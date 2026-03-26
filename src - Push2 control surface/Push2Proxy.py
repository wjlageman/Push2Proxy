# File: Push2Proxy.py
# Push2Proxy.py
import os
import traceback
from typing import Any
from .utils import fmt_exc

_ACTIVE_PROXY = None
_io = None


def active_proxy():
    # Returns the last successfully initialized proxy instance (debug convenience).
    return _ACTIVE_PROXY


class Push2Proxy(object):
    """
    Orchestrator / kernel:
    - holds host + io references
    - resets Data cache for the new live_set
    - starts ModuleManager (builtins + modules)
    - installs observers and routes events into ModuleManager dispatchers

    Lifecycle model:
    - One proxy instance per Live Set load/create.
    - Observers/modules are started once per live_set.
    - Any fatal init failure raises.
    """

    def __init__(self, c_instance, host, io):
        global _ACTIVE_PROXY
        global _io

        # c_instance is used by MidiObserver (and possibly others).
        self._c = c_instance

        # Host is the original Push2 ControlSurface instance.
        self._host = host

        self._module_manager = None
        self._song_observer = None
        self._redring = None

        # IoManager is injected by __init__.py; do not instantiate it here.
        self._io = io
        _io = io

        # Let IoManager know which proxy instance is active.
        self._io.set_proxy(self)

        _io.send("log", "Live is creating or opening a new live_set")

        # ---- HARD REQUIRE: cache reset ----
        try:
            from . import Data
            Data.reset(self._io)
        except Exception:
            self._fatal("Data.reset failed")

        # ---- HARD REQUIRE: ModuleManager ----
        try:
            base_dir = os.path.dirname(__file__)
            from .ModuleManager import ModuleManager
            self._module_manager = ModuleManager(self, base_dir)
            # Execute discover_modules later
        except Exception:
            self._fatal("ModuleManager init failed")

        # Ask host for a fresh MIDI map (non-fatal, but recommended).
        try:
            self._host.request_rebuild_midi_map()
        except Exception:
            self._fatal("request_rebuild_midi_map failed")

        # ---- HARD REQUIRE: MidiObserver ----
        try:
            from .observers.MidiObserver import MidiObserver
            self._midi_observer = MidiObserver(self._module_manager, self._io)
            self._midi_observer.attach(self)
        except Exception:
            self._fatal("MidiObserver init/attach failed")

        # ---- HARD REQUIRE: SurfaceUpdateObserver ----
        try:
            from .observers.SurfaceUpdateObserver import SurfaceUpdateObserver
            self._surface_update_observer = SurfaceUpdateObserver(self._module_manager, self._io)
            self._surface_update_observer.install()
        except Exception:
            self._fatal("SurfaceUpdateObserver init/install failed")

        # ---- HARD REQUIRE: SongObserver ----
        # SongObserver currently expects a song.view reference.
        try:
            from .observers.SongObserver import SongObserver
            self._song_observer = SongObserver(self, self._module_manager, self._io)

            song = getattr(self._host, "song", None) or getattr(self._host, "_song", None)
            song_view = getattr(song, "view", None) if song else None

            self._song_observer.attach(song, song_view)
        except Exception:
            self._fatal("SongObserver init/attach failed")

        # ---- HARD REQUIRE: ClipObserver ----
        try:
            from .observers.ClipObserver import ClipObserver
            self._clip_observer = ClipObserver(self._host, self._module_manager, self._io)
            self._clip_observer.attach()
        except Exception:
            self._fatal("ClipObserver init/attach failed")
            
        # ---- HARD REQUIRE: RedringObserver ----
        self._redring = None
        try:
            from .observers.RedringObserver import RedringObserver
            RedringObserver.start(self._host, self._module_manager, self._io)
            RedringObserver.redraw_frame(True)
        except Exception:
            self._fatal("RedringObserver init failed")

        # ---- HARD REQUIRE: ModeObserver ----
        try:
            from .observers.ModeObserver import ModeObserver
            self._mode_observer = ModeObserver(self._host, self._module_manager, self._io)
            self._mode_observer.attach()
        except Exception:
            self._fatal("ModeObserver init/attach failed")

        # ---- HARD REQUIRE: StaticDataObserver ----
        try:
            from .observers.StaticDataObserver import StaticDataObserver
            self._static_data_observer = StaticDataObserver(self._host, self._module_manager, self._io)
            self._static_data_observer.attach()
        except Exception:
            self._fatal("StaticDataObserver init/attach failed")

        # ---- HARD REQUIRE: SongTimeObserver ----
        try:
            from .observers.SongTimeObserver import SongTimeObserver

            # SongTimeObserver.__init__(proxy, io)
            self._song_time_observer = SongTimeObserver(self, self._io)

            song = getattr(self._host, "song", None) or getattr(self._host, "_song", None)
            self._song_time_observer.attach(song)
        except Exception:
            self._fatal("SongTimeObserver init/attach failed")

        # Now it's the time to discover modules
        try:
            self._module_manager.discover_modules()
        except Exception:
            self._fatal("ModuleManager discover_modules failed")

        _ACTIVE_PROXY = self
        _io.send('update', 'global_state')
        if Data.upsert('global_state', 'push2proxy_active'):
            Data.emit_json('global_state')

    def _fatal(self, msg: str) -> None:
        # Always raise after reporting the stack trace.
        try:
            _io.send("error", "FATAL:", msg + ":\n" + traceback.format_exc())
        except Exception:
            pass
        raise RuntimeError("Push2Proxy: " + msg)

    # The rest of the are probably hanging leftovers. They should be removed before releasing this code.
    def _song(self):
        # Convenience accessor for observers/modules.
        try:
            _io.send('error', '_song in Push2Proxy is called')
            return self._host.song
        except Exception:
            try:
                return self._host._song
            except Exception:
                return None
