# Push2/__init__.py
# Purpose:
#   - Start IoManager early (UDP bootstrap).
#   - Expose Push2Original.* under Push2.* for legacy imports, but LAZY.
#   - Delegate get_capabilities() to Push2Original (no fallback).
#   - In create_instance(): create original Push2 script first, then start proxy,
#     but ALWAYS return the original host to Live.
#
# Extra diagnostics:
#   - Write unmistakable startup lines to Ableton Log.txt via standard logging.
#   - Do not depend on IoManager / UDP for these boot messages.

from __future__ import annotations

import atexit
import sys
import importlib
import importlib.abc
import importlib.util
import importlib.machinery
import logging

LOGGER = logging.getLogger("Push2Init")
if not LOGGER.handlers:
    LOGGER.setLevel(logging.INFO)

_BOOT_LOGGER = logging.getLogger("Push2Boot")
if not _BOOT_LOGGER.handlers:
    _BOOT_LOGGER.setLevel(logging.INFO)

_io = None
_shutdown_registered = False

# ---------------------------------------------------------------------------
# Import-debug logging (optional)
# WARNING: Monkeypatches global import behavior for the whole script runtime.
# Keep this OFF unless you are actively debugging imports.
# ---------------------------------------------------------------------------
_ENABLE_IMPORT_DEBUG = False

if _ENABLE_IMPORT_DEBUG:
    try:
        import importlib as _importlib_debug
        import builtins as _builtins_debug
        import logging as _logging_debug

        _LOGGER_IMPORT = _logging_debug.getLogger("Push2Init")
        try:
            _LOGGER_IMPORT.setLevel(_logging_debug.INFO)
        except Exception:
            pass

        _real_import_module = _importlib_debug.import_module

        def _import_module_logged(fullname, package=None):
            try:
                _LOGGER_IMPORT.info("import.debug: importlib.import_module(%r, package=%r)", fullname, package)
            except Exception:
                pass
            try:
                return _real_import_module(fullname, package)
            except Exception:
                try:
                    _LOGGER_IMPORT.error(
                        "import.debug: FAILED %r", fullname, exc_info=True
                    )
                except Exception:
                    pass
                raise

        _importlib_debug.import_module = _import_module_logged

        _real_dunder_import = _builtins_debug.__import__

        def _dunder_import_logged(name, globals=None, locals=None, fromlist=(), level=0):
            try:
                return _real_dunder_import(name, globals, locals, fromlist, level)
            except Exception:
                try:
                    _LOGGER_IMPORT.error(
                        "import.debug: __import__ FAILED name=%r fromlist=%r level=%r",
                        name, fromlist, level, exc_info=True
                    )
                except Exception:
                    pass
                raise

        _builtins_debug.__import__ = _dunder_import_logged
    except Exception:
        pass

# --- Constants ---------------------------------------------------------------

PUBLIC_PACKAGE = __name__
BASE_PACKAGE = __name__ + ".Push2Original"

# --- Hard Log.txt boot logging ----------------------------------------------

def _boot_log(msg: str, *args) -> None:
    try:
        if args:
            _BOOT_LOGGER.info(msg, *args)
        else:
            _BOOT_LOGGER.info(msg)
    except Exception:
        pass

def _boot_log_error(msg: str, *args) -> None:
    try:
        if args:
            _BOOT_LOGGER.error(msg, *args)
        else:
            _BOOT_LOGGER.error(msg)
    except Exception:
        pass

def _on_python_shutdown() -> None:
    _boot_log("Push2Proxy: Python shutdown for %s", PUBLIC_PACKAGE)

def _register_shutdown_hook() -> None:
    global _shutdown_registered

    if _shutdown_registered:
        return

    try:
        atexit.register(_on_python_shutdown)
        _shutdown_registered = True
        _boot_log("Push2Proxy: shutdown hook registered for %s", PUBLIC_PACKAGE)
    except Exception as e:
        _boot_log_error("Push2Proxy: shutdown hook registration failed: %s", e)

# This line should appear as soon as Live loads this package.
_boot_log("Push2Proxy: __init__.py loaded for %s", PUBLIC_PACKAGE)
_register_shutdown_hook()

# --- Logging ----------------------------------------------------------------

def _log_io(level: str, msg: str, *args) -> None:
    """
    Best-effort logger:
    - Prefer IoManager logger if available.
    - Fall back to standard LOGGER.
    """
    try:
        if _io is not None:
            _io.send(level, msg, *args)
            return
    except Exception:
        pass

    try:
        if args:
            msg = msg % args
    except Exception:
        pass

    if level == "error":
        LOGGER.error(msg)
    else:
        LOGGER.info(msg)

# --- Early I/O bootstrap ----------------------------------------------------

def _start_io() -> None:
    """
    Start IoManager early (may bootstrap UDP). Never raises.
    """
    try:
        from .IoManager import IoManager
        global _io
        _io = IoManager.instance()
        _boot_log("Push2Proxy: IoManager bootstrap OK")
    except Exception as e:
        LOGGER.error("io: IoManager bootstrap failed for Push2Proxy: %s", e)
        _boot_log_error("Push2Proxy: IoManager bootstrap failed: %s", e)

try:
    _start_io()
except Exception as e:
    LOGGER.error("io: bootstrap failed: %s", e)
    _boot_log_error("Push2Proxy: early bootstrap wrapper failed: %s", e)

# --- Lazy aliasing of Push2Original.* to Push2.* -----------------------------

_ALIAS_FINDER_INSTALLED = False

class _LazyAliasLoader(importlib.abc.Loader):
    def __init__(self, public_name: str, target_name: str):
        self.public_name = public_name
        self.target_name = target_name

    def create_module(self, spec):
        mod = importlib.import_module(self.target_name)
        sys.modules[self.public_name] = mod
        return mod

    def exec_module(self, module):
        sys.modules[self.public_name] = module


class _LazyAliasFinder(importlib.abc.MetaPathFinder):
    """
    Map:
        Push2.foo  -> Push2.Push2Original.foo
    but only if:
      - Push2.foo is not a real local module/package
      - Push2.Push2Original.foo actually exists
    """

    def find_spec(self, fullname, path=None, target=None):
        public_prefix = PUBLIC_PACKAGE + "."
        base_prefix = BASE_PACKAGE + "."

        if not fullname.startswith(public_prefix):
            return None

        if fullname == BASE_PACKAGE or fullname.startswith(base_prefix):
            return None

        remainder = fullname[len(public_prefix):]
        if not remainder:
            return None

        # If this is a real local module/package inside Push2, leave it alone.
        try:
            local_spec = importlib.machinery.PathFinder.find_spec(fullname, globals().get("__path__", None))
            if local_spec is not None:
                return None
        except Exception:
            pass

        target_name = BASE_PACKAGE + "." + remainder

        try:
            target_spec = importlib.util.find_spec(target_name)
        except Exception:
            target_spec = None

        if target_spec is None:
            return None

        is_package = target_spec.submodule_search_locations is not None

        return importlib.util.spec_from_loader(
            fullname,
            _LazyAliasLoader(fullname, target_name),
            is_package=is_package
        )


def _install_lazy_alias_finder() -> None:
    global _ALIAS_FINDER_INSTALLED

    if _ALIAS_FINDER_INSTALLED:
        return

    finder = _LazyAliasFinder()
    sys.meta_path.insert(0, finder)
    _ALIAS_FINDER_INSTALLED = True
    _log_io("info", "alias: lazy finder installed for %s -> %s.*", PUBLIC_PACKAGE, BASE_PACKAGE)
    _boot_log("Push2Proxy: lazy alias finder installed for %s", PUBLIC_PACKAGE)

try:
    _install_lazy_alias_finder()
except Exception as e:
    _log_io("error", "alias: lazy finder install failed: %s", e)
    _boot_log_error("Push2Proxy: lazy alias finder install failed: %s", e)

# --- Public API required by Live --------------------------------------------

def get_capabilities():
    """
    Delegate to Push2Original.get_capabilities(). No fallback.
    """
    _boot_log("Push2Proxy: get_capabilities called")

    mod = importlib.import_module(BASE_PACKAGE + ".__init__")
    fn = getattr(mod, "get_capabilities", None)
    if not callable(fn):
        _boot_log_error("Push2Proxy: original get_capabilities not callable")
        raise RuntimeError("original get_capabilities not callable")

    return fn()


def create_instance(c_instance):
    """
    Live entry point:
      - Create the original Push2 ControlSurface first.
      - Start proxy after that (observer/orchestrator).
      - Return the original host to Live (never return the proxy).
    """
    _boot_log("Push2Proxy: create_instance called")

    mod = importlib.import_module(BASE_PACKAGE + ".__init__")
    make = getattr(mod, "create_instance", None)
    if not callable(make):
        _boot_log_error("Push2Proxy: original create_instance not callable")
        raise RuntimeError("original create_instance not callable")

    try:
        host = make(c_instance)
        _boot_log("Push2Proxy: original Push2 host created OK")
    except Exception as e:
        _boot_log_error("Push2Proxy: original Push2 host creation FAILED: %s", e)
        raise

    try:
        from .Push2Proxy import Push2Proxy
        proxy = Push2Proxy(c_instance, host, _io)
        _log_io("info", "create_instance: proxy bootstrap ok")
        _boot_log("Push2Proxy: Push2Proxy bootstrap OK")
    except Exception as e:
        _log_io("error", "create_instance: proxy bootstrap failed: %s", e)
        _boot_log_error("Push2Proxy: Push2Proxy bootstrap FAILED: %s", e)
        proxy = None

    _boot_log("Push2Proxy: create_instance returning original host")
    return host