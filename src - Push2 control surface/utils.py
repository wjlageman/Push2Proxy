# utils.py
#
# Common lightweight helpers used across the Push2 proxy/kernel.
#
# Notes for external devs
# - These helpers must be safe in Ableton Live’s embedded Python runtime.
# - Most functions are defensive: failures return a placeholder instead of raising.
# - fmt_exc() is intentionally heuristic: it prefers “project-ish” frames over stdlib.

from __future__ import annotations
import os, sys, traceback, re, threading
from typing import Any, List, Tuple, Dict
from typing import Optional


# ---------- helpers (small formatters) ----------

def typename_for_seq(obj: Any) -> str:
    if isinstance(obj, tuple): return "tuple"
    if isinstance(obj, list):  return "list"
    if isinstance(obj, set):   return "set"
    return type(obj).__name__


def get_thread() -> str:
    """
    Return a short thread marker for logging.
    """
    cur_id = threading.get_ident()
    try:
        cur_name = threading.current_thread().name
    except Exception:
        cur_name = "<?>"
    return f"CURRENT_THREAD: {cur_name} {cur_id}"


def fmt_seq_preview(seq: List[Any], kind: str, max_inline: int = 128, head: int = 16, tail: int = 4) -> str:
    n = len(seq)
    core = seq[:head] + ["…"] + seq[-tail:] if (n > max_inline or n > (head + tail)) else seq
    rep_items = [fmt_val(x) if x != "…" else "…" for x in core]
    o, c = ("[", "]") if kind in ("list", "set") else ("(", ")")
    return f"<{kind} n={n}> {o}{', '.join(rep_items)}{c}"


def fmt_val(v: Any) -> str:
    try:
        if isinstance(v, (int, float, bool, type(None))): return repr(v)
        if isinstance(v, str): return repr(v)
        if isinstance(v, (tuple, list, set)):
            seq = list(v) if not isinstance(v, set) else list(sorted(v, key=lambda x: repr(x)))
            return fmt_seq_preview(seq, typename_for_seq(v))
        tname = type(v).__name__
        if hasattr(v, "name"):
            try: return f"<{tname} name={repr(getattr(v,'name'))}>"
            except Exception: return f"<{tname}>"
        if hasattr(v, "class_name"):
            try: return f"<{tname} class={repr(getattr(v,'class_name'))}>"
            except Exception: return f"<{tname}>"
        return f"<{tname}>"
    except Exception:
        return "<val>"


def fmt_args(a: Tuple[Any, ...], k: Dict[str, Any]) -> str:
    parts: List[str] = []
    try: parts += [fmt_val(x) for x in a]
    except Exception: parts += ["<args>"]
    try: parts += [f"{key}={fmt_val(val)}" for key, val in k.items()]
    except Exception: parts += ["<kwargs>"]
    return ", ".join(parts)


def fmt_exc(prefix: str, exc: Exception) -> str:
    """
    Format an exception with a useful (but lightweight) location hint.

    Behavior:
    - If sys.exc_info() has no traceback, print only type + message.
    - Otherwise select a "best" frame by skipping obvious stdlib / site-packages paths.
    - Append a short tail call-chain for orientation.
    """
    import os
    import sys
    import traceback

    etype, evalue, etb = sys.exc_info()
    if etb is None:
        return "%s: %s: %s" % (prefix, type(exc).__name__, str(exc))

    tb = traceback.extract_tb(etb)
    if not tb:
        return "%s: %s: %s @ <no-traceback>" % (prefix, type(exc).__name__, str(exc))

    # Prefer a frame that looks like project code (not stdlib / not site-packages).
    # Heuristic: contains "Push2" or ends with "Data.py", OR is inside current working dir.
    cwd = os.getcwd().replace("\\", "/")
    best = None

    for fr in reversed(tb):
        fn = (fr.filename or "").replace("\\", "/")
        if "python-bundle/Python/lib" in fn:
            continue
        if "site-packages" in fn:
            continue
        if "/re/__init__.py" in fn:
            continue

        if "Push2" in fn or fn.endswith("Data.py") or fn.startswith(cwd):
            best = fr
            break

        if best is None:
            best = fr

    if best is None:
        best = tb[-1]

    where = "%s:%d in %s" % (best.filename, best.lineno, best.name)

    # Include a short call chain (last ~6 frames).
    chain = []
    for fr in tb[-6:]:
        chain.append("%s:%d:%s" % (os.path.basename(fr.filename), fr.lineno, fr.name))
    chain_s = " <- ".join(chain)

    return "%s: %s: %s @ %s | %s" % (prefix, type(exc).__name__, str(exc), where, chain_s)


def caller_atom(skip: int = 1) -> Optional[str]:
    """
    Fast caller string '<file:line>' using sys._getframe().

    skip:
      Number of extra frames to skip above this function (in addition to this frame).
    """
    try:
        f = sys._getframe(1 + skip)
    except Exception:
        return None
    try:
        return f"<{os.path.basename(f.f_code.co_filename)}:{f.f_lineno}>"
    except Exception:
        return None


def call_stack(depth: int = 8, skip: int = 0) -> Optional[str]:
    """
    Return a single string with the caller hierarchy, e.g.:
        '<A.py:10> <- <B.py:42> <- <C.py:7>'
    """
    try:
        frames = []
        i = 1 + skip  # 0 would be call_stack itself
        while len(frames) < depth:
            try:
                f = sys._getframe(i)
            except Exception:
                break
            try:
                fn = os.path.basename(f.f_code.co_filename)
                frames.append(f"<{fn}:{f.f_lineno}>")
            except Exception:
                frames.append("<unknown>")
            i += 1
        if not frames:
            return None
        return " <- ".join(frames)
    except Exception:
        return None


def get_callstack_lines(start: int = 2, max_frames: int = 32) -> str:
    """
    Return a formatted callstack string (one line per frame, newest first).
    """
    lines = []
    i = start
    try:
        while len(lines) < max_frames:
            try:
                f = sys._getframe(i)
            except Exception:
                break
            try:
                lines.append(f"[{i - start}] <{f.f_code.co_filename}:{f.f_lineno} in {f.f_code.co_name}>")
            except Exception:
                lines.append(f"[{i - start}] <unknown>")
            i += 1
    except Exception:
        pass
    return "\n".join(lines)
