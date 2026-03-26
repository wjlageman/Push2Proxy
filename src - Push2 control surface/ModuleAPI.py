# ModuleAPI.py
# Public contract object passed to modules.
#
# DESIGN GOALS
# - Minimal kernel surface area
# - No "escape hatch" references (no env/host objects in the API)
# - A module may only interact with the system through explicitly provided callables
# - A module registers callbacks by assigning callables to api.on_* during init_module(api)
#
# IMPORTANT
# - The ModuleManager creates a fresh ModuleAPI for each module.
# - The ModuleManager injects service callables before calling init_module(api).
# - The module MUST set api.id and api.module during init_module(api).
# - Callback delivery is opt-in: events are only sent to callbacks
#   explicitly assigned by the module; default is None.


from typing import Any, Callable, Optional


SendFn = Callable[..., None]   # fire-and-forget message sender
UpsertFn = Callable[..., bool] # cache write,
MangleKeyFn = Callable[[Any], str]
SetScreenModeFn = Callable[[str, Any], None]


class ModuleAPI(object):
    """
    Module API contract (v0.1).

    This object serves two roles:

    1) Module -> Host services (capabilities):
       The manager injects these callables before init_module(api) is called.
       A module must only use these services to interact with the system.

    2) Host -> Module callbacks:
       The module subscribes to events by assigning callables to api.on_* fields
       during init_module(api).

    Identity:
    - api.id is a unique string identifying the module (e.g. "builtin.track.device.module").
    - api.origin is informational: "builtins" or "modules".
    - api.module is the ONLY strong reference to the module instance managed by the host.
      The manager can drop a module by removing its API from the manager registry.
    """

    def __init__(self) -> None:
        # ------------------------------------------------------------
        # Module-provided fields (must be set during init_module(api))
        # ------------------------------------------------------------

        # Required unique id, examples:
        #   "builtin.track.device.module"
        #   "xanadu.mixer.enhancement"
        #
        # Convention:
        # - Use a personal or project-specific prefix as the first segment
        # - This avoids collisions without requiring central registration
        self.id: Optional[str] = None

        # Informational origin string: "builtins" or "modules"
        self.origin: Optional[str] = None

        # Host-managed module instance reference (informational)
        self.module: Any = None

        # ------------------------------------------------------------
        # Module callbacks (Host -> Module)
        #
        # Recommended callback signature:
        #   def on_xxx(api: ModuleAPI, source: str, payload: Any) -> None
        #
        # Where:
        # - api: the module API (services + identity)
        # - source: a diagnostic route string (no objects), examples:
        #     "SongObserver.selected_track"
        #     "SongObserver.appointed_device"
        # - payload: data only (dict/list/tuple/scalars), no host objects
        # ------------------------------------------------------------

        self.on_track_change: Optional[Callable[["ModuleAPI", str, Any], None]] = None
        self.on_device_change: Optional[Callable[["ModuleAPI", str, Any], None]] = None
        self.on_surface_update: Optional[Callable[["ModuleAPI", str, Any], None]] = None
        self.on_mode_change: Optional[Callable[["ModuleAPI", str, Any], None]] = None
        # Not in use yet
        self.on_clip_change: Optional[Callable[["ModuleAPI", str, Any], None]] = None
        self.on_midi_in: Optional[Callable[["ModuleAPI", str, Any], None]] = None
        self.on_udp_in: Optional[Callable[["ModuleAPI", str, Any], None]] = None
        self.on_set_screen_mode: Optional[Callable[["ModuleAPI", str, Any], None]] = None

        # ------------------------------------------------------------
        # Manager-injected services (Module -> Host)
        #
        # These are the only capabilities a module receives.
        # They are injected by the ModuleManager before init_module(api).
        #
        # All services are optional at runtime (None if not wired), but
        # core modules may treat specific ones as hard requirements.
        # ------------------------------------------------------------

        # Minimal outbound messaging function (UDP/log bridge).
        # Usage examples:
        #   api.send("debug", "hello", 123)
        #   api.send("error", "oops")
        #
        # This replaces exposing a full io object.
        self.send: Optional[SendFn] = None

        # Key mangling helper (Push2 view keys -> stable cache keys).
        self.mangle_key: Optional[MangleKeyFn] = None

        # Set_screen_mode helper used by legacy surface update processing.
        self.set_screen_mode: Optional[SetScreenModeFn] = None

        # Cache write helper.
        #
        # Contract:
        #   upsert(*path, prop_or_index, value) -> bool
        #
        # Returns:
        #   True if the value changed and should be emitted
        self.upsert: Optional[UpsertFn] = None

        # Emit a message to Max via UDP (or equivalent).
        #
        # Contract:
        #   emit_path(tag: str, *atoms) -> None
        #
        # Where tag is typically one of:
        #   "data", "json", "line", "log", ...
        self.emit_path: Optional[Callable[..., None]] = None

        # Convenience wrappers wired by the ModuleManager (if emit_path exists)
        self.emit_data: Optional[Callable[..., None]] = None
        self.emit_json: Optional[Callable[..., None]] = None

        # Cache reads (optional)
        #self.get_cached_data: Optional[Callable[[], Any]] = None
        self.select: Optional[Callable[[Any], Any]] = None

        # Debug helpers
        self.get_callstack: Optional[Callable[[], str]] = None

    # ------------------------------------------------------------
    # Convenience logging helpers
    # ------------------------------------------------------------

    def debug(self, *atoms: Any) -> None:
        """
        Convenience debug logger.
        Equivalent to:
            api.send("debug", "[<id>]", *atoms)
        """
        try:
            if self.send:
                self.send("debug", "[%s]" % (self.id or "<no-id>"), *atoms)
        except Exception:
            pass

    def error(self, *atoms: Any) -> None:
        """
        Convenience error logger.
        Equivalent to:
            api.send("error", "[<id>]", *atoms)
        """
        try:
            if self.send:
                self.send("error", "[%s]" % (self.id or "<no-id>"), *atoms)
        except Exception:
            pass
