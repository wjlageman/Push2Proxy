# ModuleManager.py
#
# Responsibilities
# - Discover modules in:
#       <base_dir>/builtins
#       <base_dir>/modules
# - Import each module as:
#       Push2.<origin>.<file_stem>
# - Create a fresh ModuleAPI per module and call init_module(api) once per live_set.
# - Inject outbound service callables into the API before init_module(api).
# - Maintain one registry: module_id -> ModuleAPI.
# - Dispatch events using opt-in callbacks:
#       only callbacks explicitly assigned by the module are invoked (default is None).
#
# Override rule
# - modules/ overrides builtins/ when module_id matches.
#
# Fault handling
# - If a module callback raises, the module is detached (removed from registry).

import os
import sys
import traceback
import importlib
from typing import Any, Dict, Optional, Tuple, List
from .utils import fmt_exc, call_stack

from .ModuleAPI import ModuleAPI


class ModuleManager(object):
    def __init__(self, env: Any, base_dir: str) -> None:
        self._env = env
        self._base_dir = base_dir

        self._io = getattr(env, "_io", None)
        if self._io is None:
            raise RuntimeError("ModuleManager: env has no _io")

        self._dirs: List[Tuple[str, str]] = [
            ("builtins", os.path.join(base_dir, "builtins")),
            ("modules", os.path.join(base_dir, "modules")),
        ]

        # module_id -> ModuleAPI
        self._apis: Dict[str, ModuleAPI] = {}

        # module_id -> (origin, module_name, file_path)
        self._meta: Dict[str, Tuple[str, str, str]] = {}

        #self._io.send("debug", "ModuleManager: __init__", "base_dir", base_dir)

    # -------------------------
    # Public lifecycle
    # -------------------------

    def discover_modules(self) -> None:
        """
        Called by Push2Proxy once per live_set lifetime.
        Discover + init all modules (builtins first, modules override by id).
        """
        self._io.send("debug", "ModuleManager: begin discovery")

        self._discover_origin("builtins")
        self._discover_origin("modules")

        self._io.send("debug", "ModuleManager: discovery done", "count", len(self._apis))

    def detach(self, module_id: str) -> bool:
        """
        Remove a module from the registry so it stops receiving callbacks.
        Note: we do not promise GC cleanup (modules may keep global references).
        """
        api = self._apis.get(module_id)
        if api is None:
            return False

        #self._io.send("debug", "ModuleManager: detach", module_id)

        # Optional on_detach (not part of the public ModuleAPI contract)
        on_detach = getattr(api, "on_detach", None)
        if callable(on_detach):
            try:
                api.debug("on_detach", "call")
                on_detach(api, "ModuleManager.detach", None)
                api.debug("on_detach", "ok")
            except Exception:
                api.error("on_detach failed:\n" + traceback.format_exc())

        try:
            del self._apis[module_id]
        except Exception:
            pass

        try:
            del self._meta[module_id]
        except Exception:
            pass

        return True

    def _get_callstack(self) -> str:
        """
        Return a formatted callstack string.
        One line per frame, indexed, newest first.

        Example line:
            [1] <C:\\path\\to\\file.py:123 in func>
        """
        lines = []
        i = 2  # skip internal frames (API / dispatcher / observer)
        try:
            while True:
                f = sys._getframe(i)
                lines.append(f"[{i - 3}] <{f.f_code.co_filename}:{f.f_lineno} in {f.f_code.co_name}>")
                i += 1
        except ValueError:
            pass

        return "\n".join(lines)

    # -------------------------
    # Dispatch (manager -> module callbacks)
    #
    # Opt-in model:
    # - Only callbacks explicitly assigned by the module are invoked.
    # - Signature in this manager is: callback(api, payload)
    # -------------------------

    def emit_track_change(self, payload: Any) -> None:
        self._dispatch("on_track_change", payload)

    def emit_device_change(self, payload: Any) -> None:
        self._dispatch("on_device_change", payload)

    def emit_clip_change(self, payload: Any) -> None:
        self._dispatch("on_clip_change", payload)

    def emit_midi_in(self, payload: Any) -> Optional[bool]:
        return self._dispatch_with_reply("on_midi_in", payload)

    def emit_udp_in(self, payload: Any) -> None:
        return self._dispatch("on_udp_in", payload)

    def emit_surface_update(self, payload: Any) -> None:
        self._dispatch("on_surface_update", payload)

    def emit_mode_change(self, payload: Any) -> None:
        self._dispatch("on_mode_change", payload)

    # IMPORTANT:
    # - Modules call api.set_screen_mode(key, state)
    # - Manager converts that into an event for whoever implements on_set_screen_mode
    # - api.set_screen_mode MUST remain callable (SurfaceUpdateModule expects it).
    def emit_set_screen_mode(self, key: Any, state: Any = None) -> None:
        #self._io.send('debug', 'IN EMIT_SET_SCREEN_MODE', 'KEY', key, 'STATE', state, call_stack())
        payload = {"key": key, "state": state}
        self._dispatch("on_set_screen_mode", payload)

    # -------------------------
    # Internals
    # -------------------------

    def _dispatch(self, callback_name: str, payload: Any) -> None:
        # Stable iteration order is helpful for debugging.
        for module_id in sorted(self._apis.keys()):
            api = self._apis.get(module_id)
            if api is None:
                continue

            callback = getattr(api, callback_name, None)
            if not callable(callback):
                continue

            try:
                callback(api, payload)
            except Exception:
                api.error("%s failed:\n%s" % (callback_name, traceback.format_exc()))
                self.detach(module_id)

    def _dispatch_with_reply(self, callback_name: str, payload: Any) -> Optional[bool]:
        # Stable iteration order is helpful for debugging.
        reply = None
        for module_id in sorted(self._apis.keys()):
            api = self._apis.get(module_id)
            if api is None:
                continue

            callback = getattr(api, callback_name, None)
            if not callable(callback):
                continue

            try:
                ans = callback(api, payload)
                if isinstance(ans, bool):
                    reply = ans
            except Exception:
                api.error("%s failed:\n%s" % (callback_name, traceback.format_exc()))
                self.detach(module_id)
        return reply

    def _discover_origin(self, origin: str) -> None:
        path = None
        for o, p in self._dirs:
            if o == origin:
                path = p
                break

        if not path or not os.path.isdir(path):
            self._io.send("error", "ModuleManager: discover", origin, "dir missing", path)
            return

        #self._io.send("debug", "ModuleManager: discover", origin, "dir", path)

        files: List[str] = []
        try:
            for fn in os.listdir(path):
                if not fn.endswith(".py"):
                    continue
                if fn.startswith("_"):
                    continue
                # Keep manager/api files out of discovery
                if fn in ("ModuleAPI.py", "ModuleManager.py"):
                    #self._io.send("debug", "ModuleManager: skip", fn)
                    continue
                files.append(fn)
        except Exception:
            self._io.send("error", "ModuleManager: listdir failed:\n" + traceback.format_exc())
            return

        files.sort()

        for fn in files:
            file_path = os.path.join(path, fn)
            stem = fn[:-3]
            module_name = "Push2.%s.%s" % (origin, stem)

            module_id = None
            try:
                module_id = self._load_and_init(origin, module_name, file_path)
            except Exception:
                self._io.send(
                    "error",
                    "ModuleManager: load/init failed",
                    origin,
                    fn,
                    "\n" + traceback.format_exc()
                )
                continue

            #if module_id:
            #    self._io.send("debug", "ModuleManager: discovered", origin, "id", module_id, "from", fn)

    def _resolve_service(self, name: str):
        """
        Resolve a service callable for modules.

        Priority:
        1) env.<name>
        2) env._cache.<name>          (if present)
        3) Push2.Data.<name>          (module-level functions)
        """
        # 1) env.<name>
        try:
            fn = getattr(self._env, name, None)
            if callable(fn):
                return fn
        except Exception:
            pass

        # 2) env._cache.<name>
        try:
            cache = getattr(self._env, "_cache", None)
            if cache is not None:
                fn = getattr(cache, name, None)
                if callable(fn):
                    return fn
        except Exception:
            pass

        # 3) Push2.Data.<name>
        try:
            from . import Data as Data
            fn = getattr(Data, name, None)
            if callable(fn):
                return fn
        except Exception:
            pass

        return None

    def _load_and_init(self, origin: str, module_name: str, file_path: str) -> Optional[str]:
        #self._io.send("debug", "ModuleManager: load", origin, "module", module_name)

        try:
            if module_name in sys.modules:
                mod = importlib.reload(sys.modules[module_name])
            else:
                mod = importlib.import_module(module_name)
        except Exception:
            self._io.send("error", "ModuleManager: import failed", module_name, "\n" + traceback.format_exc())
            return None

        # Determine module id
        module_id = getattr(mod, "MODULE_ID", None) or getattr(mod, "module_id", None)
        if not module_id:
            module_id = os.path.splitext(os.path.basename(file_path))[0]
        module_id = str(module_id)

        # Override behavior: modules override builtins by id
        if module_id in self._apis:
            self._io.send("debug", "ModuleManager: override", module_id, "by", origin)
            self.detach(module_id)

        api = ModuleAPI()

        # Default id (module should keep it; may overwrite during init_module(api))
        api.id = module_id

        # --- Inject services (expected to be callable in your runtime) ---
        api.send = self._io.send
        api.upsert = self._resolve_service("upsert")
        api.emit_path = self._resolve_service("emit_path")
        api.select = self._resolve_service("select")
        api.get_callstack = self._get_callstack

        # CRITICAL: must remain callable. Modules call set_screen_mode; manager emits event.
        api.set_screen_mode = self.emit_set_screen_mode

        from . import Data
        api.mangle_key = Data.mangle_key

        # Convenience wrappers (emit_path is expected to exist in this runtime)
        def _emit_data(*p):
            return api.emit_path("data", *p)

        def _emit_json(*p):
            return api.emit_path("json", *p)

        api.emit_data = _emit_data
        api.emit_json = _emit_json

        init_fn = getattr(mod, "init_module", None)
        if not callable(init_fn):
            api.error("missing required init_module(api) in %s" % module_name)
            return None

        try:
            init_fn(api)
        except Exception:
            api.error("init_module failed:\n" + traceback.format_exc())
            return None

        # Strong requirement: module must set api.id (should match module_id)
        if not api.id:
            api.error("init_module did not set api.id (required)")
            return None

        # If module changed api.id, respect it (and override by that id)
        final_id = str(api.id)
        if final_id != module_id:
            if final_id in self._apis:
                self._io.send("debug", "ModuleManager: override (after id change)", final_id, "by", origin)
                self.detach(final_id)
            module_id = final_id

        self._apis[module_id] = api
        self._meta[module_id] = (origin, module_name, file_path)

        return module_id
