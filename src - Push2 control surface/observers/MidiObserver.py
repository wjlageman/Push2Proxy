# File: Push2/observers/MidiObserver.py
# Push2/observers/MidiObserver.py
# MIDI I/O layer + grab mechanism + UDP command handling.
#
# Policy:
# - No discovery, no fallbacks, no logging-to-file. Only _io.send once UDP is up.
# - Targets (original host + c_instance) are injected explicitly from Push2Proxy via attach().
# - Keep the standalone function layout (winning team). Class only wires references + installs hooks.
#
# Reporting requirements:
# 1) sysexin  : if msg[0] == 240 -> send('debug','sysexin', <all bytes...>)
# 2) sysexout : if msg[0] == 240 -> send('debug','sysexout', <all bytes...>)
# 3) midiin   : short msgs that reach surface -> exactly 3 bytes
# 4) midiin_grabbed : short msgs swallowed -> exactly 3 bytes
# 5) midiout  : short msgs that reach device -> exactly 3 bytes
# 6) midiout_grabbed : short msgs swallowed -> exactly 3 bytes
#
# Notes:
# - Grab logic applies only to channel-0 CC messages (0xB0).
# - Sysex is never grabbed (for now).

from __future__ import annotations
from typing import Iterable, Optional, Set, Tuple, Any, List
import traceback
from ..utils import fmt_exc, get_thread


# ---------------------------
# Explicitly injected refs
# ---------------------------

_io: Optional[Any] = None                 # IoManager instance (must be injected)
_c_instance: Optional[Any] = None         # Ableton control surface c_instance
_host_obj: Optional[Any] = None           # Original Push2 ControlSurface (host)


# ---------------------------
# Grab bookkeeping
# ---------------------------

_grab_in: Set[int] = set()
_grab_out: Set[int] = set()
_control_name_lookup = None

# ---------------------------
# Observer wiring only
# ---------------------------

class MidiObserver(object):
    def __init__(self, module_manager: Any, io: Any) -> None:
        self._module_manager = module_manager
        self._io = io

        global _io
        _io = io

    def attach(self, proxy: Any) -> None:
        global _host_obj, _c_instance, _control_name_lookup

        # Official access first (no backdoor). Fallback kept for older snapshots.
        host = None
        ci = None

        try:
            fn = getattr(proxy, "get_host", None)
            if callable(fn):
                host = fn()
        except Exception:
            host = None

        try:
            fn = getattr(proxy, "get_c_instance", None)
            if callable(fn):
                ci = fn()
        except Exception:
            ci = None

        if host is None:
            host = getattr(proxy, "_host_raw", None) or getattr(proxy, "_host", None)
        if ci is None:
            ci = getattr(proxy, "_c", None)

        from ..Data import select
        _control_name_lookup = select(('midi_controls', 'control_name_lookup'))

        _host_obj = host
        _c_instance = ci

        #_io.send('debug', "MidiObserver attach: host=", type(host).__name__ if host else None, "c_instance=", type(ci).__name__ if ci else None)

        _grab_in.clear()
        _grab_out.clear()
        _io.send('reset_midi_grab')

        self._install_midi_in_hooks()
        self._install_midi_out_hook()

    def _install_midi_in_hooks(self) -> None:
        """
        Hook MIDI IN at the *host* (real ControlSurface), not at proxy.
        Ableton calls host.receive_midi / host.receive_midi_chunk.
        """
        host = _host_obj
        if host is None:
            _io.send('error', "MidiObserver: cannot install MIDI IN hooks (host is None)")
            return

        if getattr(host, "_neo_midi_in_wrapped", False):
            _io.send('debug', "MidiObserver: MIDI IN hooks already installed")
            return

        orig_receive_midi = getattr(host, "receive_midi", None)
        orig_receive_midi_chunk = getattr(host, "receive_midi_chunk", None)

        if not callable(orig_receive_midi) and not callable(orig_receive_midi_chunk):
            _io.send('error', "MidiObserver: host has no receive_midi/receive_midi_chunk to hook")
            return

        #_io.send('debug', type(host).__name__, "receive_midi=", "<yes>" if callable(orig_receive_midi) else "<no>", "receive_midi_chunk=", "<yes>" if callable(orig_receive_midi_chunk) else "<no>")

        def _is_sysex(msg: Any) -> bool:
            try:
                return isinstance(msg, (list, tuple)) and len(msg) >= 1 and (int(msg[0]) & 0xFF) == 0xF0
            except Exception:
                return False

        def _is_cc_triplet(msg: Any) -> bool:
            try:
                return isinstance(msg, (list, tuple)) and len(msg) >= 3 and ((int(msg[0]) & 0xF0) == 0xB0)
            except Exception:
                return False

        def _triplet3(msg: Any) -> Tuple[int, int, int]:
            return (int(msg[0]) & 0xFF, int(msg[1]) & 0x7F, int(msg[2]) & 0x7F)

        def _handle_one_in(msg: Any) -> Tuple[Optional[bool], Any]:
            """
            Returns (swallowed, msg_to_pass).
            - Reports sysex as 'sysexin' and always passes.
            - Reports short triplets:
                * grabbed CC -> 'midiin_grabbed' and swallow
                * otherwise -> 'midiin' and pass

            Selfkick note:
            - This specific SysEx message is used as a "main-thread kicker".
            - It allows MaxForLive-side logic to react quickly on the main thread,
              instead of waiting on the slower UDP_recv thread.
            """
            try:
                if _is_sysex(msg):
                    #_io.send('debug', 'sysexin', 'THREAD', get_thread(), 'type', type(msg))
                    if msg == (240, 0, 33, 29, 1, 1, 10, 2, 247):
                        _io.send('sysex_and_selfkick_tick', msg)
                        return (False, msg)
                    _io.send('sysexin', msg)
                    return (False, msg)

                if isinstance(msg, (list, tuple)) and len(msg) >= 3:
                    st, d1, d2 = _triplet3(msg)

                    # Notify modules and receive replies
                    module_reply = self._module_manager.emit_midi_in((st, d1, d2))

                    if (st & 0xF0) == 0xB0:
                        cc = d1 & 0x7F
                        if cc in _grab_in:
                            _io.send('debug', 'midiin_grabbed', (st, d1, d2))
                            return (True, None)

                    if module_reply is True:
                        return (True, None)

                    #_io.send('debug', 'MIDIIN', 'THREAD', get_thread())
                    _io.send('midiin', (st, d1, d2))

                    if st == 176: # 0xB0
                        from ..Data import select
                        current_mode = select(('screen_mode', 'current_mode'))
                        #_io.send('debug', 'CHECK FOR MODE CHANGE', current_mode)

                        if current_mode == 'convert' and ((d1 == 35 and d2 == 127) or (d1 == 102 and d2 == 127)):
                            self._module_manager.emit_set_screen_mode('convert', 0)
                        elif current_mode == 'quantization' and d1 == 116 and d2 == 0:
                            self._module_manager.emit_set_screen_mode('quantization', 0)
                        elif current_mode == 'scales' and d1 == 58 and d2 == 127:
                            self._module_manager.emit_set_screen_mode('scales', 0)
                        elif current_mode == 'fixed_length' and ((d1 == 90 and d2 == 0) or (d1 == 102 and d2 == 127)):
                            self._module_manager.emit_set_screen_mode('fixed_length', 0)
                        elif current_mode == 'setup' and d1 == 30 and d2 == 127:
                            self._module_manager.emit_set_screen_mode('setup', 0)
                        elif d1 in (44, 45, 46, 47):
                            #_io.send('debug', 'ARROW_BUTTON')
                            from .RedringObserver import RedringObserver
                            RedringObserver.redraw_frame(True)

                    return (False, (st, d1, d2))

                return (False, msg)
            except Exception:
                _io.send('error', "MidiObserver: _handle_one_in FAILED", traceback.format_exc())
                return (False, msg)

        if callable(orig_receive_midi):
            def receive_midi_hook(msg: Any, *a, **kw):
                swallowed, out_msg = _handle_one_in(msg)
                if swallowed:
                    return None
                try:
                    return orig_receive_midi(out_msg, *a, **kw)
                except Exception:
                    _io.send('error', "MidiObserver: host.receive_midi FAILED", traceback.format_exc())
                    return None

            setattr(host, "receive_midi", receive_midi_hook)

        if callable(orig_receive_midi_chunk):
            def receive_midi_chunk_hook(chunk: Any, *a, **kw):
                try:
                    if isinstance(chunk, (list, tuple)):
                        filtered: List[Any] = []
                        for msg in chunk:
                            swallowed, out_msg = _handle_one_in(msg)
                            if swallowed:
                                continue
                            filtered.append(out_msg)
                        return orig_receive_midi_chunk(filtered, *a, **kw)
                except Exception:
                    _io.send('error', "MidiObserver: host.receive_midi_chunk FAILED", traceback.format_exc())
                try:
                    return orig_receive_midi_chunk(chunk, *a, **kw)
                except Exception:
                    return None

            setattr(host, "receive_midi_chunk", receive_midi_chunk_hook)

        try:
            setattr(host, "_neo_midi_in_wrapped", True)
        except Exception:
            pass


    def _install_midi_out_hook(self) -> None:
        """
        Hook MIDI OUT at c_instance.send_midi so grab_midiout can block hardware output.
        - Reports sysexout for full sysex payloads (starts with 0xF0).
        - Reports midiout/midiout_grabbed for 3-byte messages.
        """
        ci = _c_instance
        if ci is None:
            _io.send('error', "MidiObserver: cannot install MIDI OUT hook (c_instance is None)")
            return

        if getattr(ci, "_neo_midi_out_wrapped", False):
            _io.send('debug', "MidiObserver: MIDI OUT hook already installed")
            return

        orig = getattr(ci, "send_midi", None)
        if not callable(orig):
            _io.send('error', "MidiObserver: c_instance.send_midi missing/not callable on", type(ci).__name__)
            return

        def _is_sysex(msg: Any) -> bool:
            try:
                return isinstance(msg, (list, tuple)) and len(msg) >= 1 and (int(msg[0]) & 0xFF) == 0xF0
            except Exception:
                return False

        def _triplet3(msg: Any) -> Tuple[int, int, int]:
            return (int(msg[0]) & 0xFF, int(msg[1]) & 0x7F, int(msg[2]) & 0x7F)

        def send_midi_hook(msg: Any, *a, **kw):
            try:
                if _is_sysex(msg):
                    #_io.send('sysexout', msg)
                    return orig(msg, *a, **kw)

                if isinstance(msg, (list, tuple)) and len(msg) >= 3:
                    st, d1, d2 = _triplet3(msg)
                    note = 0

                    # Save tha led color or brightness in the cach using upsert in Data.py
                    if st == 144:
                        note = 128
                    from ..Data import upsert
                    upsert('leds', 'by_id', str(d1 + note), d2)
                    try:
                        name = _control_name_lookup.get(d1 + note)
                        if name:
                            upsert('leds', 'by_name', name, d2)
                            #_io.send('debug', 'leds', 'by_name', name, d2)
                        else:
                            if d1 + note not in (69, 80, 81, 82, 83, 84, 91, 92, 93, 94, 114, 115, 140): # Midi CC not on the Push2
                                _io.send('error', 'no led lookup for', str(d1 + note))
                    except Exception as ex:
                        _io.send('error', 'no led lookup for', str(d1 + note), ex)

                    injected = False
                    try:
                        if hasattr(_io, "is_midiout_injection"):
                            injected = bool(_io.is_midiout_injection())
                    except Exception:
                        injected = False

                    if not injected and (st & 0xF0) == 0xB0:
                        cc = d1 & 0x7F
                        if cc in _grab_out:
                            _io.send('midiout_grabbed', (st, d1, d2))
                            return None

                    _io.send('midiout', (st, d1, d2))
                    return orig((st, d1, d2), *a, **kw)

                return orig(msg, *a, **kw)

            except Exception:
                _io.send('error', "MidiObserver: c_instance.send_midi FAILED", traceback.format_exc())
                return None

        setattr(ci, "send_midi", send_midi_hook)
        try:
            setattr(ci, "_neo_midi_out_wrapped", True)
        except Exception:
            pass


# ---------------------------
# Small utils
# ---------------------------

def _to_int_or_none(x: Any):
    try:
        i = int(x)
        if i < -2147483648 or i > 2147483647:
            return None
        return i
    except Exception:
        return None


def _cc_list(args: Iterable[int]) -> Set[int]:
    out: Set[int] = set()
    for a in args:
        try:
            v = int(a) & 0x7F
            out.add(v)
        except Exception:
            pass
    return out


# ---------------------------
# MIDI encoding helpers
# ---------------------------

def _bytes_cc(cc: int, val: int) -> Tuple[int, int, int]:
    return (0xB0, int(cc) & 0x7F, int(val) & 0x7F)


# ---------------------------
# Injection helpers (unchanged semantics)
# ---------------------------

def _midiin_core(cc: int, val: int, ignore_grab: bool) -> None:
    cc_i = int(cc) & 0x7F
    val_i = int(val) & 0x7F
    triplet = _bytes_cc(cc_i, val_i)

    _io.send('debug', "[inject.in] start cc=", cc_i, "val=", val_i, "bytes=", triplet, "ignore_grab=", ignore_grab)

    if not ignore_grab and cc_i in _grab_in:
        _io.send('debug', "[inject.in] GRABBED (IN) cc=", cc_i, "val=", val_i, "bytes=", triplet)
        return

    host = _host_obj
    if host is None:
        _io.send('error', "[inject.in] NO HOST — cannot call receive_midi/receive_midi_chunk")
        return

    fn = getattr(host, "receive_midi", None)
    if callable(fn):
        fn(triplet)
        return

    fn2 = getattr(host, "receive_midi_chunk", None)
    if callable(fn2):
        fn2([triplet])
        return

    _io.send('error', "[inject.in] No viable receive method on host (receive_midi / receive_midi_chunk missing)")


def _midiout_core(cc: int, val: int, ignore_grab: bool) -> None:
    try:
        cc_i = int(cc) & 0x7F
        val_i = int(val) & 0x7F
        triplet = _bytes_cc(cc_i, val_i)

        _io.send('debug', "[inject.out] start cc=", cc_i, "val=", val_i, "bytes=", triplet, "ignore_grab=", ignore_grab)

        if not ignore_grab and cc_i in _grab_out:
            _io.send('debug', "[inject.out] GRABBED (OUT) cc=", cc_i, "val=", val_i, "bytes=", triplet)
            return

        ci = _c_instance
        if ci is None:
            _io.send('error', "[inject.out] NO c_instance — cannot call send_midi")
            return

        fn = getattr(ci, "send_midi", None)
        if not callable(fn):
            _io.send('error', "[inject.out] c_instance.send_midi missing/not callable on", type(ci).__name__)
            return

        fn(triplet)
    finally:
        _io.tick()

def midiin_cc(cc: int, val: int) -> None:
    _midiin_core(cc, val, ignore_grab=False)


def midiout_cc(cc: int, val: int) -> None:
    _midiout_core(cc, val, ignore_grab=False)


def inject_midiin_cc(cc: int, val: int) -> None:
    _midiin_core(cc, val, ignore_grab=True)


def inject_midiout_cc(cc: int, val: int) -> None:
    _midiout_core(cc, val, ignore_grab=True)


# ---------------------------
# Public API — GRAB (IN/OUT)
# ---------------------------

def grab_midiin(*ccs: int) -> Tuple:
    try:
        s = _cc_list(ccs)
        _grab_in.update(s)
        return (True, ("grab_midiin", ccs, 'grabbed', sorted(_grab_in) or '<empty>'))
    except Exception as ex:
        return (False, ('Error in grab_midiin', ex))


def release_midiin(*ccs: int) -> Tuple:
    try:
        s = _cc_list(ccs)
        for v in s:
            _grab_in.discard(v)
        return (True, ("release_midiin", ccs, 'grabbed', sorted(_grab_in) or '<empty>'))
    except Exception as ex:
        return (False, ('Error in release_midiin', ex))


def reset_midiin() -> Tuple:
    try:
        _grab_in.clear()
        return (True, ("reset_midiin", 'grabbed', sorted(_grab_in) or '<empty>'))
    except Exception as ex:
        return (False, ('Error in reset_midiin', ex))


def is_grabbed_midiin(cc: int) -> Tuple:
    try:
        v = int(cc) & 0x7F
        flag = v in _grab_in
        return (True, ('is_grabbed_midiin', v, flag))
    except Exception as ex:
        return (False, ('Error in is_grabbed_midiin', ex))


def get_grabbed_midiin() -> Tuple:
    try:
        out = tuple(sorted(_grab_in))
        return (True, ('get_grabbed_midiin', out or '<empty>'))
    except Exception as ex:
        return (False, ('Error in get_grabbed_midiin', ex))


def grab_midiout(*ccs: int) -> Tuple:
    try:
        s = _cc_list(ccs)
        _grab_out.update(s)
        return (True, ("grab_midiout", ccs, 'grabbed', sorted(_grab_out) or '<empty>'))
    except Exception as ex:
        return (False, ('Error in grab_midiout', ex))


def release_midiout(*ccs: int) -> Tuple:
    try:
        s = _cc_list(ccs)
        for v in s:
            _grab_out.discard(v)
        return (True, ("release_midiout", ccs, 'grabbed', sorted(_grab_out) or '<empty>'))
    except Exception as ex:
        return (False, ('Error in release_midiout', ex))


def reset_midiout() -> Tuple:
    try:
        _grab_out.clear()
        return (True, ("reset_midiout", 'grabbed', sorted(_grab_out)))
    except Exception as ex:
        return (False, ('Error in reset_midiout', ex))


def is_grabbed_midiout(cc: int) -> Tuple:
    try:
        v = int(cc) & 0x7F
        flag = v in _grab_out
        return (True, ('is_grabbed_midiout', v, flag))
    except Exception as ex:
        return (False, ('Error in is_grabbed_midiout', ex))


def get_grabbed_midiout() -> Tuple:
    try:
        out = tuple(sorted(_grab_out))
        return (True, ('get_grabbed_midiout', out or '<empty>'))
    except Exception as ex:
        return (False, ('Error in get_grabbed_midiout', ex))


# ---------------------------
# UDP command entry
# ---------------------------

def handle_midi_command(cmd: str, *args) -> bool:
    """
    Returns:
        True  -> MIDI command family (handled here, even on errors)
        False -> not a MIDI command
    """
    c = (cmd or "").strip().lower()

    if not (
        c.startswith("midi") or
        c.startswith("grab_") or
        c.startswith("release_") or
        c.startswith("reset_") or
        c.startswith("is_grabbed_") or
        c.startswith("get_grabbed_") or
        c == "button_click"
    ):
        return False

    try:
        #_io.send('debug', "HANDLE_MIDI_COMMAND cmd=", cmd, "args=", args)

        def _need_cc_val(name: str):
            if len(args) < 2:
                _io.send('error', name, ": need <cc> <val>, got", repr(args))
                return None, None
            cc = _to_int_or_none(args[0])
            val = _to_int_or_none(args[1])
            if cc is None or val is None:
                _io.send('error', name, ": invalid args", repr(args))
                return None, None
            return cc, val

        ok = True
        result = None

        if c == "midiin":
            cc, val = _need_cc_val("midiin")
            if cc is None:
                ok, result = False, ("midiin", "invalid args")
            else:
                inject_midiin_cc(cc, val)
                ok, result = True, ("midiin", (cc, val), "OK")

        elif c == "midiout":
            # Guard: avoid IndexError on empty args.
            if len(args) < 1:
                ok, result = False, ("midiout", "need <cc> <val> OR full sysex bytes")
            else:
                first = _to_int_or_none(args[0])

                # SysEx: first byte 240 (0xF0). Accept atoms/strings.
                if first == 240:
                    ci = _c_instance
                    if ci is None:
                        ok, result = False, ("midiout_sysex", "NO c_instance")
                    else:
                        fn = getattr(ci, "send_midi", None)
                        if not callable(fn):
                            ok, result = False, ("midiout_sysex", "send_midi missing/not callable", type(ci).__name__)
                        else:
                            sysex = tuple((int(a) & 0xFF) for a in args)
                            fn(sysex)
                            ok, result = True, ("midiout_sysex", len(sysex), "OK")
                else:
                    cc, val = _need_cc_val("midiout")
                    _io.send('debug', 'MIDIOUT', 'CMD', c, 'ARGS', args, 'CC', cc, 'VAL', val)
                    if cc is None:
                        ok, result = False, ("midiout", "invalid args")
                    else:
                        _io.begin_midiout_injection()
                        try:
                            inject_midiout_cc(cc, val)
                        finally:
                            _io.end_midiout_injection()
                        ok, result = True, ("midiout", (cc, val), "OK")

        elif c == "grab_midiin":
            if not args:
                ok, result = False, ("grab_midiin", "need <cc1> [cc2 ...]")
            else:
                ok, result = grab_midiin(*[int(a) for a in args])

        elif c == "grab_midiout":
            ok, result = grab_midiout(*[int(a) for a in args])

        elif c == "release_midiin":
            ok, result = release_midiin(*[int(a) for a in args])

        elif c == "release_midiout":
            ok, result = release_midiout(*[int(a) for a in args])

        elif c == "reset_midiin":
            ok, result = reset_midiin()

        elif c == "reset_midiout":
            ok, result = reset_midiout()

        elif c == "is_grabbed_midiin":
            if not args:
                ok, result = False, ("is_grabbed_midiin", "need <cc>")
            else:
                cc = _to_int_or_none(args[0])
                if cc is None:
                    ok, result = False, ("is_grabbed_midiin", "invalid cc", repr(args[0]))
                else:
                    ok, result = is_grabbed_midiin(cc)

        elif c == "is_grabbed_midiout":
            if not args:
                ok, result = False, ("is_grabbed_midiout", "need <cc>")
            else:
                cc = _to_int_or_none(args[0])
                if cc is None:
                    ok, result = False, ("is_grabbed_midiout", "invalid cc", repr(args[0]))
                else:
                    ok, result = is_grabbed_midiout(cc)

        elif c == "get_grabbed_midiin":
            ok, result = get_grabbed_midiin()

        elif c == "get_grabbed_midiout":
            ok, result = get_grabbed_midiout()

        else:
            ok, result = False, ("unknown MIDI command", repr(cmd), "args=", repr(args))

        if ok:
            #_io.send('debug', cmd, args, 'result', result)
            pass
        else:
            _io.send('error', cmd, args, 'result', result)

    except Exception as ex:
        try:
            import sys
            tb = sys.exc_info()[2]
            while tb and tb.tb_next:
                tb = tb.tb_next
            lineno = tb.tb_lineno if tb else None
        except Exception:
            lineno = None

        _io.send('error', "handle_midi_command FAILED", "cmd=", cmd, "args=", repr(args), "error=", type(ex).__name__, str(ex), "line=", lineno)

    return True
