# Push2/UDP.py
# Minimal OSC-over-UDP for Max <-> Live.
#
# Contract:
#   - Decode OSC -> call on_receive(atoms) where atoms[0] is the OSC address (unchanged).
#   - Encode OSC from atoms where atoms[0] is the OSC address (unchanged).
#   - Supported typetags: i (int32), f (float32), s (utf8 string), b (blob).
#
# Environment notes:
#   - Tested with Max 9.1.0
#   - Max has its own UDP abstractions and threading model; this module
#     intentionally aligns with Max UDP usage to ensure
#     predictable collaboration with Max.
#
# Notes:
#   - No auto-prefixing of '/'.
#   - Errors are intentionally swallowed to avoid destabilizing Live.


from __future__ import annotations
import socket
import struct
import threading
from typing import Callable, Optional, Sequence, Tuple

# Transport defaults (ONLY HERE)
_DEFAULT_LISTEN_HOST = "127.0.0.1"
_DEFAULT_LISTEN_PORT = 3137
_DEFAULT_SEND_HOST = "255.255.255.255"
_DEFAULT_BROADCAST_PORT = 3138
_DEFAULT_ONDEMAND_PORT = 3139

# Module-level singleton
_UDP_SINGLETON: Optional["UDP"] = None
_UDP_LOCK = threading.Lock()


def ensure_started(
    on_receive: Optional[Callable[[tuple], None]] = None,
    listen_host: str = _DEFAULT_LISTEN_HOST,
    listen_port: Optional[int] = _DEFAULT_LISTEN_PORT,
    send_host: str = _DEFAULT_SEND_HOST,
    broadcast_port: int = _DEFAULT_BROADCAST_PORT,
    ondemand_port: int = _DEFAULT_ONDEMAND_PORT,
) -> "UDP":
    """
    Start or reuse the global UDP singleton. Safe to call multiple times.
    If on_receive is provided, it overwrites the previous callback.
    If listen_port is None, no receiver thread is started.
    """
    global _UDP_SINGLETON
    with _UDP_LOCK:
        if _UDP_SINGLETON is None:
            inst = UDP(
                on_receive=on_receive,
                listen_host=listen_host,
                listen_port=listen_port,
                send_host=send_host,
                broadcast_port=broadcast_port,
                ondemand_port=ondemand_port,
            )
            inst.start()
            _UDP_SINGLETON = inst
        else:
            if on_receive is not None:
                _UDP_SINGLETON.on_receive = on_receive
    return _UDP_SINGLETON



def get_instance() -> Optional["UDP"]:
    # Returns the singleton if started; otherwise None.
    return _UDP_SINGLETON


class UDP:
    def __init__(
        self,
        on_receive: Optional[Callable[[tuple], None]] = None,
        listen_host: str = _DEFAULT_LISTEN_HOST,
        listen_port: Optional[int] = _DEFAULT_LISTEN_PORT,
        send_host: str = _DEFAULT_SEND_HOST,
        broadcast_port: int = _DEFAULT_BROADCAST_PORT,
        ondemand_port: int = _DEFAULT_ONDEMAND_PORT,
    ):
        self.on_receive = on_receive
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.send_host = send_host
        self.broadcast_port = int(broadcast_port)
        self.ondemand_port = int(ondemand_port)

        self._rsock: Optional[socket.socket] = None
        self._ssock: Optional[socket.socket] = None
        self._rthr: Optional[threading.Thread] = None
        self._running = False

        self._boot_sent = False

    def start(self):
        # Sender socket (lazy)
        if self._ssock is None:
            try:
                self._ssock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._ssock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except Exception:
                self._ssock = None

        # Receiver socket + thread
        if self.listen_port is not None and self._rsock is None:
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((self.listen_host, int(self.listen_port)))
                s.settimeout(0.5)
                self._rsock = s
                self._running = True
                self._rthr = threading.Thread(target=self._recv_loop, daemon=True)
                self._rthr.start()

                # Single boot message (ONLY HERE)
                if not self._boot_sent:
                    self._boot_sent = True
                    self.send_broadcast((
                        "<sender>", "log", "Push2", "UDP",
                        "listening", f"{self.listen_host}:{int(self.listen_port)}",
                        "sending", self.send_host,
                        "broadcast", self.broadcast_port,
                        "ondemand", self.ondemand_port,
                    ))

            except Exception:
                try:
                    if s:
                        s.close()
                except Exception:
                    pass
                self._rsock = None
                self._rthr = None
                self._running = False

    def send_atoms(self, atoms: Sequence, host: str, port: int):
        """atoms[0] is the OSC address (coerced to str) and is used unchanged."""
        try:
            if not atoms:
                return

            if self._ssock is None:
                try:
                    self._ssock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    self._ssock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                except Exception:
                    self._ssock = None

            addr_atom = atoms[0]
            addr_str = str(addr_atom)  # no auto-prefix '/'
            args = tuple(atoms[1:])
            pkt = self._encode_osc(addr_str, args)

            if self._ssock is not None:
                self._ssock.sendto(pkt, (str(host), int(port)))
        except Exception:
            pass

    def send_broadcast(self, atoms: Sequence):
        try:
            self.send_atoms(tuple(atoms), self.send_host, self.broadcast_port)
        except Exception:
            pass

    def send_ondemand(self, atoms: Sequence):
        try:
            self.send_atoms(tuple(atoms), self.send_host, self.ondemand_port)
        except Exception:
            pass

    def send(self, atoms: Sequence):
        """Compatibility: default send goes to Broadcast."""
        try:
            self.send_broadcast(atoms)
        except Exception:
            pass

    def _recv_loop(self):
        sock = self._rsock
        while self._running and sock:
            try:
                data, _ = sock.recvfrom(65536)
                atoms = self._decode_osc(data)
                if atoms:
                    cb = self.on_receive
                    if cb is not None:
                        try:
                            cb(atoms)
                        except Exception:
                            pass
            except socket.timeout:
                continue
            except Exception:
                continue

    # ---------- OSC encode/decode (i/f/s/b only) ----------

    @staticmethod
    def _pad4(b: bytes) -> bytes:
        return b + (b"\x00" * ((4 - (len(b) % 4)) % 4))

    @staticmethod
    def _pack_str(s: str) -> bytes:
        return UDP._pad4(s.encode("utf-8") + b"\x00")

    @staticmethod
    def _pack_i(i: int) -> bytes:
        return struct.pack(">i", int(i))

    @staticmethod
    def _pack_f(f: float) -> bytes:
        return struct.pack(">f", float(f))

    @staticmethod
    def _pack_b(bts: bytes) -> bytes:
        size = struct.pack(">i", len(bts))
        return size + UDP._pad4(bts)

    @staticmethod
    def _tag_of(a) -> str:
        if isinstance(a, str):
            return "s"
        if isinstance(a, bool):
            return "i"
        if isinstance(a, int):
            return "i"
        if isinstance(a, float):
            return "f"
        if isinstance(a, (bytes, bytearray)):
            return "b"
        return "s"

    def _encode_osc(self, address: str, args: Sequence) -> bytes:
        addr_b = self._pack_str(address)
        tags = "," + "".join(self._tag_of(a) for a in args)
        tags_b = self._pack_str(tags)
        arg_b = b"".join(
            self._pack_str(a) if isinstance(a, str) else
            self._pack_i(a) if isinstance(a, int) else
            self._pack_f(a) if isinstance(a, float) else
            self._pack_b(bytes(a)) if isinstance(a, (bytes, bytearray)) else
            self._pack_str(str(a))
            for a in args
        )
        return addr_b + tags_b + arg_b

    @staticmethod
    def _read_padded_str(buf: bytes, off: int):
        end = buf.find(b"\x00", off)
        if end < 0:
            end = len(buf)
        raw = buf[off:end]
        s = raw.decode("utf-8", errors="replace")
        off = off + ((len(raw) + 1 + 3) // 4) * 4
        return s, off

    def _decode_osc(self, packet: bytes) -> tuple:
        """Return atoms=(address, *args). Address is preserved exactly."""
        try:
            if not packet:
                return ()
            off = 0
            address, off = self._read_padded_str(packet, off)
            typetags, off = self._read_padded_str(packet, off)
            if not typetags.startswith(","):
                return (address,)
            args = []
            for t in typetags[1:]:
                if t == "i":
                    val = struct.unpack(">i", packet[off:off + 4])[0]
                    off += 4
                    args.append(int(val))
                elif t == "f":
                    val = struct.unpack(">f", packet[off:off + 4])[0]
                    off += 4
                    args.append(float(val))
                elif t == "s":
                    s, off = self._read_padded_str(packet, off)
                    args.append(s)
                elif t == "b":
                    sz = struct.unpack(">i", packet[off:off + 4])[0]
                    off += 4
                    data = packet[off: off + sz]
                    off += ((sz + 3) // 4) * 4
                    args.append(data)
                else:
                    # Unsupported OSC types are ignored (i/f/s/b only).
                    off += 4
            return (address,) + tuple(args)
        except Exception:
            return ()
