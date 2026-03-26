# SurfaceUpdateObserver.py
#
# Kernel observer that bridges Python logging into the module system.
#
# Responsibilities:
# - Install one logging.Handler on the root logger.
# - Sanitize each LogRecord into a small, stable payload.
# - Forward the payload to ModuleManager as a single callback: on_surface_update.
#
# Non-responsibilities:
# - No parsing of Push2/Live model semantics.
# - No cache writes.
# - No UDP/Max output.
#
# Role of logging in the kernel:
#
# - Logging is used here as a passive tap into Live/Push2 internal messages.
#   Many Push2 script state changes and diagnostics are emitted via Python logging.
#   By attaching a handler to the root logger we can observe those messages without
#   modifying upstream code.
#
# - This observer is strictly one-way:
#       Live/Push2 -> logging -> SurfaceUpdateObserver -> ModuleManager
#   It never writes back into logging to influence Live.
#
# - Python logging is used as a *unified event bus* for all internal state
#   changes, warnings, and diagnostics originating from the Push2 script,
#   Live internals, and our own code.
#
# - This observer intentionally installs a handler on the *root logger* and
#   sets the root level to DEBUG, so that *all* log records are captured:
#       DEBUG, INFO, WARNING, ERROR, CRITICAL.
#
# - SurfaceUpdateObserver performs NO semantic filtering.
#   Every LogRecord that is emitted by logging is forwarded as-is (after
#   sanitization) to the ModuleManager via emit_surface_update().
#
# - The observer is content-agnostic:
#   it does not interpret messages, does not decide what is relevant,
#   and does not write to caches or send UDP itself.
#
# - Filtering, parsing, caching, and export are the responsibility of
#   higher-level modules. This keeps the kernel transparent and makes
#   all internal behavior observable from the outside (Max).
#
# Design intent:
#   "If it happened inside the Push2 script, it must be observable."
#
# Any reduction of data volume must happen *after* this observer,
# never here.


import logging, ast, json
from typing import Any, Dict, Optional


class SurfaceUpdateObserver(object):
    """
    Observes the Python logging stream and forwards log records to ModuleManager.

    Notes:
    - This observer MUST stay content-agnostic.
    - It only sanitizes LogRecord into a stable dict payload.
    - Modules decide what matters (filtering, parsing, caching, exporting).
    """

    def __init__(self, module_manager: Any, io: Any) -> None:
        self._module_manager = module_manager
        self._io = io

        self._installed = False
        self._handler = None  # type: Optional[_SurfaceUpdateForwardingHandler]

    def install(self) -> None:
        if self._installed:
            return

        root = logging.getLogger()

        # Avoid double-install: if our forwarding handler already exists, reuse it.
        try:
            for h in list(getattr(root, "handlers", []) or []):
                if isinstance(h, _SurfaceUpdateForwardingHandler):
                    self._handler = h
                    self._installed = True
                    try:
                        self._io.send("debug", "SurfaceUpdateObserver", "ALREADY_INSTALLED")
                    except Exception:
                        pass
                    return
        except Exception:
            pass

        self._handler = _SurfaceUpdateForwardingHandler(self._module_manager, self._io)

        try:
            self._handler.setFormatter(logging.Formatter("%(name)s: %(levelname)s: %(message)s"))
        except Exception:
            pass

        root.addHandler(self._handler)

        try:
            # IMPORTANT: Push2 bank switches often update labels via DEBUG logs.
            # Ensure we capture them by setting root to DEBUG.
            root.setLevel(logging.DEBUG)
        except Exception:
            pass

        try:
            # Route warnings through logging so we can observe them as well.
            logging.captureWarnings(True)
        except Exception:
            pass

        self._installed = True

# -------------------------
# Object coercion (text-only)
# -------------------------
    
class _SurfaceUpdateForwardingHandler(logging.Handler):
    """
    Internal logging handler that forwards LogRecord -> ModuleManager.

    Safety:
    - Re-entrancy guard prevents infinite recursion if io.send or module dispatch logs again.
    """

    def __init__(self, module_manager: Any, io: Any) -> None:
        super(_SurfaceUpdateForwardingHandler, self).__init__()
        self._module_manager = module_manager
        self._io = io
        self._in_emit = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._in_emit:
            return

        self._in_emit = True
        try:
            payload = self._sanitize_record(record)

            # Debug mirror (explicit, cheap).
            # Keep it short to reduce log spam; modules can do deeper logging if needed.
            """
            try:
                self._io.send(
                    "debug",
                    "surface_update",
                    '\nMESSAGE ' + str(payload.get("message")),
                    '\nOBJECT ' + str(payload.get("object")),
                    '\nLOGGER ' + str(payload.get("logger")) + ' LEVEL ' + str(payload.get("level")) + ' LEVELNO ' + str(payload.get("levelno")),
                    '\nPATH ' + str(payload.get("pathname")) + ': ' + str(payload.get("lineno")) + ' in ' + str(payload.get("func")),
                    #'\nCREATED ' + str(payload.get("created")),
                    #'\nTHREAD ' + str(payload.get("thread")),
                    #'\nPROCESS ' + str(payload.get("process")),
                    '\nEXC_INFO ' + str(payload.get("exc_info")),
                )
            except Exception:
                pass
            """

            # Forward to modules (single callback type).
            # Preparation: ModuleManager must provide emit_surface_update(payload).
            try:
                emit_function = getattr(self._module_manager, "emit_surface_update", None)
                if callable(emit_function):
                    emit_function(payload)
            except Exception:
                # Never let logging crash the host.
                pass
        finally:
            self._in_emit = False

    def _coerce_to_obj(self, record: logging.LogRecord, msg_text: str):
        """
        Try to obtain a Python object (dict/list/tuple) from a log record.
        Order:
        1) record.msg is already a structure?
        2) record.args contains a structure?  (logger.debug(".. %s", obj))
        3) msg_text contains a repr/json-like block after e.g. "Model sent:"
        4) msg_text itself is a repr/json of dict/list
        On failure -> None
        """
        # 1) record.msg is already a structure?
        if isinstance(record.msg, (dict, list, tuple)):
            return record.msg

        # 2) args -> common pattern: logger.debug("Model sent: %s", obj)
        if record.args:
            if len(record.args) == 1 and isinstance(record.args[0], (dict, list, tuple)):
                return record.args[0]
            for a in record.args:
                if isinstance(a, (dict, list, tuple)):
                    return a

        t = msg_text.strip()

        # 3) Heuristic: "Model sent: { ... }" -> take everything after colon
        if "Model sent:" in t:
            tail = t.split("Model sent:", 1)[1].strip()
            if (tail.startswith("'") and tail.endswith("'")) or (tail.startswith('"') and tail.endswith('"')):
                tail = tail[1:-1]
            try:
                return ast.literal_eval(tail)
            except Exception:
                pass
            try:
                return json.loads(tail)
            except Exception:
                pass

        # 4) If the whole text looks like dict/list, try eval/json
        if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
            try:
                return ast.literal_eval(t)
            except Exception:
                pass
            try:
                return json.loads(t)
            except Exception:
                pass

        return None
    
    def _format_exc_text(self, exc_info: Any) -> Optional[str]:
        if not exc_info:
            return None
        try:
            import traceback as _tb
            etype, evalue, etb = exc_info
            parts = _tb.format_exception(etype, evalue, etb)
            return "".join(parts).strip() if parts else None
        except Exception:
            return None

    def _sanitize_record(self, record: logging.LogRecord) -> Dict[str, Any]:
        message = "<unprintable>"
        obj = None

        try:
            msg = str(record.getMessage())
            message = str(msg) if msg is not None else "<empty>"
            obj = self._coerce_to_obj(record, message)
            #self._io.send('debug', 'SURFACE UPDATE OBSERVER OBJ', 'OBJECT', obj, 'RECORD', record, 'MEESAGE', message)
        except Exception as ex:
            self._io.send('error', 'SURFACE UPDATE OBSERVER OBJ', ex)
            pass

        return {
            # Keep a stable explicit source marker (no callstack work here).
            #"source": "SurfaceUpdateObserver",

            # Message data (both formatted and raw when possible).
            #"message": msg_formatted,
            "message": message,
            "object": obj,

            # Primary routing/filter fields for modules.
            "logger": getattr(record, "name", None),
            "level": getattr(record, "levelname", None),
            "levelno": getattr(record, "levelno", None),

            # Location metadata (best-effort).
            "pathname": getattr(record, "pathname", None),
            "lineno": getattr(record, "lineno", None),
            "func": getattr(record, "funcName", None),

            # Timing / context.
            #"created": getattr(record, "created", None),
            #"thread": getattr(record, "threadName", None),
            #"process": getattr(record, "processName", None),

            # Optional exception info (best-effort).
            "exc_text": self._format_exc_text(record.exc_info),
            "exc_info": record.exc_info,
        }
