# builtins/SurfaceUpdateModule.py
#
# Builtin module that processes surface_update events (sanitized logging records)
#
# What this module is for (Max-focused)
# ------------------------------------
# SurfaceUpdateObserver installs a logging handler on Python's root logger and forwards
# every LogRecord as a small sanitized payload:
#     { "message": <text>, "object": <dict/list/tuple or None>, ... }
#
# This module consumes that payload and extracts the few event families that are
# useful for Max, without requiring Max to parse Python logging internals:
#
# 1) Push2 model updates emitted by Live/Push2 runtime (structured objects):
#    - command: "full-model-update"  (payload is dict)
#    - command: "path-model-update"  (payload is list of [path, value] items)
#
# 2) LCD display string messages (text-only fallback):
#    - "set_display_string" logs (we try to decode the string literal)
#
# Notes / limitations
# -------------------
# - This module is intentionally "best effort" and defensive: we do not want logging
#   content changes in Live to crash the script.
# - We do NOT attempt to discover or reconstruct "raw" hardware button presses here.
#   Those come via MIDI hooks (MidiObserver) and only when the host routes them.
# - We keep the output shape stable because Max patches depend on it.
#
# Services required (provided via ModuleAPI by ModuleManager):
# - api.send(...)
# - api.upsert(...)
# - api.emit_data(...) / api.emit_path(...)
# - api.select(...)
# - api.mangle_key(key)
# - api.set_screen_mode(key, visible)

from __future__ import annotations

import ast
import json
import re
import sys
import time
import traceback
from typing import Any, Dict, Optional

from ..utils import caller_atom, fmt_exc
from ..ModuleAPI import ModuleAPI


def init_module(api: ModuleAPI) -> None:
    api.id = "builtin.surface_update"
    api.on_surface_update = _on_surface_update


# -------------------------
# Event entrypoint
# -------------------------

def _on_surface_update(api: ModuleAPI, payload: dict) -> None:
    try:
        message = payload.get("message")
        obj = payload.get("object")

        # If we did not get a structured object, try LCD text extraction only.
        if not obj:
            _emit_lcd_message(api, message)
            return

        if isinstance(obj, dict):
            cmd = obj.get("command")
            cmd_payload = obj.get("payload")

            if cmd == "full-model-update":
                _handle_full_model_update(api, cmd_payload)
                _emit_lcd_message(api, message)
                return

            if cmd == "path-model-update":
                _handle_path_model_update(api, cmd_payload, message)
                _emit_lcd_message(api, message)
                return

            api.send("debug", "other.command", cmd if cmd else "<empty>", "obj", obj)

        _emit_lcd_message(api, message)

    except Exception as e:
        api.send("error", fmt_exc("SurfaceUpdateModule failed", e))


# -------------------------
# Legacy-normalization helpers (pure functions)
# -------------------------

def _should_skip_key(mangled_key: str) -> bool:
    return mangled_key in (
        "id", "channel_id", "object_id", "visualization_real_time_channel_id",
        "playhead_real_time_channel_id", "waveform_real_time_channel_id",
        "realtime_channel_id", "icon", "value_item_images", "value_item_small_images",
        "shrink_parameters", "value_item_image", "value_item_small_image",
        "realtime_channel",
    )


def _normalize(api: ModuleAPI, obj: Any) -> Any:
    if obj is None:
        return None

    if isinstance(obj, str):
        if obj == "":
            return None
        return obj

    if isinstance(obj, dict):
        keys_to_delete = []
        for k in list(obj.keys()):
            mangled_key = api.mangle_key(k)
            if _should_skip_key(mangled_key):
                keys_to_delete.append(k)

        for k in keys_to_delete:
            try:
                del obj[k]
            except Exception:
                pass

        # Full-model-update should also land in snake_case.
        normalized_obj = {}
        for k, v in list(obj.items()):
            mangled_key = api.mangle_key(k) if isinstance(k, str) else k
            normalized_obj[mangled_key] = _normalize(api, v)

        return normalized_obj

    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = _normalize(api, obj[i])
        return obj

    return obj


def _scalar_norm(v: Any) -> Any:
    if v is None:
        return "<empty>"
    if isinstance(v, str) and v == "":
        return "<empty>"
    return v


def _note_to_midi(note_str: Any) -> Optional[int]:
    if not isinstance(note_str, str):
        return None

    note_index = {
        "C": 0,  "C♯": 1,  "C#": 1,  "C𝄪": 2,  "C♭": 11, "C𝄫": 10,
        "D": 2,  "D♯": 3,  "D#": 3,  "D𝄪": 4,  "D♭": 1,  "D𝄫": 0,
        "E": 4,  "E♯": 5,            "E𝄪": 6,  "E♭": 3,  "E𝄫": 2,
        "F": 5,  "F♯": 6,  "F#": 6,  "F𝄪": 7,  "F♭": 4,  "F𝄫": 3,
        "G": 7,  "G♯": 8,  "G#": 8,  "G𝄪": 9,  "G♭": 6,  "G𝄫": 5,
        "A": 9,  "A♯": 10, "A#": 10, "A𝄪": 11, "A♭": 8,  "A𝄫": 7,
        "B": 11, "B♯": 0,            "B𝄪": 1,  "B♭": 10, "B𝄫": 9,
    }

    note_re = re.compile(r"^([A-G])([#♯]?)(-?\d+)$")
    m = note_re.match(note_str)
    if not m:
        return None

    note, accidental, octave_str = m.groups()
    key = note + accidental
    try:
        octave = int(octave_str)
    except Exception:
        return None

    idx = note_index.get(key)
    if idx is None:
        return None

    midi = (octave + 2) * 12 + idx
    if midi < 0 or midi > 127:
        return None

    return midi


# -------------------------
# Update handlers (legacy logic, via ModuleAPI)
# -------------------------

def _update(api: ModuleAPI, payload: Any) -> None:
    json_cache = api.select()
    if not json_cache:
        api.send("error", "Update_cached_json json cache bucket missing: _push2_state_info['json']")
        return

    for path, value in payload:
        if not isinstance(path, (list, tuple)) or not path:
            api.send("error", "_update: invalid path", path)
            continue

        # Path-model-update arrives in camelCase on all string segments.
        # Full-model-update ends up snake_case via _normalize(). So normalize the whole path here.
        normalized_path = []
        for seg in path:
            if isinstance(seg, str):
                normalized_path.append(api.mangle_key(seg))
            else:
                normalized_path.append(seg)

        mangled_key = api.mangle_key(normalized_path[0]) if isinstance(normalized_path[0], str) else normalized_path[0]
        if mangled_key == "notification":
            continue

        obj = api.select(normalized_path[:-1])
        prop = normalized_path[-1]
        if obj is None:
            # Legacy intent: if this update is about visibility, still try to update screen_mode state.
            if prop == "visible":
                api.set_screen_mode(mangled_key, _scalar_norm(value))
            elif mangled_key == "live_dialog":
                api.send("log", "live_dialog", value)
            else:
                api.send("error", "json cache entry for", mangled_key, normalized_path[1:], "not found", "value", value, "path", normalized_path, "prop", prop)
            continue

        # Resolve old_value safely for dict OR list containers.
        old_value = "<empty>"
        try:
            if isinstance(obj, dict):
                old_value = _scalar_norm(obj.get(prop))
            elif isinstance(obj, list) and isinstance(prop, int) and 0 <= prop < len(obj):
                old_value = _scalar_norm(obj[prop])
        except Exception:
            old_value = "<empty>"

        new_value = _scalar_norm(value)

        if new_value == old_value:
            continue

        # String-based special cases (legacy behavior)
        if isinstance(new_value, str):
            split = new_value.split(" ")

            if split and len(split) >= 4 and split[0] in ("Play", "Sequence"):
                if api.upsert("matrix_mode", "keys", "notes", {"from": split[1], "to": split[3]}):
                    api.emit_data("matrix_mode", "keys", "notes")
                if api.upsert("matrix_mode", "keys", "midi", {"from": _note_to_midi(split[1]), "to": _note_to_midi(split[3])}):
                    api.emit_data("matrix_mode", "keys", "midi")
                continue

            if split and split[0] in ("Melodic:", "Drums:", "Slicing:"):
                mangled_value = new_value.replace(" ", "_").replace(":", "").replace("+", "plus").lower()
                #api.send("debug", "_UPDATE", "LATOUT", "SPLIT[0]", split[0], "SPLIT[1]", split[1] if len(split) > 1 else "<empty>", "NEW_VALUE", new_value, "MANGLED_VALUE", mangled_value)
                if api.upsert("matrix_mode", "keys", "layout", mangled_value): 
                    api.emit_data("matrix_mode", "keys", "layout")
                continue

        # Regular updates
        if prop == "visible":
            if mangled_key not in ("notification",):
                api.set_screen_mode(mangled_key, new_value)
            continue

        # Write into container best-effort (matches your old “try/except pass” behavior)
        try:
            if isinstance(obj, dict):
                obj[prop] = value
            elif isinstance(obj, list) and isinstance(prop, int) and prop >= 0:
                while len(obj) <= prop:
                    obj.append(None)
                obj[prop] = value
        except Exception:
            pass

        subpath2 = normalized_path[1:-1]
        mix_mode = api.select(("screen_mode", "mix_mode"))
        api.send("data", mangled_key, subpath2, prop, new_value)

        try:
            if len(subpath2) > 0 and subpath2[0] == "parameters":
                api.send("data", "visible_parameters", subpath2, "=>", prop, new_value)
            if (
                len(subpath2) > 0 and
                mix_mode == "global" and
                subpath2[0] in ("volume_control_list_view", "pan_control_list_view", "send_control_list_view") and
                subpath2[1] == "parameters"
            ):
                api.send("data", "visible_parameters", subpath2[1:], "=>", prop, new_value)
            if len(subpath2) > 0 and mix_mode == "track" and subpath2[0] == "track_control_view" and subpath2[2] == "parameters":
                api.send("data", "visible_parameters", subpath2[2:], "=>", prop, new_value)
        except Exception:
            pass


def _parameters(api: ModuleAPI, params: Any, device: Any, visible: Any) -> None:
    try:
        _atoms = list()
        _atoms_original = list()
        if isinstance(params, list):
            while len(params) < 8:
                inactive_param = {"is_active": False, "is_enabled": False}
                params.append(inactive_param)

            index: int = 1
            for param in params:
                if not param:
                    params[index - 1] = {"is_active": False, "is_enabled": False}
                    param = params[index - 1]  # <- BELANGRIJK

                if isinstance(param, dict):
                    param["index"] = index
                index += 1

                name = "<empty>"
                try:
                    name = param.get("name").strip()
                except Exception:
                    pass

                original_name = "<empty>"
                try:
                    original_name = param.get("original_name").strip()
                except Exception:
                    pass

                _atoms.append(name if name else "<empty>")
                _atoms_original.append(original_name if original_name else "<empty>")
        else:
            _atoms = "<empty>"

        obj = dict()
        obj["parameters"] = params or "<empty>"
        obj["device"] = device or "<empty"
        obj["names"] = _atoms or "<empty>"
        obj["original_names"] = _atoms_original or "<empty>"
        obj["visible"] = visible or "<empty>"
    except Exception as ex:
        api.send("error", fmt_exc("Cannot create parameter set", ex))
        obj = "<empty>"

    api.send("update", "visible_parameters")
    api.upsert("visible_parameters", obj)
    api.emit_json("visible_parameters")


def _walk_and_debug(api, data, prefix=""):
    try:
        #_io.send('debug', '_walk_and_debug', 'caller', _io.caller_atom())
        if isinstance(data, dict):
            for k, v in data.items():
                keypath = f"{prefix}.{k}" if prefix else str(k)
                # _walk_and_debug(api, v, keypath)
        elif isinstance(data, (list, tuple)):
            for i, v in enumerate(data):
                keypath = f"{prefix}[{i}]"
                # _walk_and_debug(api, v, keypath)
        else:
            try:
                s = str(data)
            except Exception:
                s = "<unprintable>"
            api.send("debug", prefix or "<root>", s)
    except Exception as ex:
        api.send('error', _fmt_exc("Dispatcher failed", ex))


def _handle_full_model_update(api: ModuleAPI, payload: Any) -> None:
    if not isinstance(payload, dict):
        return

    for k, v in payload.items():
        # BUGFIX #1:
        # mangled_key must be available for any debug branch that references it.
        # Compute it once at top of the loop.
        mangled_key = api.mangle_key(k)
        api.send("debug", "---- FULL_MODEL_UPDATE key:", mangled_key, "original_key", k)

        if k == "visualisationSettings":
            api.send("debug", "---- FULL_MODEL_UPDATE key:", mangled_key, "original_key", k, "SPECIAL_CASE")
            # _walk_and_debug(api, v)

        if k in (
            "editModeOptionsView", "stepAutomationSettingsView", "visualisationSettings",
            "controls", "firmwareSwitcher", "firmwareUpdate", "realTimeClient", "deviceVisualisation",
            "playhead_real_time_channel_id", "waveform_real_time_channel_id", "notificationView",
            "live_dialog", "liveDialogView"
        ):
            continue

        t0 = time.perf_counter()
        v = _normalize(api, v)
        t1 = time.perf_counter()

        report_data = True

        if k == "hardwareInfo":
            api.send("debug", "---- FULL_MODEL_UPDATE key:", mangled_key, "original_key", k, "SPECIAL_CASE")
            system_info = dict()

            firmwareVersion = v.get("firmware_version") if isinstance(v, dict) else None
            try:
                system_info["firmware_version"] = (
                    str(firmwareVersion.get("build")) + "." +
                    str(firmwareVersion.get("major")) + "." +
                    str(firmwareVersion.get("minor"))
                )
            except Exception:
                system_info["firmware_version"] = "<empty>"

            try:
                system_info["serial_number"] = v.get("serial_number")
            except Exception:
                system_info["serial_number"] = "<empty>"

            full = sys.version
            py_ver = full.split()[0]
            system_info["python_version"] = py_ver
            m = re.search(r"\((?:[^,]*,\s*)([^)]*)\)", full)
            py_ts = m.group(1) if m else ""
            system_info["python_date"] = py_ts
            v = system_info

            if api.upsert(mangled_key, system_info):
                api.emit_data(mangled_key)
            else:
                api.send("reset_blend")
            continue

        elif k == "deviceParameterView":
            api.send("debug", "---- FULL_MODEL_UPDATE key:", mangled_key, "original_key", k, "PARAMETER BANK START")
            try:
                params = v.get("parameters", None)
                dev = v.get("device", None)
                try:
                    dev["type"] = "<empty>"
                    dev["type"] = v.get("device_type") or "<empty>"
                except Exception:
                    pass
                visible = v.get("visible")
                if visible:
                    _parameters(api, params, dev, visible)
            except Exception:
                pass
            report_data = False

        elif k == "simplerDeviceView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k, "SPECIAL_CASE")
            try:
                params = v.get("parameters")
                dev = v.get("device")
                try:
                    dev["type"] = "<empty>"
                    dev["type"] = v.get("device_type") or "<empty>"
                except Exception:
                    pass
                visible = v.get("visible")
                if visible:
                    _parameters(api, params, dev, visible)
            except Exception as ex:
                api.send("error", fmt_exc("Simpler error", ex))
            report_data = False

        elif k == "compressorDeviceView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k, "SPECIAL_CASE")
            try:
                params = v.get("parameters")
                dev = v.get("device")
                try:
                    dev["type"] = "<empty>"
                    dev["type"] = v.get("device_type") or "<empty>"
                except Exception:
                    pass
                visible = v.get("visible")
                if visible:
                    _parameters(api, params, dev, visible)
            # BUGFIX #2:
            # Was "except:" and then used ex -> unbound local.
            except Exception as ex:
                api.send("error", fmt_exc("Compressor error", ex))
            report_data = False

        elif k == "mixerView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)
            try:
                v.pop("realtime_meter_data")
            except Exception as ex:
                api.send("error", "Error deleting subkey", ex)

            try:
                for subkey, subview in v.items():
                    if subkey == "volume_control_list_view" and subview.get("visible"):
                        name = "Volumes"
                        params = subview.get("parameters")
                        _parameters(api, params, {"name": name}, True)
                        break
                    elif subkey == "pan_control_list_view" and subview.get("visible"):
                        name = "Pans"
                        params = subview.get("parameters")
                        _parameters(api, params, {"name": name}, True)
                        break
                    elif subkey == "send_control_list_view" and subview.get("visible"):
                        name = "Sends to "
                        params = subview.get("parameters")
                        n2 = params[0].get("name")
                        name += n2
                        _parameters(api, params, {"name": name}, True)
                        break
                    elif subkey == "track_control_view" and subview.get("track_mix").get("visible"):
                        name = "Track"
                        subview = subview.get("track_mix")
                        params = subview.get("parameters")
                        _parameters(api, params, {"name": name}, True)
                        break
            except Exception as ex:
                api.send("error", "SPECIAL_CASE MIXER", fmt_exc("Error in MixerView", ex))

            report_data = False

        elif k == "mixerSelectView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)
            # _walk_and_debug(api, v)

        elif k == "midiClipSettingsView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)
            # _walk_and_debug(api, v)

        elif k == "midiLoopSettingsView" or k == "audioLoopSettingsView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)
            params = v.get("loop_parameters") or []

            # Display in parameter view only if there is at least 1 parameter
            if len(params) > 0:
                # Some builds/states have no audio_params -> treat as empty list.
                audio_clip = api.select("audio_clip") or {}
                audio_params = []
                try:
                    audio_params = audio_clip.get("audio_parameters") or []
                except Exception:
                    audio_params = []

                inactive_param = {"is_active": False, "is_enabled": False}
                params.append(inactive_param)

                # Append only available audio parameters (no fixed indices).
                if isinstance(audio_params, list):
                    for p in audio_params:
                        api.send('debug', 'LOOP_PARAMETERS', p)
                        if p["name"] == 'Detune':
                            continue
                        params.append(p)

                clip = v.get("clip")
                _parameters(api, params, clip, True)

            # _walk_and_debug(api, v)

        elif k == "audioClipSettingsView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)
            # _walk_and_debug(api, v)

        elif k == "trackMixerSelectView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)

        elif k == "panControlListView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)

        elif k == "tracklistView":
            api.send("debug", "[-]SELECTED_TRACK VIA TRACKLISTVIEW")
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)
            # _walk_and_debug(api, v)
            api.send("debug", "---- mangled_key:", mangled_key, "key", k, 'V', '\n', v)
            try:
                v.pop("playhead_real_time_channels")
            except Exception:
                pass
            try:
                index = v.pop("absolute_selected_track_index")
                selected = v.get("selected_track")
                selected["index"] = index
            except Exception as ex:
                api.send("debug", "ERROR", ex)
            """
            try:
                tracks = v.pop("tracks")
                v["tracks"] = {str(i): v for i, v in enumerate(tracks)}
                pass
            except Exception as ex:
                api.send("debug", "ERROR", ex)
            """

        elif k == "devicelistView":
            api.send("debug", "[-]SELECTED_DEVICE VIA DEVICELISTVIEW")
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)
            #_walk_and_debug(api, v)
            """
            try:
                items = v.pop("items")
                v["items"] = {str(i): v for i, v in enumerate(items)}
            except Exception as ex:
                api.send("debug", "ERROR", ex)
            """

        elif k == "quantizeSettingsView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)
            try:
                v["quantization_option_names"] = ["1/4", "1/8", "1/8T", "1/16", "1/16T", "1/16+T", "1/16+T", "1/32"]
            except Exception:
                pass
            report_data = False

        elif k == "browserData":
            api.send("debug", "---- mangled_key:", mangled_key, "key")
            api.send("debug", "BROWSER_DATA", mangled_key, k, "V", v if v else "<empty>")
            report_data = True

        elif k == "modeState":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k, v)
            if v.get("main_mode") is None:
                api.send("update", "global_state")
                if api.upsert("global_state", "push2proxy_inactive"):
                    api.emit_json("global_state")
            api.set_screen_mode("state", v)
            report_data = False
            continue

        elif k == "convertView":
            api.send("debug", "---- mangled_key:", mangled_key, "key", k, "v", v)
            # _walk_and_debug(api, v)
            if isinstance(v, dict) and "visible" in v:
                api.set_screen_mode("convert", v.get("visible"))

        elif k in (
            "importantGlobals",
            "fixedLengthSelectorView",
            "fixedLengthSettings",
            "scalesView",
            "setupView",
            "convertView",
            "noteSettingsView",
            "browserData",
            "browserView",
        ):
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)
            report_data = False

        elif k in (
            "modeState",
            "mixerSelectView",
            "trackMixerSelectView",
            "chainListView",
            "stepSettingsView",
            "parameterBankListView",
            "editModeOptionsView",
            "notificationView",
            "stepAutomationSettingsView",
            "clipSlot",
            "selectedClip",
        ):
            api.send("debug", "---- mangled_key:", mangled_key, "key", k)

        else:
            api.send("debug", "---- KEY:", k, "NOT FOUND")

        if v is None:
            v = "<empty>"

        if api.upsert(mangled_key, v):
            api.send("update", mangled_key)
            api.emit_json(mangled_key)

            try:
                if mangled_key == "screen_mode":
                    api.set_screen_mode(v.get("main_mode"), 1)
            except Exception:
                pass

        t2 = time.perf_counter()
        # api.send("log", "duration", "normalization", (t1 - t0) * 1000, "ms", "parsing and sending", (t2 - t1) * 1000, "ms", "total duration", (t2 - t0) * 1000, "ms")


def _handle_path_model_update(api: ModuleAPI, payload: Any, message: str) -> None:
    api.send('debug', 'PATH_MODEL_UPDATE', 'PAYLOAD', payload, 'MESSAGE', message)
    if not isinstance(payload, list):
        return

    try:
        if payload and "notificationView" in str(payload[0]) and len(payload) >= 2:
            api.send("log", "NotificationView", "message", payload[-1])
    except Exception as ex:
        api.send("error", ex)

    _update(api, payload)


def _emit_lcd_message(api: ModuleAPI, text: str) -> None:
    if not isinstance(text, str):
        return

    # Send the text that is displayed on the LCD to Max (best-effort).
    # These originate from Push2/Live internals; we only decode string payloads.
    if ("set_display_string" in text) or text.startswith("display:DisplayDataSource.set_display_string -> "):
        raw = text.split("-> ", 1)[1].strip() if "-> " in text else text
        if (raw.startswith("'") and raw.endswith("'")) or (raw.startswith('"') and raw.endswith('"')):
            try:
                decoded = ast.literal_eval(raw)
            except Exception:
                decoded = raw.strip("'").strip('"')
        else:
            decoded = raw

        # We keep mode placeholder here. If you ever want mode, wire an explicit service in ModuleAPI.
        mode = "<unknown>"
        api.send("data", "display_text", decoded, mode)


