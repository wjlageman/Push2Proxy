# -*- coding: utf-8 -*-
# Push2/Push2Access.py
#
# Purpose
# -------
# Provide a robust, read-only bridge to the *real* Push 2 control surface
#
# Scope & guarantees
# ------------------
# - Does NOT touch UDP or MIDI. No logging to /proxy. Optional DEBUG goes to /data.
# - Adds a tiny in-module registry so the init wrapper (or your loader) can
#   register the original Push2 ControlSurface instance at creation time.
# - Backward-compatible: still performs heuristic discovery (BFS + Live API)
#   if nothing was registered yet.
# - __init__ is exception-safe and never raises; failures are stored in _last_error.
#
# Public API
# ----------
#   register_script(script_obj, router_like=None) -> None
#   Push2Access(router_like, strict: bool = False, debug: bool = False)
#   .get_dynamic_root() -> Optional[dict]
#   .get_last_error() -> Optional[str]
#   .get_script_version() -> Optional[str]   # NEW

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Deque, Tuple
from collections import deque

# ---------------- module-local registry ----------------
# NOTE: single underscore to avoid name-mangling.

_REG_SCRIPT: Any = None
_REG_ROUTER: Any = None

def register_script(script_obj: Any, router_like: Any = None) -> None:
    """
    Record the original Push2 ControlSurface instance for later access by GetDataCommands.

    Call this immediately after creating the original Push2 script in your
    init wrapper. It's safe to call multiple times; the latest non-None wins.
    """
    global _REG_SCRIPT, _REG_ROUTER
    if script_obj is not None:
        _REG_SCRIPT = script_obj
    if router_like is not None:
        _REG_ROUTER = router_like


# ---------------- tiny /data sender for DEBUG ----------------

def _proxy(x: Any) -> Any:
    for attr in ('proxy', '_proxy', 'p'):
        try:
            v = getattr(x, attr, None)
            if v is not None:
                return v
        except Exception:
            pass
    return x

def _send_line(router_like: Any, s: str) -> None:
    """Send a single line to /data if possible; silent on errors."""
    try:
        r = _proxy(router_like)
        send_fn = getattr(r, "_send", None) or getattr(r, "send", None)
        if send_fn:
            send_fn(("/data", "line", s))
    except Exception:
        pass


# ---------------- helpers ----------------

def _safe_get(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return None

def _maybe_call(x: Any) -> Any:
    try:
        return x() if callable(x) else x
    except Exception:
        return None

def _is_script_candidate(x: Any) -> bool:
    if x is None:
        return False
    try:
        names = set(dir(x))
    except Exception:
        return False
    has_device_comp = ('_device_component' in names) or ('device_component' in names)
    has_appish = any(k in names for k in ('application', '_application', 'c_instance'))
    has_components = any(k in names for k in ('components', '_components'))
    class_name = getattr(getattr(x, '__class__', type(x)), '__name__', '')
    looks_named = ('Push2' in class_name) or ('Push' in class_name)
    return (has_device_comp and (has_appish or has_components)) or looks_named

_ATTR_WHITELIST: Tuple[str, ...] = (
    'host','_host','root','_root','app','_app','application','_application',
    'surface','_surface','control_surface','_control_surface',
    'script','_script','__script',
    'parent','_parent','owner','_owner',
    'push','_push','push2','_push2',
    'main','_main','ctx','_ctx',
)

_CONTAINER_ATTRS: Tuple[str, ...] = (
    'surfaces','_surfaces','children','_children','items','_items',
)

def _stringify_version(v: Any) -> Optional[str]:
    """Render common version shapes to a short human string."""
    try:
        if v is None:
            return None
        # Plain string
        if isinstance(v, str):
            s = v.strip()
            return s or None
        # Tuple/list like (major, minor, patch[, extra])
        if isinstance(v, (list, tuple)):
            parts = []
            for p in v:
                if isinstance(p, (int, float)):
                    parts.append(str(int(p)))
                elif isinstance(p, str):
                    parts.append(p.strip())
                else:
                    parts.append(str(p))
            s = ".".join([p for p in parts if p != ""])
            return s or None
        # Int/float
        if isinstance(v, (int, float)):
            return str(v)
        # Objects with attributes
        for name in ('version', 'VERSION'):
            try:
                attr = getattr(v, name, None)
                s = _stringify_version(attr)
                if s:
                    return s
            except Exception:
                pass
        # Fallback repr
        s = str(v).strip()
        return s or None
    except Exception:
        return None


class Push2Access(object):
    """Best-effort access to the running Push2 script."""
    def __init__(self, router_like: Any, strict: bool = False, debug: bool = False) -> None:
        # Never raise from __init__; store error and proceed in a safe state.
        self._router = router_like
        self._strict = bool(strict)
        self._debug = bool(debug)
        self._script: Any = None
        self._last_error: Optional[str] = None
        try:
            self._locate_script()
        except Exception as ex:
            # Store and optionally emit DEBUG — but keep constructor non-throwing.
            self._last_error = f"init-locate-exception: {ex!r}"
            if self._debug:
                _send_line(self._router, f"DEBUG: Push2Access.__init__ failed: {ex!r}")

    # -------------------- discovery --------------------
    def _locate_script(self) -> None:
        """
        Discovery order:
        0) Use explicitly registered script (if any).
        1) Check a few direct attributes on router/proxy.
        2) BFS crawl over a whitelisted attribute graph (depth ≤ 3, nodes ≤ 200).
        3) Try Live.Application.get_application().control_surfaces (inside Live only).
        """
        try:
            if _REG_SCRIPT is not None and _is_script_candidate(_REG_SCRIPT):
                self._script = _REG_SCRIPT
                if self._debug:
                    _send_line(self._router, "DEBUG: locate: used registered script")
                return
        except Exception as ex:
            self._last_error = f"locate-registered-exception: {ex!r}"

        r = _proxy(self._router)
        if self._debug:
            _send_line(self._router, f"DEBUG: locate: start; router={type(r).__name__}")

        # 1) direct hits
        direct_candidates: List[Any] = [r]
        for name in _ATTR_WHITELIST:
            try:
                v = getattr(r, name)
            except Exception:
                v = None
            if v is not None:
                direct_candidates.append(v)

        for obj in direct_candidates:
            for name in ('__script', '_script', 'script'):
                try:
                    v = getattr(obj, name)
                except Exception:
                    v = None
                if _is_script_candidate(v):
                    self._script = v
                    if self._debug:
                        _send_line(self._router, f"DEBUG: locate: direct hit via {name} on {type(obj).__name__}")
                    return

        # 2) BFS crawl with tight limits
        visited: Set[int] = set()
        q: Deque[Tuple[Any, int]] = deque()

        def _enqueue(o: Any, d: int) -> None:
            if o is None:
                return
            oid = id(o)
            if oid in visited:
                return
            visited.add(oid)
            q.append((o, d))

        for obj in direct_candidates:
            _enqueue(obj, 0)

        MAX_NODES = 200
        found = None
        while q and len(visited) <= MAX_NODES:
            obj, depth = q.popleft()
            try:
                if _is_script_candidate(obj):
                    found = obj
                    break
            except Exception:
                continue

            if depth >= 3:
                continue

            for name in _ATTR_WHITELIST:
                try:
                    v = getattr(obj, name)
                except Exception:
                    v = None
                if _is_script_candidate(v):
                    found = v
                    break
                if v is not None:
                    _enqueue(v, depth + 1)
            if found is not None:
                break

            for cname in _CONTAINER_ATTRS:
                try:
                    cont = getattr(obj, cname)
                except Exception:
                    cont = None
                if isinstance(cont, dict):
                    for kv in list(cont.values())[:32]:
                        if _is_script_candidate(kv):
                            found = kv
                            break
                        _enqueue(kv, depth + 1)
                elif isinstance(cont, (list, tuple)):
                    for it in list(cont)[:64]:
                        if _is_script_candidate(it):
                            found = it
                            break
                        _enqueue(it, depth + 1)
                if found is not None:
                    break
            if found is not None:
                break

        if found is not None:
            self._script = found
            if self._debug:
                _send_line(self._router, f"DEBUG: locate: BFS found {type(found).__name__}")
            return

        # 3) Try Live API if present (inside Ableton only)
        try:
            import Live  # type: ignore
            app = getattr(Live, 'Application', None)
            if app is not None:
                get_app = getattr(app, 'get_application', None)
                live_app = get_app() if callable(get_app) else None
                if live_app is not None:
                    css = getattr(live_app, 'control_surfaces', None)
                    css = css() if callable(css) else css
                    if isinstance(css, (list, tuple)):
                        for cs in css:
                            if _is_script_candidate(cs):
                                self._script = cs
                                if self._debug:
                                    _send_line(self._router, "DEBUG: locate: Live API control_surfaces hit")
                                return
        except Exception as ex:
            # Live import can fail outside Ableton — that's OK.
            self._last_error = f"locate-liveapi-exception: {ex!r}"

        # Not found
        self._script = None
        if self._strict:
            self._last_error = self._last_error or "no-script-found"

    # -------------------- public API --------------------
    def get_dynamic_root(self) -> Optional[Dict[str, Any]]:
        """Return a minimal-yet-useful dynamic snapshot or None if unavailable."""
        s = self._script
        if s is None:
            if self._strict:
                return None
            # Re-attempt discovery once in lax mode
            try:
                self._locate_script()
            except Exception as ex:
                self._last_error = f"relocate-exception: {ex!r}"
                if self._debug:
                    _send_line(self._router, f"DEBUG: relocate failed: {ex!r}")
                return None
            s = self._script
            if s is None:
                return None

        # Extract device, banks, parameters best-effort
        try:
            dpc = _safe_get(s, '_device_component') or _safe_get(s, 'device_component')
            provider = _safe_get(dpc, '_parameter_provider') or _safe_get(dpc, 'parameter_provider')
            bank_reg = _safe_get(dpc, '_bank_registry') or _safe_get(dpc, 'bank_registry')
            bank_idx = _safe_get(dpc, '_bank_index') or _safe_get(dpc, 'bank_index')

            dev = _safe_get(dpc, '_device') or _safe_get(dpc, 'device')
            dev_name = _maybe_call(_safe_get(dev, 'name'))

            bank_names: List[str] = []
            try:
                names = _safe_get(bank_reg, 'names')
                names = _maybe_call(names)
                if not isinstance(names, (list, tuple)):
                    names = _maybe_call(_safe_get(provider, 'bank_names'))
                if isinstance(names, (list, tuple)):
                    bank_names = [str(x) for x in names]
            except Exception:
                bank_names = []

            idx = None
            try:
                idx_val = _maybe_call(bank_idx)
                if isinstance(idx_val, (int, float)):
                    idx = int(idx_val)
            except Exception:
                idx = None
            bank_name = bank_names[idx] if isinstance(idx, int) and 0 <= idx < len(bank_names) else None

            params: List[Dict[str, Optional[str]]] = []
            raw_params = _maybe_call(_safe_get(provider, 'parameters'))
            if not isinstance(raw_params, (list, tuple)) or not raw_params:
                raw_params = _maybe_call(_safe_get(dpc, 'parameters'))
            if isinstance(raw_params, (list, tuple)):
                for p in raw_params:
                    nm = _maybe_call(_safe_get(p, 'name'))
                    params.append({'name': nm if isinstance(nm, str) else None})

            snapshot: Dict[str, Any] = {
                'device_name': dev_name if isinstance(dev_name, str) else None,
                'banks': bank_names,
                'bank_index': idx,
                'bank_name': bank_name,
                'parameters': params,
            }
            if self._debug:
                _send_line(self._router, f"DEBUG: dynamic-root ok; device={snapshot['device_name']!r}, banks={len(bank_names)}")
            return snapshot
        except Exception as ex:
            self._last_error = f"dynamic-root-exception: {ex!r}"
            if self._debug:
                _send_line(self._router, f"DEBUG: dynamic-root failed: {ex!r}")
            return None

    def get_script_version(self) -> Optional[str]:
        """
        Best-effort version discovery for the original Push2 control surface.
        Tries common attributes on the script instance and on its defining module.
        Returns a short human string (e.g. '12.2.5' or '1.0.0a3') or None.
        """
        s = self._script
        if s is None:
            return None

        # 1) Common attributes on the instance
        for name in ('version', '_version', 'script_version', 'push_version', 'push2_version'):
            try:
                v = getattr(s, name, None)
                sv = _stringify_version(_maybe_call(v))
                if sv:
                    return sv
            except Exception:
                pass

        # 2) A getter method
        for name in ('get_version', 'get_script_version'):
            try:
                fn = getattr(s, name, None)
                if callable(fn):
                    sv = _stringify_version(fn())
                    if sv:
                        return sv
            except Exception:
                pass

        # 3) Module-level constants
        try:
            modname = getattr(s, '__module__', None)
            if isinstance(modname, str) and modname:
                mod = __import__(modname, fromlist=['*'])
                for name in ('__version__', 'VERSION', 'version'):
                    try:
                        v = getattr(mod, name, None)
                        sv = _stringify_version(v)
                        if sv:
                            return sv
                    except Exception:
                        pass
        except Exception:
            pass

        # 4) Class-level attributes
        try:
            cls = getattr(s, '__class__', None)
            for name in ('__version__', 'VERSION', 'version', '_version'):
                try:
                    v = getattr(cls, name, None)
                    sv = _stringify_version(v)
                    if sv:
                        return sv
                except Exception:
                    pass
        except Exception:
            pass

        return None

    def get_last_error(self) -> Optional[str]:
        return self._last_error
