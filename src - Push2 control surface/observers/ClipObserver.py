# File: observers/ClipObserver.py
# observers/ClipObserver.py
#
# Observes Live's detail clip + detail clip slot (Song.view).
# Emits surface_update events via ModuleManager:
# - full-model-update: { clipSlot: {...}, selectedClip: {...} }
# - path-model-update: [ [path, value] ]
#
# Listener policy:
# - Never writes to Data/Cache (SurfaceUpdateModule owns state).
# - Never emits playing_position; only state/static properties.
# - Callbacks ignore stale objects (no remove_*_listener required).

from __future__ import annotations

from typing import Any, Dict, Set, Tuple
import traceback
from ..utils import fmt_exc


class ClipObserver(object):
    def __init__(self, host: Any, module_manager: Any, io: Any) -> None:
        self._host = host
        self._mm = module_manager
        self._io = io

        self._attached: bool = False

        self._clip_slot: Any = None
        self._clip: Any = None

        self._slot_state: Dict[str, Any] = {}
        self._clip_state: Dict[str, Any] = {}

        self._added_keys: Set[Tuple[int, str, str]] = set()

        self._slot_props = [
            "has_clip",
            "is_playing",
            "is_recording",
        ]

        self._clip_props_common = [
            "name",
            "length",
            "loop_start",
            "loop_end",
            "start_marker",
            "end_marker",
            "start_time",
            "end_time",
            "color_index",
            "is_recording",
        ]

        # Audio-only (kept here for completeness; harmless if absent)
        self._clip_props_audio_only = [
            "gain",
            "gain_display_string",
        ]

    # -------------------- host access --------------------

    def _song(self) -> Any:
        try:
            # Most ControlSurface hosts expose song() as a callable.
            fn = getattr(self._host, "song", None)
            if callable(fn):
                return fn()
        except Exception:
            pass

        try:
            # Fallback: some hosts keep it as attribute.
            return getattr(self._host, "song", None)
        except Exception:
            return None

    def _song_view(self) -> Tuple[Any, Any]:
        s = self._song()
        if not s:
            return None, None
        v = getattr(s, "view", None)
        return s, v

    # -------------------- lifecycle --------------------

    def attach(self) -> None:
        if self._attached:
            return

        try:
            s, v = self._song_view()
            if s is None:
                self._io.send("error", "ClipObserver: song() not available yet")
                return
            if v is None:
                self._io.send("error", "ClipObserver: song.view not available yet; attach later")
                return

            # Attach view listeners
            self._safe_add(v, "add_detail_clip_listener", self._on_detail_clip)
            self._safe_add(v, "add_detail_clip_slot_listener", self._on_detail_clip_slot)

            # Initial pull
            self._on_detail_clip_slot()
            self._on_detail_clip()

            self._attached = True
        except Exception as ex:
            self._io.send("error", fmt_exc("ClipObserver attach failed", ex))

    # -------------------- view callbacks --------------------

    def _on_detail_clip_slot(self) -> None:
        try:
            s, v = self._song_view()
            if v is None:
                return

            slot = getattr(v, "detail_clip_slot", None)
            if slot is self._clip_slot:
                return

            self._clip_slot = slot
            self._slot_state = self._read_slot_state(slot)
            self._emit_full_snapshot()

            # Attach slot prop listeners (ignore old slots; callbacks check current slot id)
            if slot is not None:
                self._attach_slot(slot)

        except Exception as ex:
            self._io.send("error", fmt_exc("ClipObserver detail_clip_slot failed", ex))

    def _on_detail_clip(self) -> None:
        try:
            s, v = self._song_view()
            if v is None:
                return

            clip = getattr(v, "detail_clip", None)
            if clip is self._clip:
                return

            self._clip = clip
            self._clip_state = self._read_clip_state(clip)
            self._emit_full_snapshot()

            # Attach clip prop listeners (ignore old clips; callbacks check current clip id)
            if clip is not None:
                self._attach_clip(clip)

        except Exception as ex:
            self._io.send("error", fmt_exc("ClipObserver detail_clip failed", ex))

    # -------------------- attach LOM listeners --------------------

    def _attach_slot(self, slot: Any) -> None:
        sid = id(slot)
        for prop in self._slot_props:
            try:
                add = getattr(slot, "add_%s_listener" % prop, None)
                if not callable(add):
                    continue

                def _mk(propname: str):
                    def _cb():
                        # Ignore callbacks from stale slots.
                        if self._clip_slot is None or id(self._clip_slot) != sid:
                            return
                        self._on_slot_prop(propname)
                    return _cb

                cb = _mk(prop)
                key = (sid, "add_%s_listener" % prop, prop)
                if key in self._added_keys:
                    continue

                add(cb)
                self._added_keys.add(key)
            except Exception:
                pass

    def _attach_clip(self, clip: Any) -> None:
        cid = id(clip)

        # Determine type once (used only to decide audio-only props).
        is_audio = bool(getattr(clip, "is_audio_clip", getattr(clip, "is_audio", False)))

        props = list(self._clip_props_common)
        if is_audio:
            props.extend(self._clip_props_audio_only)

        for prop in props:
            try:
                add = getattr(clip, "add_%s_listener" % prop, None)
                if not callable(add):
                    continue

                def _mk(propname: str):
                    def _cb():
                        # Ignore callbacks from stale clips.
                        if self._clip is None or id(self._clip) != cid:
                            return
                        self._on_clip_prop(propname)
                    return _cb

                cb = _mk(prop)
                key = (cid, "add_%s_listener" % prop, prop)
                if key in self._added_keys:
                    continue

                add(cb)
                self._added_keys.add(key)
            except Exception:
                pass

    # -------------------- prop callbacks --------------------

    def _on_slot_prop(self, prop: str) -> None:
        try:
            slot = self._clip_slot
            if slot is None:
                return

            new_state = self._read_slot_state(slot)
            new_val = new_state.get(prop)
            old_val = self._slot_state.get(prop)

            self._slot_state[prop] = new_val
            if new_val != old_val:
                self._emit_path_update(["clipSlot", prop], new_val)
        except Exception as ex:
            self._io.send("error", fmt_exc("ClipObserver slot prop failed", ex))

    def _on_clip_prop(self, prop: str) -> None:
        try:
            clip = self._clip
            if clip is None:
                return

            new_state = self._read_clip_state(clip)
            new_val = new_state.get(prop)
            old_val = self._clip_state.get(prop)

            self._clip_state[prop] = new_val
            if new_val != old_val:
                self._emit_path_update(["selectedClip", prop], new_val)
        except Exception as ex:
            self._io.send("error", fmt_exc("ClipObserver clip prop failed", ex))

    # -------------------- state reads --------------------

    def _read_slot_state(self, slot: Any) -> Dict[str, Any]:
        if slot is None:
            return {
                "present": 0,
                "has_clip": 0,
                "is_playing": 0,
                "is_recording": 0,
            }

        def _b(name: str) -> int:
            try:
                v = getattr(slot, name, None)
                return 1 if bool(v) else 0
            except Exception:
                return 0

        st: Dict[str, Any] = {}
        st["present"] = 1
        st["has_clip"] = _b("has_clip")
        st["is_playing"] = _b("is_playing")
        st["is_recording"] = _b("is_recording")
        return st

    def _read_clip_state(self, clip: Any) -> Dict[str, Any]:
        if clip is None:
            return {
                "present": 0,
                "name": "<no_clip>",
                "type": "<empty>",
            }

        is_midi = bool(getattr(clip, "is_midi_clip", getattr(clip, "is_midi", False)))
        clip_type = "midi" if is_midi else "audio"

        def _get(name: str, default: Any = "<empty>") -> Any:
            try:
                v = getattr(clip, name, None)
                if v is None:
                    return default
                if isinstance(v, (int, float, bool, str)):
                    # Preserve 0/False as-is.
                    return v
                return v
            except Exception:
                return default

        st: Dict[str, Any] = {}
        st["present"] = 1
        st["type"] = clip_type
        for k in self._clip_props_common:
            st[k] = _get(k)

        # Audio-only (if present).
        st["gain"] = _get("gain")
        st["gain_display_string"] = _get("gain_display_string")

        return st

    # -------------------- dispatch helpers --------------------

    def _emit_full_snapshot(self) -> None:
        # full-model-update: lets SurfaceUpdateModule store + emit via default flow
        try:
            payload = {
                "message": "clip_observer",
                "logger": "clip_observer",
                "level": "DEBUG",
                "levelno": 10,
                "pathname": "ClipObserver.py",
                "lineno": 0,
                "func": "_emit_full_snapshot",
                "exc_info": None,
                "object": {
                    "command": "full-model-update",
                    "payload": {
                        "clipSlot": dict(self._slot_state),
                        "selectedClip": dict(self._clip_state),
                    },
                },
            }
            self._mm.emit_surface_update(payload)
        except Exception as ex:
            self._io.send("error", fmt_exc("ClipObserver emit full snapshot failed", ex))

    def _emit_path_update(self, path, value) -> None:
        # path-model-update: list of pairs (path, value)
        try:
            payload = {
                "message": "clip_observer",
                "logger": "clip_observer",
                "level": "DEBUG",
                "levelno": 10,
                "pathname": "ClipObserver.py",
                "lineno": 0,
                "func": "_emit_path_update",
                "exc_info": None,
                "object": {
                    "command": "path-model-update",
                    "payload": [
                        [path, value],
                    ],
                },
            }
            self._mm.emit_surface_update(payload)
        except Exception as ex:
            self._io.send("error", fmt_exc("ClipObserver emit path update failed", ex))

    # -------------------- safe add --------------------

    def _safe_add(self, obj: Any, add_name: str, fn: Any) -> None:
        try:
            add = getattr(obj, add_name, None)
            if not callable(add):
                return

            key = (id(obj), add_name, getattr(fn, "__name__", "cb"))
            if key in self._added_keys:
                return

            add(fn)
            self._added_keys.add(key)
        except Exception:
            try:
                self._io.send("error", "ClipObserver: add listener failed", add_name, traceback.format_exc())
            except Exception:
                pass
