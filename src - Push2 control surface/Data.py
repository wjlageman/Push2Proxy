# Data.py
"""
Terminology notes:
- This is NOT a relational database.
- There is no schema, no SQL query language, no transactions, and no isolation.
- Paths are resolved structurally, not queried.
- The term "upsert" is used deliberately:
    * It inserts missing paths.
    * It updates existing values.
    * It returns True only if the effective value changed.
- The term 'select' means: resolve a subtree by path segments; it is not SQL SELECT
- The store is optimized for incremental UI/state updates, not for data integrity guarantees.
"""

from __future__ import annotations

import logging, sys, os, re, ast, traceback, json  # Needed for json.loads in _coerce_to_obj
from typing import Any, Dict, Optional, Sequence, Tuple, List, Callable

from .utils import caller_atom, call_stack, fmt_exc


# Central I/O manager (UDP singleton + emitters)
_io = None

# ----------------------------------------------------------------------
# Push2 state cache
#   - _push2_state_info: maps string keys to either
#       * a callable(io, *args)   (for dynamic handlers, like "keys" or "push2_state")
#       * a list of tuples        (each tuple are atoms for io.send(*atoms))
#   - cache helpers do NOT send to UDP, they only manipulate the cache.
#   - get/emit helpers use the IoManager instance (_io) passed in.
# ----------------------------------------------------------------------

_push2_state_data: Dict[str, Any] = {}
_push2_state_last: Dict[str, Tuple[Tuple[Any, ...], ...]] = {}


def upsert(*data):
    try:
        # BUGFIX: *data is a tuple; convert to list so we can append safely.
        data = list(data)

        if data is None or len(data) == 0:
            _io.send('error', 'upsert: expected at least (prop/index, value)', 'got', data, call_stack())
            return False

        # (kept for diagnostics even though data is always list after conversion)
        if not isinstance(data, (list, tuple)):
            _io.send('error', 'IN UPSERT data must be a list or a typle, not', type(data).__name__, call_stack())

        if len(data) == 1:
            data.append('<empty>')

        prop = data[-2]
        value = data[-1]
        path = list(data[:-2]) if len(data) > 2 else []

        root = _push2_state_data

        def _get_child(parent, key):
            if isinstance(parent, dict):
                return parent.get(key, None)
            idx = key
            if not isinstance(idx, int) or idx < 0 or idx >= len(parent):
                return None
            return parent[idx]

        def _set_child(parent, key, child):
            if isinstance(parent, dict):
                parent[key] = child
                return
            idx = key
            while len(parent) <= idx:
                parent.append(None)
            parent[idx] = child

        def _ensure_list(parent, key):
            child = _get_child(parent, key)
            if not isinstance(child, list):
                child = []
                _set_child(parent, key, child)
            return child

        def _ensure_dict(parent, key):
            child = _get_child(parent, key)
            if not isinstance(child, dict):
                child = {}
                _set_child(parent, key, child)
            return child

        def _want_container(next_key):
            return list if isinstance(next_key, int) else dict

        # Walk/create intermediate path (structure-only, does NOT affect return boolean)
        cur = root

        for i, p in enumerate(path):
            if isinstance(p, int):
                _io.send('error', 'upsert: path cannot contain int at dict-root level', 'path', path)
                return False
            if not isinstance(p, str):
                _io.send('error', 'upsert: invalid path element type', type(p).__name__, 'value', p)
                return False
            if not isinstance(cur, dict):
                _io.send('error', 'upsert: expected dict while walking path, got', type(cur).__name__, 'at', p)
                return False

            next_key = path[i + 1] if i < (len(path) - 1) else prop
            want = _want_container(next_key)

            if want is list:
                cur = _ensure_list(cur, p)
            else:
                cur = _ensure_dict(cur, p)

        # Leaf write: ONLY this determines the boolean
        if isinstance(prop, str):
            if not isinstance(cur, dict):
                _io.send('error', 'upsert: expected dict at leaf for str prop, got', type(cur).__name__, 'prop', prop, 'path', path)
                return False

            existed = (prop in cur)
            old = cur.get(prop, None)

            if (not existed) or (old != value):
                cur[prop] = value
                return True
            return False

        if isinstance(prop, int):
            if not isinstance(cur, list):
                _io.send('error', 'upsert: expected list at leaf for int prop, got', type(cur).__name__, 'index', prop, 'path', path)
                return False

            idx = prop
            if idx < 0:
                _io.send('error', 'upsert: negative list index not supported', idx)
                return False

            existed = (idx < len(cur))
            old = cur[idx] if existed else None

            if not existed:
                while len(cur) <= idx:
                    cur.append(None)
                cur[idx] = value
                return True

            if old != value:
                cur[idx] = value
                return True

            return False

        _io.send('error', 'upsert: prop must be str or int, found', 'prop', prop, type(prop).__name__, call_stack())
        return False

    except Exception as ex:
        _io.send('error', 'UPSERT ERROR', 'data', data, 'detail', fmt_exc('upsert failed', ex), call_stack())
        return False


def reset(_io_ref) -> None:
    """
    Reset the push2_state cache and register built-in handlers:
    - 'keys'   -> list all keys
    - 'layout' -> lazy get-layout
    - 'banks', 'colors' as lazy handlers

    You can call this when a new Live Set is loaded to drop stale entries.
    """

    global _io
    _io = _io_ref

    # Clear main cache and "last sent" cache (for emit_state_if_changed)
    _push2_state_data.clear()
    _push2_state_last.clear()

    _io.send('update', 'global_state')
    if upsert('global_state', 'push2proxy_initialising'):
        emit_json('global_state')

    # Built-in handlers as callables
    #_push2_state_data['bank'] = get_parameter_bank
    from .observers.StaticDataObserver import StaticDataObserver
    _push2_state_data['live_device_banks']   = StaticDataObserver.load_banks_normalized
    _push2_state_data['colors']  = StaticDataObserver.load_colors_normalized
    _push2_state_data['live_devices']  = StaticDataObserver.load_live_devices
    upsert('midi_controls', StaticDataObserver.get_midi_controls(_io))

    if upsert('matrix_mode', {'session': {'visible':0}, 'keys': {'visible':0}}):
        emit_json('matrix_mode')


def select(keys=None):
    #_io.send('debug', 'KEYS', keys, type(keys))
    if isinstance(keys, (list, tuple)):
        path = list(keys)
    elif isinstance(keys, str):
        path = [keys]
    elif keys is None:
        return _push2_state_data
    else:
        _io.send('error', 'get_cached_obj: invalid keys type', type(keys).__name__)
        return None

    if len(path) == 0:
        return _push2_state_data

    root_cache = _push2_state_data

    root_key = path[0]
    if root_key is None:
        return None
    if not isinstance(root_key, str):
        root_key = str(root_key)

    obj = root_cache.get(root_key)
    if obj is None:
        mk = mangle_key(str(root_key))
        obj = root_cache.get(mk)

    if root_key == 'live_dialog':
        return None

    if obj is None:
        _io.send('log', 'Warning: root key not found:', root_key if root_key else '<empty>', 'mangled_key', mangle_key(str(root_key)),'path', path if path else '<empty>', '\n', 'keys', keys, '\n', call_stack())
        return None

    for key in path[1:]:
        if isinstance(key, int):
            if not isinstance(obj, list):
                return Exception("resolve: expected list at index %r, got %s" % (key, type(obj).__name__))
            if key < 0 or key >= len(obj):
                return Exception("resolve: list index out of range at index: %r" % (key,))
            obj = obj[key]
        else:
            if isinstance(obj, dict):
                if key not in obj:
                    return Exception("resolve: missing key %r" % (key,))
                obj = obj[key]
            elif isinstance(obj, str):
                pass
            else:
                return Exception("expected dict or string at key %r, got %s" % (key, type(obj).__name__))

    return obj


def to_snake(key: str):
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', str(key))
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s)
    return s.lower().strip('_')


def mangle_key(key: str) -> str:
    try:
        mangle_overrides = {
            # Views -> cache data keys
            'deviceParameterView':      'device_parameter_bank',
            'parameterBankListView':    'parameter_banks',

            'modeState':                'screen_mode',
            'hardwareInfo':             'system',

            'mixerView':                'mixer',
            'mixerSelectView':          'mixer_items',
            'trackMixerSelectView':     'track_mixer',

            'audioClipSettingsView':    'audio_clip',
            'audioLoopSettingsView':    'audio_loop',
            'chainListView':            'chain_list',

            'fixedLengthSelectorView':  'fixed_length_selectors',
            'fixedLengthSettings':      'fixed_length',

            'liveDialogView':           'live_dialog',
            'midiLoopSettingsView':     'midi_loop',
            'midiClipSettingsView':     'midi_clip',
            'notificationView':         'notification',
            'quantizeSettingsView':     'quantization',

            'scalesView':               'scales',
            'setupView':                'setup',
            'stepSettingsView':         'step_settings',
            'transportState':           'transport',
            'convertView':              'convert',

            'devicelistView':           'devices',
            'tracklistView':            'tracks',
            'editModeOptionsView':      'edit_options',

            'browserView':              'browser_view',
            'browserData':              'browser_data',

            'noteSettingsView':         'note_settings',

            'importantGlobals':         'globals',

            'simplerDeviceView':        'simpler',
            'compressorDeviceView':     'compressor',
        }

        v = mangle_overrides.get(key)
        if v:
            return v

        return to_snake(key)

    except Exception as ex:
        try:
            _io.send('error', 'mangle_key failed', 'key', key, fmt_exc('exception', ex), caller_atom())
        except Exception:
            pass

        # Fail-safe fallback: never raise, never return None
        try:
            return str(key)
        except Exception:
            return '<invalid_key>'


# Used by IoManager for external command 'keys'
def handle_keys(path) -> None:
    # Note: Exception can be returned as a data object
    _io.send('debug', 'IN HANDLE_KEYS', path)
    obj = select(path)
    if not obj:
        _io.send('keys', 'error', 'path', path, 'not found')
    elif not path:
        _io.send('keys', 'all', sorted(obj.keys()))
    elif isinstance(obj, dict):
        _io.send('keys', len(path), path, 'keys', sorted(obj.keys()))
    elif isinstance(obj, list):
        _io.send('keys', len(path), path, 'array', len(obj))
    elif isinstance(obj, Exception):
        _io.send('keys', len(path), path, 'error', obj)
    elif not obj:
        _io.send('keys', len(path), path, 'error', 'no keys found')
    else:
        _io.send('keys', len(path), path, 'error', 'No keys or array, found ' + type(obj).__name__, obj)
    return


def emit_max_atoms(keys, obj):
    if isinstance(keys, str):
        keys = [keys]
    
    if len(keys) == 0:
        return

    if obj is None:
        # Works now for empty parameters
        _io.send('data', list(keys), '=>', 'is_enabled', False)
        return

    if isinstance(obj, dict):
        # ------------------------------------------------------------
        # IMPORTANT DEBUGGING BEHAVIOR:
        # If a dict is empty, emit an explicit "<empty>" marker.
        # This makes structures like realtimeMeterData: [{}, {}, ...]
        # visible in "data" output.
        # ------------------------------------------------------------
        if len(obj) == 0:
            _io.send('data', list(keys) + ['=>'], '<empty>')
            return

        # 1) Collect list fields (arrays) so we can emit them first (value_items first)
        list_fields = []
        for k, v in obj.items():
            if isinstance(v, list):
                mk = mangle_key(k)
                list_fields.append((mk, v))

        # 1a) Sort: value_items first, then tracks, then selected_track, then rest
        def _list_prio(mk):
            if mk == 'value_items':
                return (0, mk)
            if mk == 'tracks':
                return (1, mk)
            if mk == 'selected_track':
                return (2, mk)
            return (3, mk)

        list_fields.sort(key=lambda kv: _list_prio(kv[0]))

        # 2) Emit arrays: if it's a "scalar list" -> one line with "... -> <items...>"
        #    otherwise recurse per element
        for mk, v in list_fields:
            scalar_list = True
            for item in v:
                if isinstance(item, (dict, list, tuple)):
                    scalar_list = False
                    break

            if scalar_list:
                if v != None and v != '' and v != []:
                    _io.send('data', list(keys), mk, '->', *v)
                else:
                    _io.send('data', list(keys), mk, '->', '<empty>')
            else:
                keys.append(mk)
                emit_max_atoms(keys, v)
                keys.pop()

        # 3) Collect "pairs" (key/value only, no lists, no dicts) into one line
        pairs = []

        # prefer name/value first if they exist
        try:
            v = obj.get('name')
            if isinstance(v, str) and v:
                pairs.append('name'); pairs.append(v)
        except Exception:
            pass

        try:
            v = obj.get('value')
            if v is not None:
                pairs.append('value'); pairs.append(v)
        except Exception:
            pass

        # CHANGE: use mangle_key consistently (overrides + snake), not to_snake
        for k, v in obj.items():
            if k in ('name', 'value'):
                continue
            if isinstance(v, (list, dict)):
                continue
            pairs.append(mangle_key(k)); pairs.append(v)

        if pairs:
            _io.send('data', list(keys) + ['=>'], *pairs, caller_atom())

        # 4) Then recurse into dict fields (sorted)
        dict_fields = []
        for k, v in obj.items():
            mk = mangle_key(k)  # CHANGE: use mangle_key consistently
            if isinstance(v, dict):
                dict_fields.append((mk, v))

        dict_fields.sort(key=lambda kv: kv[0])

        for mk, v in dict_fields:
            keys.append(mk)
            emit_max_atoms(keys, v)
            keys.pop()

        return

    if isinstance(obj, list):
        # If this list is scalar-only, emit one line instead of per-index.
        scalar_list = True
        for item in obj:
            if isinstance(item, (dict, list, tuple)):
                scalar_list = False
                break

        if scalar_list:
            if obj != None and obj != '' and obj != []:
                _io.send('debug', 'v', type(obj), 'repr', repr(obj), 'str', str(obj))
                _io.send('data', *list(keys), '->', *obj)
            else:
                _io.send('data', *list(keys), '->', '<empty>')
            return

        # Non-scalar list: recurse per element
        for i, v in enumerate(obj):
            keys.append(i)
            emit_max_atoms(keys, v)
            keys.pop()
        return


def emit_path(cmd, *data) -> None:
    try:
        if cmd not in ("data", "json"):
            _io.send("error", "In emit_path cmd must be 'data' or json, but '" + str(cmd) + "' was given")
            return

        # Normalize data input to a list of segments
        if len(data) == 0:
            path = []
        elif len(data) == 1:
            one = data[0]
            if one is None:
                path = []
            elif isinstance(one, (list, tuple)):
                path = list(one)
            else:
                path = [one]
        else:
            path = list(data)

        # Helper: parse "123" / "-1" -> int, else None
        def _parse_int(s):
            if not isinstance(s, str):
                return None
            if s.isdigit():
                return int(s)
            if s.startswith("-") and s[1:].isdigit():
                return int(s)
            return None

        # Safe traversal that supports:
        # - dict keys as str or int
        # - list/tuple indices as int (or numeric strings)
        def _select_smart(root_obj, segments):
            obj = root_obj
            for seg in segments:
                if obj is None:
                    return None

                # Dict: try exact, then int/str alternatives
                if isinstance(obj, dict):
                    if seg in obj:
                        obj = obj[seg]
                        continue

                    i = _parse_int(seg) if isinstance(seg, str) else (seg if isinstance(seg, int) else None)
                    if i is not None and i in obj:
                        obj = obj[i]
                        continue

                    if not isinstance(seg, str):
                        s = str(seg)
                        if s in obj:
                            obj = obj[s]
                            continue

                    return None

                # List / tuple: only index by int
                if isinstance(obj, (list, tuple)):
                    idx = None
                    if isinstance(seg, int):
                        idx = seg
                    else:
                        idx = _parse_int(seg)

                    if idx is None:
                        return None
                    try:
                        obj = obj[idx]
                    except Exception:
                        return None
                    continue

                # Scalar: cannot traverse further
                return None

            return obj

        # Empty => whole model
        if not path:
            obj = _push2_state_data
            if cmd == "json":
                _io.send("json", 1, "<empty>", obj)
            else:
                emit_max_atoms([], obj)
            return

        root = path[0]

        # Resolve root and evaluate callable lazily (unchanged behavior)
        root_obj = select([root])
        if callable(root_obj):
            try:
                computed_data = root_obj()
                if computed_data:
                    _io.send('debug', 'COMPUTED', type(computed_data))
                    upsert(root, computed_data)
            except Exception as exc:
                _io.send("error", "Calling %r callable failed: %r" % (path, exc))
                return
            
        # Handle live_device_banks for jason
        banks = 'live_device_banks'
        #_io.send("debug", "LIVE_DEVICE_BANKS", 'cmd', cmd, 'root', root, 'len', len(data), 'data', list(data)[-1])
        if cmd == 'json' and root == banks and (len(data) == 0 or list(data)[-1] == banks):
            try:
                payload = _push2_state_data.get(banks)
                for k, v in payload.items():
                    _io.send('json', banks, k, v)
                return
            except Exception as ex:
                _io.send('error', 'LIVE_DEVICE_BANKS', ex)
                return

        # Now select with smart traversal (supports int keys safely)
        obj = _select_smart(_push2_state_data, path)

        if obj is None:
            if cmd == "json":
                _io.send("json", list(path), "<not_found>")
            else:
                _io.send("data", list(path), '->', "<not_found>")
            return

        if isinstance(obj, Exception):
            if cmd == "json":
                _io.send("json", list(path), "error", obj)
            else:
                _io.send("data", list(path), '->', "error", obj)
            return

        # Emit
        if cmd == "json":
            if isinstance(obj, (dict, list)):
                _io.send("json", list(path), json.dumps(obj))
            else:
                head = list(path)[:-1]
                tail = list(path)[-1]
                if not head:
                    _io.send("json", tail, {tail: obj})
                else:
                    _io.send("json", head, {tail: obj})
            return

        # cmd == 'data'
        if isinstance(obj, (dict, list)):
            emit_max_atoms(list(path), obj)
            return

        if obj is None:
            _io.send("data", list(path), '->', "<empty>", call_stack())
        else:
            _io.send("data", list(path), '->', obj, call_stack())

    except Exception as ex:
        _io.send("error", call_stack())
        _io.send("error", fmt_exc("Error in emit_path", ex), call_stack())


def emit_data(*data) -> None:
    emit_path('data', *data)

def emit_json(*data) -> None:
    emit_path('json', *data)
