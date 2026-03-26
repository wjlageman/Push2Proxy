# Push2/IoManager.py
# Central I/O manager for UDP used by Push2Proxy.
#
# Responsibilities:
#   - Own the UDP singleton (UDP.py holds host/port config) and set on_receive callback.
#   - Provide emitters: send(), send_line(), send_json(), send_dbg(), send_proxy().
#   - Dispatch inbound UDP on the main thread via a scheduled metronome:
#       UDP recv thread -> _on_udp_in (enqueue)
#       main thread     -> metronome tick -> tick() -> _on_udp_dispatch()
#
# Notes:
#   - MIDI hooks are installed by MidiObserver.attach().
#   - IoManager does not call c_instance.send_midi directly.
#   - UDP inbox is lockless: relies on CPython deque atomic append/popleft.

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Any, Dict, Optional, Tuple

from .Data import handle_keys, emit_path
from .observers.SongObserver import handle_liveset
from .UDP import ensure_started, UDP
from .observers import MidiObserver as MIDI
from .utils import caller_atom, fmt_exc


LOGGER = logging.getLogger("IoManager")
if not LOGGER.handlers:
    LOGGER.setLevel(logging.INFO)


def _proxy(obj: Any) -> Any:
    for attr in ("proxy", "_proxy", "p"):
        try:
            v = getattr(obj, attr, None)
            if v is not None:
                return v
        except Exception:
            continue
    return obj


def _host_from_router(router: Any) -> Any:
    pr = _proxy(router)
    for name in ("_host_raw", "_host"):
        try:
            v = getattr(pr, name, None)
            if v is None and pr is not router:
                v = getattr(router, name, None)
            if v is not None:
                return v
        except Exception:
            continue
    return None


class IoManager(object):
    _INSTANCE: Optional["IoManager"] = None
    _INJECT_CALLER = True  # Compatibility: prepend caller atom to outgoing UDP

    # Debug/test-only: keep a "selfkick" hook on UDP receive thread.
    _ENABLE_SELFKICK = True

    _UDP_TARGET_BROADCAST = "broadcast"
    _UDP_TARGET_ONDEMAND = "ondemand"

    @classmethod
    def instance(cls) -> "IoManager":
        if cls._INSTANCE is None:
            cls._INSTANCE = cls()
            cls._INSTANCE._ensure_udp_started()
        return cls._INSTANCE

    def __init__(self) -> None:
        self._udp: Optional[UDP] = None
        self.proxy = None  # type: ignore
        self._host = None  # cached ControlSurface for schedule_message
        self._json_dumps = json.dumps

        # Hot-path cached callables (filled at UDP start)
        self._udp_send = None  # type: ignore
        self._udp_send_broadcast = None  # type: ignore
        self._udp_send_ondemand = None  # type: ignore
        self._udp_target = self._UDP_TARGET_BROADCAST

        # Injection context for MIDI OUT (UDP midiout should bypass grabs)
        self._midiout_inject_depth = 0

        # Inbound queue (UDP recv thread -> main thread)
        self._udp_inbox = deque()  # type: ignore[var-annotated]

        # Metronome state
        self._metronome_running = False
        self._metronome_tick_scheduled = False

        # Delays (avoid 0ms runaway loops)
        self._metronome_idle_delay_ms = 2
        self._metronome_busy_delay_ms = 1

        # Debug throttling
        self._metronome_tick_counter = 0
        self._metronome_debug_every = 100
        self._last_tick = time.time()

    # ---------------------- public emitters -------------------------

    def _is_atomic(self, x: Any) -> bool:
        return isinstance(x, (str, bytes, bytearray, int, float, bool)) or x is None

    def _atom_coerce(self, x: Any) -> Any:
        if x is None:
            return "null"
        if isinstance(x, (str, bytes, bytearray, int, float, bool)):
            return x
        if isinstance(x, (dict, set)):
            try:
                return self._json_dumps(x, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                return str(x)
        return str(x)

    def _flatten_atoms(self, *args: Any) -> Tuple[Any, ...]:
        if not args:
            return tuple()

        if len(args) == 1 and isinstance(args[0], (tuple, list)):
            cont = args[0]
            all_atomic = True
            needs_coerce = False
            for it in cont:
                if isinstance(it, (list, tuple)):
                    all_atomic = False
                    break
                if not self._is_atomic(it):
                    needs_coerce = True
            if all_atomic:
                if needs_coerce:
                    return tuple(self._atom_coerce(it) for it in cont)
                return tuple(cont)

        out: list = []
        stack: list = [iter(args)]
        append = out.append
        is_atomic = self._is_atomic
        atom_coerce = self._atom_coerce

        while stack:
            it = stack[-1]
            try:
                v = next(it)
            except StopIteration:
                stack.pop()
                continue

            if isinstance(v, (list, tuple)):
                stack.append(iter(v))
                continue

            append(v if is_atomic(v) else atom_coerce(v))

        if not out:
            return tuple()

        if not isinstance(out[0], str):
            out[0] = str(out[0])  # OSC address must be string
        return tuple(out)

    def _set_udp_target(self, target: str) -> None:
        if target == self._UDP_TARGET_ONDEMAND:
            self._udp_target = self._UDP_TARGET_ONDEMAND
        else:
            self._udp_target = self._UDP_TARGET_BROADCAST

    def _get_udp_sender(self):
        if self._udp_target == self._UDP_TARGET_ONDEMAND:
            return self._udp_send_ondemand or self._udp_send
        return self._udp_send_broadcast or self._udp_send

    def send(self, *atoms: Any) -> None:
        """
        Send OSC-like atoms over UDP. Flattens nested lists/tuples.
        Optionally injects a caller atom as prefix (compat).
        Default target is Broadcast. During _on_udp_dispatch() it is temporarily OnDemand.
        """
        try:
            udp_send = self._get_udp_sender()
            if udp_send is None:
                raise RuntimeError("UDP not started")

            flat = self._flatten_atoms(*atoms)
            if not flat:
                udp_send(("error", "IoManager: flatten failed (empty)"))
                return

            if self._INJECT_CALLER:
                caller = caller_atom() or "<caller>"
                flat = (caller,) + flat

            udp_send(flat)

        except Exception as e:
            msg = fmt_exc("UDP send error", e)
            try:
                LOGGER.error(msg)
            except Exception:
                pass
            try:
                if self.proxy and getattr(self.proxy, "_c", None):
                    self.proxy._c.log_message(msg)
            except Exception:
                pass

    def send_line(self, addr: str, text: str) -> None:
        try:
            self.send(addr, "line", text)
        except Exception as e:
            try:
                LOGGER.error(fmt_exc("send_line failed", e))
            except Exception:
                pass

    def send_dbg(self, text: str) -> None:
        try:
            self.send("debug", text)
        except Exception as e:
            try:
                LOGGER.error(fmt_exc("send_dbg failed", e))
            except Exception:
                pass

    def send_proxy(self, text: str) -> None:
        try:
            self.send("/proxy", "line", text)
        except Exception as e:
            try:
                LOGGER.error(fmt_exc("send_proxy failed", e))
            except Exception:
                pass

    """
    def send_json(self, addr: str, obj: Dict[str, Any]) -> None:
        ""
        Encode obj as JSON and send it. (Currently routed via 'debug'.)
        ""
        try:
            s = self._json_dumps(obj, ensure_ascii=False, separators=(",", ":"))
            self.send("debug", addr, "json", s)
        except Exception as e:
            try:
                LOGGER.error(fmt_exc("json encode/send failed", e))
            except Exception:
                pass
    """

    # ---------------------- MIDI OUT injection context -------------------------

    def begin_midiout_injection(self) -> None:
        try:
            self._midiout_inject_depth += 1
        except Exception:
            self._midiout_inject_depth = 1

    def end_midiout_injection(self) -> None:
        try:
            self._midiout_inject_depth -= 1
            if self._midiout_inject_depth < 0:
                self._midiout_inject_depth = 0
        except Exception:
            self._midiout_inject_depth = 0

    def is_midiout_injection(self) -> bool:
        try:
            return getattr(self, "_midiout_inject_depth", 0) > 0
        except Exception:
            return False

    # ---------------------- lifecycle / bootstrap -------------------------

    def set_proxy(self, proxy_obj) -> None:
        self.proxy = proxy_obj

        # Cache host for main-thread scheduling via host.schedule_message().
        self._host = _host_from_router(getattr(self, "proxy", None))
        if self._host is None:
            self.send("error", "IoManager set_proxy host_cached", "None")

        self._start_metronome()

    def _ensure_udp_started(self) -> None:
        """
        Start/reuse UDP singleton and install inbound callback.
        Transport config lives ONLY in UDP.py.
        """
        try:
            if self._udp is None:
                self._udp = ensure_started(on_receive=self._on_udp_in)
                self._udp_send = self._udp.send
                self._udp_send_broadcast = self._udp.send_broadcast
                self._udp_send_ondemand = self._udp.send_ondemand
                self._udp_target = self._UDP_TARGET_BROADCAST
        except Exception as e:
            try:
                LOGGER.error(fmt_exc("UDP bootstrap failed", e))
            except Exception:
                pass

    # ---------------------- metronome (main thread pump) ----------------------

    def _start_metronome(self) -> None:
        host = self._host or _host_from_router(getattr(self, "proxy", None))
        if host is None:
            self.send("error", "IoManager: _start_metronome: host not found")
            self._metronome_running = False
            return

        if self._metronome_running:
            return

        self._metronome_running = True
        self._metronome_tick_scheduled = False
        self._schedule_metronome_tick(self._metronome_idle_delay_ms)

    def _schedule_metronome_tick(self, delay_ms: int) -> None:
        if not self._metronome_running:
            return

        if self._metronome_tick_scheduled:
            return

        host = self._host or _host_from_router(getattr(self, "proxy", None))
        if host is None:
            self.send("error", "IoManager: _schedule_metronome_tick: host missing")
            self._metronome_running = False
            return

        schedule_message = getattr(host, "schedule_message", None)
        if not callable(schedule_message):
            self.send("error", "IoManager: _schedule_metronome_tick: host.schedule_message missing/not callable")
            self._metronome_running = False
            return

        try:
            ms = int(delay_ms)
            if ms <= 0:
                ms = 1
            self._metronome_tick_scheduled = True
            schedule_message(ms, self._metronome_tick)
        except Exception as ex:
            self._metronome_tick_scheduled = False
            self._metronome_running = False
            self.send("error", fmt_exc("IoManager: schedule_message failed", ex))

    def _metronome_tick(self) -> None:
        self._metronome_tick_scheduled = False

        if not self._metronome_running:
            return

        self._metronome_tick_counter += 1
        if self._metronome_debug_every and (self._metronome_tick_counter % int(self._metronome_debug_every) == 0):
            try:
                self._last_tick = time.time()
            except Exception:
                pass

        self.tick()

        try:
            if len(self._udp_inbox) > 0:
                self._schedule_metronome_tick(self._metronome_busy_delay_ms)
                return
        except Exception as ex:
            self.send("error", fmt_exc("IoManager: inbox len failed (post-tick)", ex))
            self._schedule_metronome_tick(self._metronome_busy_delay_ms)
            return

        self._schedule_metronome_tick(self._metronome_idle_delay_ms)

    # ------------------------- tick (main thread pump) -------------------------

    def tick(self) -> None:
        try:
            inbox_depth = len(self._udp_inbox)
        except Exception as ex:
            self.send("error", fmt_exc("IoManager: inbox len failed", ex))
            inbox_depth = 0

        if inbox_depth > 0:
            max_per_tick = 256
            n = 0

            while n < max_per_tick:
                try:
                    atoms = self._udp_inbox.popleft()
                except IndexError:
                    break
                except Exception as ex:
                    self.send("error", fmt_exc("IoManager: inbox pop failed", ex))
                    break

                n += 1
                try:
                    self._on_udp_dispatch(atoms)
                except Exception as ex:
                    self.send("error", fmt_exc("IoManager: _on_udp_dispatch failed", ex))

        # Always attempt redraw; guard failures so tick() can't crash.
        try:
            from .observers.RedringObserver import RedringObserver
            RedringObserver.redraw_frame(False)
        except Exception:
            pass

    # ------------------------- inbound (UDP recv thread) -------------------------

    def _on_udp_in(self, atoms) -> None:
        """
        UDP recv thread: enqueue atoms and wake the metronome.
        """
        try:
            self._udp_inbox.append(tuple(atoms) if isinstance(atoms, list) else atoms)
        except Exception as ex:
            self.send("error", fmt_exc("IoManager: enqueue failed", ex))
            return

        # Debug/test: runs on UDP recv thread (not main thread).
        if self._ENABLE_SELFKICK:
            try:
                MIDI.handle_midi_command("midiout", 240, 0, 33, 29, 1, 1, 10, 2, 247)
            except Exception:
                pass

        if not self._metronome_running:
            self._start_metronome()

        self._schedule_metronome_tick(self._metronome_busy_delay_ms)

    # ------------------------- main-thread dispatcher -------------------------

    def _on_udp_dispatch(self, atoms) -> None:
        """
        Main-thread dispatcher for inbound UDP.
        """
        self._set_udp_target(self._UDP_TARGET_ONDEMAND)
        try:
            if isinstance(atoms, (tuple, list)) and atoms:
                first = atoms[0]
                if isinstance(first, str):
                    cmd = first.strip()
                    args = atoms[1:]

                    if hasattr(MIDI, "handle_midi_command"):
                        if MIDI.handle_midi_command(cmd, *args):
                            return

                    if cmd == "keys":
                        handle_keys(args)
                        return

                    if cmd == "json" or cmd == "data":
                        emit_path(cmd, args)
                        return

                    if cmd == "liveset":
                        handle_liveset(cmd, args)
                        return

                    if cmd == "set_redring":
                        if len(args) >= 2:
                            self.send("debug", "IoManager", "move redring", args[0], args[1])
                            from .observers.RedringObserver import RedringObserver
                            RedringObserver.move_redring(args[0], args[1])
                        else:
                            self.send("error", "IoManager set_redring missing args", repr(args))
                        return

                    if cmd == "get_redring":
                        self.send("debug", "IoManager", "get redring")
                        from .observers.RedringObserver import RedringObserver
                        RedringObserver.redraw_frame(True)
                        return

                    if cmd.lower().startswith("get_"):
                        base_pkg = __name__.rsplit(".", 1)[0]
                        P = __import__(base_pkg + ".GetDataCommands", fromlist=["*"])
                        handle_get = getattr(P, "handle_get", None)
                        if callable(handle_get):
                            handle_get(self.proxy, cmd, *args)
                        else:
                            self.send("/proxy", "line", "GetDataCommands.handle_get missing")
                        return

            # Fallback
            if self.proxy is not None and hasattr(MIDI, "on_udp"):
                MIDI.on_udp(self.proxy, atoms)  # type: ignore[misc]
            else:
                self.send("debug", "udp:", repr(atoms), "(MidiObserver.on_udp missing)")
        finally:
            self._set_udp_target(self._UDP_TARGET_BROADCAST)
