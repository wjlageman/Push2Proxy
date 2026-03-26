# Push2/builtins/ModeModule.py
#
# Builtin module that consumes ModeObserver events via:
#   ModuleManager.emit_mode_change(payload) -> ModuleAPI.on_mode_change(api, payload)
#
# Also provides canonical screen_mode/matrix behavior via:
#   ModuleManager.emit_set_screen_mode(...) -> ModuleAPI.on_set_screen_mode(api, payload)
#
# Notes:
# - No IoManager singletons here: use api.send/api.upsert/api.emit_* only.
# - ModeObserver payloads are already normalized (button names, mode strings).

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from ..ModuleAPI import ModuleAPI
from ..utils import fmt_exc, call_stack


_layout_mode: Tuple[str, str] = ("<unknown>", "<unknown>")

_modes_component: Optional[str] = None
_mixer_component: Optional[str] = None
_layout_component: Optional[str] = None
_active_mode_buf: List[str] = []

_appointed_device: str = "<no_device>"
_appointed_device_locked: Any = "<unknown>"


def init_module(api: ModuleAPI) -> None:
    api.id = "builtin.mode"
    api.on_mode_change = _on_mode_change
    api.on_set_screen_mode = _set_screen_mode


def layout_mode() -> Tuple[str, str]:
    return _layout_mode


def _on_mode_change(api: ModuleAPI, payload: Any) -> None:
    #api.send('debug', 'IN MODEMODULE ON_MODE_CHANGE', payload)
    if not isinstance(payload, dict):
        return

    kind = payload.get("kind")

    if kind == "hook":
        component = payload.get("component")
        mode = payload.get("mode")
        if isinstance(component, str):
            _handle_hook(api, component, mode, payload.get("device_context"))
        return

    if kind == "button":
        button_name = payload.get("button_name")
        note = payload.get("note")
        value = payload.get("value")
        if isinstance(button_name, str):
            _handle_button(api, button_name, note, value)
        return


def _handle_hook(api: ModuleAPI, component: str, mode: Any, device_context: Any) -> None:
    global _modes_component, _mixer_component, _layout_component, _active_mode_buf
    global _appointed_device, _appointed_device_locked, _layout_mode

    if mode in ("null", "default", "Generic", "None", None):
        return

    if component == "ModesComponent":
        _modes_component = str(mode)
        _active_mode_buf.insert(0, _modes_component)

        if _modes_component == "device":
            if isinstance(device_context, dict):
                dn = device_context.get("appointed_device_name")
                if isinstance(dn, str) and dn:
                    _appointed_device = dn
                    if _appointed_device == "LiveAPI_Push2_Wrapper":
                        _appointed_device = "<no_device>"

                if "locked" in device_context:
                    _appointed_device_locked = 1 if bool(device_context.get("locked")) else 0
        return

    if component == "MessengerModesComponent":
        v = str(mode)

        if v == _layout_component:
            return

        if v in ("play", "sequence", "split_melodic_sequencer"):
            return

        if v == "sequencer_velocity_levels":
            v = "sequencer_16_velocities"
        elif v == "64pads":
            v = "drums_64_pads"
        elif v == "sequencer_loop":
            v = "drums_loop_selector"

        _layout_component = v
        _layout_mode = ("drums", v)

        if api.upsert("matrix_mode", "keys", {"layout": v}):
            api.emit_data("matrix_mode", "keys", "layout")
        if v == "session":
            set_matrix_mode(api, "session", 1)
        else:
            set_matrix_mode(api, "keys", 1)
        return

    if component == "MelodicComponent":
        v = str(mode)

        if v == _layout_component:
            return

        if v == "split_melodic_sequencer":
            v = "melodic_sequencer_plus_32_notes"
        if v == "sequence":
            v = "melodic_sequencer"
        elif v == "play":
            v = "melodic_64_notes"

        _layout_component = v
        _layout_mode = ("melodic", v)

        if api.upsert("matrix_mode", "keys", {"layout": v}):
            api.emit_data("matrix_mode", "keys", "layout")
        return

    if component in ("TrackOrRoutingControlChooserComponent", "MixerControlComponent"):
        _mixer_component = str(mode)
        return

    _active_mode_buf.insert(0, str(mode))


def _handle_button(api: ModuleAPI, button_name: str, note: Any, value: Any) -> None:
    global _modes_component, _mixer_component, _layout_component, _active_mode_buf
    global _appointed_device, _appointed_device_locked

    #api.send('debug', 'HANDLE BUTTON', 'NAME', button_name, 'NOTE', note, 'VALUE', value)

    try:
        v = int(value)
    except Exception:
        return

    # Coalescing window start on press
    if v >= 64:
        _modes_component = None
        _mixer_component = None
        _layout_component = None
        _active_mode_buf.clear()
        _appointed_device = "<no_device>"
        _appointed_device_locked = "<unknown>"
        return

    # On release, flush consolidated state
    if button_name in ("session", "note"):
        if button_name == "session":
            set_matrix_mode(api, "session", 1)
        else:
            set_matrix_mode(api, "keys", 1)

    elif button_name in ("left_arrow", "right_arrow", "up_arrow", "down_arrow"):
        # Preserve old behavior (for now): arrow release triggers a redring snapshot.
        try:
            from ..observers.RedringObserver import RedringObserver
            RedringObserver.redraw_frame(True)
        except Exception:
            pass

    elif _modes_component == "device":
        #api.send('debug', 'MODEMODULE MODES_COMPONENT', 'device')
        api.send("data", "mode", "device", _appointed_device, "locked", _appointed_device_locked)

    elif _mixer_component:
        #api.send('debug', 'MODEMODULE MIXER_COMPONENT', _mixer_component)
        if _mixer_component == "mix":
            if api.upsert("mixer", "mode", "track"):
                api.emit_data("mixer", "mode")
        elif _mixer_component == "send_slot_one":
            if api.upsert("mixer", "mode", "A sends"):
                api.emit_data("mixer", "mode")
        elif _mixer_component == "send_slot_two":
            if api.upsert("mixer", "mode", "B sends"):
                api.emit_data("mixer", "mode")
        elif _mixer_component == "send_slot_three":
            if api.upsert("mixer", "mode", "C sends"):
                api.emit_data("mixer", "mode")
        elif _mixer_component == "send_slot_four":
            if api.upsert("mixer", "mode", "D sends"):
                api.emit_data("mixer", "mode")
        elif _mixer_component == "send_slot_five":
            if api.upsert("mixer", "mode", "E sends"):
                api.emit_data("mixer", "mode")
        elif _mixer_component == "send_slot_six":
            if api.upsert("mixer", "mode", "F sends"):
                api.emit_data("mixer", "mode")
        else:
            if api.upsert("mixer", "mode", _mixer_component):
                api.emit_data("mixer", "mode")

    elif _modes_component == "clip":
        # Screen_mode is a Push UI concern. Route via ModuleManager -> ModeModule.
        #api.send('debug', 'MODEMODULE SET_SCREEN_MODE CLIP', 1, 'MODES_COMPONENT = CLIP')
        api.set_screen_mode("clip", 1)

    elif _modes_component == "scales":
        if api.upsert("scales", "visible", 1):
            api.emit_data("scales", "visible")
        #api.send('debug', 'MODEMODULE SET_SCREEN_MODE SCALES', 1, 'MODES_COMPONENT = SCALES')
        api.set_screen_mode("scales", 1)

    # Reset after flush
    _modes_component = None
    _mixer_component = None
    _layout_component = None
    _active_mode_buf.clear()
    _appointed_device = "<no_device>"
    _appointed_device_locked = "<unknown>"
    return


def set_matrix_mode(api: ModuleAPI, key: str, visibility: Any) -> None:
    visible = 1 if (visibility == 1 or visibility is True) else 0
    #if api.upsert("matrix_mode", key, {"visible": visible}):
    if api.upsert("matrix_mode", key, 'visible', visible):
        api.emit_data("matrix_mode", key)

    if key == "session":
        if api.upsert("matrix_mode", "keys", "visible", 0 if visible else 1):
            api.emit_data("matrix_mode", "keys")
    elif key == "keys":
        if api.upsert("matrix_mode", "session", "visible", 0 if visible else 1):
            api.emit_data("matrix_mode", "session")
    else:
        api.send("error", "set_matrix_mode: key must be 'session' or 'keys'", "key", key)


def _set_screen_mode(api: ModuleAPI, payload: Any) -> None:
    try:
        if not isinstance(payload, dict):
            api.error("set_screen_mode: invalid payload type", type(payload).__name__, payload)
            return

        key = payload.get("key")
        if not isinstance(key, str) or not key:
            api.error("set_screen_mode: missing or invalid key", payload)
            return

        state = payload.get('state')

        try:
            screen_mode = api.select('screen_mode') or {}
        except Exception:
            screen_mode = {}

        #api.send('debug', 'IN MODEMODULE SET_SCREEN_MODE', '\nKEY', key, '\nSTATE', state, '\nCURRENT_MODE', screen_mode, '\nPAYLOAD', payload, '\n', call_stack())

        mode_list = ('device', 'clip', 'mix', 'browse', 'add_track', 'add_device', 'scales', 'quantization', 'convert', 'fixed_length', 'setup', 'user')

        if key == 'fixed_length_selectors':
            key = 'fixed_length'
        #new_mode = None

        if key == 'state':
            if not isinstance(state, dict):
                api.send('error', 'Screen-mode state payload is not a dict', state)
                return
            main_mode = state.get('main_mode')
            new_mode = main_mode

            screen_mode['main_mode'] = main_mode
            screen_mode['global_mix_mode'] = state.get('global_mix_mode')
            screen_mode['mix_mode'] = state.get('mix_mode')
            screen_mode['device_mode'] = state.get('device_mode')
        elif state == 0:
            # mode/popup ended -> fall back to main_mode remembered in cache
            new_mode = screen_mode.get('main_mode')
            if not new_mode:
                api.send('error', 'Main_mode is not set in screen_mode cache')
                return
        elif key in mode_list:
            new_mode = key
        elif key == 'globals':
            pass
        elif key == 'live_dialog':
            return
        else:
            api.send('log', 'Warning: Screen-mode', key, 'is unknown')
            return

        screen_mode['current_mode'] = new_mode
        for k in mode_list:
            screen_mode[k] = 1 if k == new_mode else 0

        #api.send('debug', 'IN MODEMODULE SET_SCREEN_MODE SCREEN_MODE', screen_mode)

        api.upsert('screen_mode', screen_mode)
        api.emit_json('screen_mode')
        return

    except Exception as ex:
        api.send('error', fmt_exc('IN MODEMODULE SET_SCREEN_MODE', ex))
        return
