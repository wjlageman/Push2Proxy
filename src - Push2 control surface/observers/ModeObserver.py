# File: Push2/observers/ModeObserver.py
# Push2/observers/ModeObserver.py
#
# Observer that detects Push2 mode/layout changes by patching a small set of
# mode-related methods in the original Push2 runtime.
#
# Responsibilities (ONLY):
# - Pick up raw mode/layout changes (hooks)
# - Pick up raw MIDI mode button presses/releases (via mode_button_event)
# - Normalize/clean the raw values (strings, None)
# - Forward a single payload shape to ModuleManager.emit_mode_change(...)
#
# No business logic here:
# - No Data.upsert / emit_data / set_screen_mode / set_matrix_mode
# - No mixer/clip/scales logic
#
# Push2Proxy should call:
#     from .observers.ModeObserver import ModeObserver
#     self._mode_observer = ModeObserver(self._host, self._module_manager, self._io)
#     self._mode_observer.start()
#
# And forward MIDI note events for mode buttons to:
#     self._mode_observer.mode_button_event(note, value)

from __future__ import annotations

import sys
import types
from typing import Any, Dict, Optional


class ModeObserver(object):
    def __init__(self, host: Any, module_manager: Any, io: Any) -> None:
        self._host = host
        self._module_manager = module_manager
        self._io = io
        self._started = False

        # For future use (routing raw CC/button events into mode semantics).
        self._MODE_BUTTON_CCS: Dict[int, str] = {
            110: "device",
            113: "clip",
            112: "mix",

            50: "note",
            51: "session",
            58: "scale",

            59: "user",
            111: "browse",
            52: "add_device",
            53: "add_track",

            102: "select_0",
            103: "select_1",
            104: "select_2",
            105: "select_3",
            106: "select_4",
            107: "select_5",
            108: "select_6",
            109: "select_7",
        }

        # For future use (routing arrow navigation CC/button events).
        self._ARROW_BUTTON_CCS: Dict[int, str] = {
            44: "left_arrow",
            45: "right_arrow",
            46: "up_arrow",
            47: "down_arrow",
        }

        self._patches_applied = False

    def attach(self) -> None:
        if self._started:
            return

        n = self._install_mode_hooks()
        #self._io.send("debug", "ModeObserver start", "patched", n)

        self._started = True

    # -------------------------
    # Internal: hook forwarding
    # -------------------------

    def _emit(self, payload: Dict[str, Any]) -> None:
        try:
            self._module_manager.emit_mode_change(payload)
        except Exception as ex:
            try:
                self._io.send("error", "ModeObserver emit_mode_change failed", repr(ex))
            except Exception:
                pass

    def _normalize_mode_name(self, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, (bytes, bytearray)):
            try:
                v = v.decode(errors="ignore")
            except Exception:
                return None
        try:
            s = str(v)
        except Exception:
            return None
        s = s.strip()
        return s if s else None

    def _guess_mode_from_obj(self, obj: Any) -> Optional[str]:
        for attr in ("selected_mode", "_selected_mode", "mode", "name"):
            try:
                val = getattr(obj, attr, None)
            except Exception:
                val = None
            name = self._normalize_mode_name(val)
            if name:
                return name
        return None

    def _cls_name(self, obj: Any) -> str:
        try:
            return obj.__class__.__name__
        except Exception:
            return "<unknown>"

    # -------------------------
    # Context snapshot (still "data", not policy)
    # -------------------------

    def _safe_get(self, obj: Any, name: str) -> Any:
        try:
            v = getattr(obj, name, None)
        except Exception:
            return None
        if callable(v):
            try:
                return v()
            except Exception:
                return None
        return v

    def _gather_device_context(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}

        host = self._host
        if not host:
            return out

        try:
            locked = bool(self._safe_get(host, "is_locked_to_device"))
            out["locked"] = locked
        except Exception:
            pass

        try:
            dev = self._safe_get(host, "song_view_selected_device") or self._safe_get(host, "selected_device")
            if dev is None:
                dc = self._safe_get(host, "device_component") or self._safe_get(host, "device_view")
                dev = self._safe_get(dc, "device") if dc else None
            if dev is None:
                prov = self._safe_get(host, "device_provider")
                dev = self._safe_get(prov, "device") if prov else None

            if dev is not None:
                dn = getattr(dev, "name", None)
                if isinstance(dn, (bytes, bytearray)):
                    dn = dn.decode(errors="ignore")
                if dn:
                    out["appointed_device_name"] = str(dn)
        except Exception:
            pass

        try:
            prov = self._safe_get(host, "device_provider")
            params = None
            if prov is not None:
                for getter in ("visible_parameters", "parameters", "get_parameters"):
                    g = getattr(prov, getter, None)
                    try:
                        vals = g() if callable(g) else g
                    except Exception:
                        vals = None
                    if isinstance(vals, (list, tuple)):
                        params = list(vals)
                        break

            if isinstance(params, list):
                names = []
                for i in range(8):
                    nm = "<empty>"
                    try:
                        p = params[i]
                    except Exception:
                        p = None
                    if p is not None:
                        try:
                            val = getattr(p, "name", None)
                            if isinstance(val, (bytes, bytearray)):
                                val = val.decode(errors="ignore")
                            if isinstance(val, str) and val.strip():
                                nm = val.strip()
                        except Exception:
                            nm = "<empty>"
                    names.append(nm)
                out["visible_parameters"] = names
        except Exception:
            pass

        return out

    # -------------------------
    # Patching
    # -------------------------

    def _install_mode_hooks(self) -> int:
        if self._patches_applied:
            return 0

        patched = 0

        prefixes = {
            "ableton.v2",
        }

        target_methods = (
            "set_selected_mode",
            "_set_selected_mode",
            "_enter_mode",
            "enter_mode",
            "notify_selected_mode",
            "_notify_selected_mode",
            "on_selected_mode_changed",
            "_on_selected_mode_changed",
        )

        def wrap(orig):
            def wrapper(this, *a, **kw):
                res = orig(this, *a, **kw)
                try:
                    mode = self._normalize_mode_name(a[0]) if a else None
                    if not mode:
                        mode = self._guess_mode_from_obj(this)

                    component = self._cls_name(this)

                    payload: Dict[str, Any] = {
                        "kind": "hook",
                        "component": component,
                        "mode": mode,
                    }

                    if component == "ModesComponent" and mode == "device":
                        payload["device_context"] = self._gather_device_context()

                    self._emit(payload)
                except Exception:
                    pass
                return res

            setattr(wrapper, "__mode_observer_patched__", True)
            return wrapper

        for mname, mod in list(sys.modules.items()):
            if not isinstance(mod, types.ModuleType):
                continue
            if not any(mname.startswith(p) for p in prefixes):
                continue

            for attr in dir(mod):
                try:
                    cls = getattr(mod, attr)
                except Exception:
                    continue
                if not isinstance(cls, type):
                    continue

                for meth in target_methods:
                    try:
                        fn = getattr(cls, meth, None)
                    except Exception:
                        fn = None
                    if not callable(fn):
                        continue
                    if getattr(fn, "__mode_observer_patched__", False):
                        continue
                    try:
                        setattr(cls, meth, wrap(fn))
                        patched += 1
                    except Exception:
                        continue

        self._patches_applied = True
        return patched
