# Push2/observers/StaticDataObserver.py
#
# Purpose
# -------
# Provide static lookup tables that are stable for a given Live/Push2 script version.
# Data is loaded lazily and cached in Data so downstream code can treat it as immutable.
#
# This file currently provides:
#   - live_device_banks: device parameter bank definitions (normalized from Push2Original.*)
#   - colors: Push2 color tables (normalized to JSON-safe shapes)
#   - midi_controls: mapping tables for CC/Note ids and control names (project-specific)
#
# Contract
# --------
# - Data.reset() seeds the cache with callables:
#       _push2_state_data['live_device_banks']  = StaticDataObserver._load_banks_normalized
#       _push2_state_data['colors'] = StaticDataObserver._load_colors_normalized
# - On first invocation a callable:
#       1) loads raw data from Push2Original.*
#       2) normalizes it (JSON-safe, stable shapes)
#       3) returns the normalized data (Data._emit_path replaces the callable with data)
# - No emit/routing is performed here; this module only returns normalized data.

from __future__ import annotations

import importlib
from typing import Any, Dict, List, Optional
from ..utils import fmt_exc


# --------------------
# Helpers (banks)
# --------------------

def _looks_dynamic(x: Any) -> bool:
    try:
        if callable(x):
            return True
        cls = getattr(x, "__class__", None)
        name = getattr(cls, "__name__", "")
        if name and name not in ("str", "int", "float", "bool", "dict", "list", "tuple"):
            return True
    except Exception as ex:
        StaticDataObserver._log_error_static("looks_dynamic failed", ex)
    return False


def _safe_str(x: Any, default: str = "<dynamic>") -> str:
    if x is None:
        return "<empty>"
    if isinstance(x, str):
        return x if x.strip() != "" else "<empty>"
    try:
        s = str(x)
        if isinstance(s, str):
            return s if s.strip() != "" else "<empty>"
    except Exception:
        return default
    return default


def _is_psd(x: Any) -> bool:
    try:
        if isinstance(x, str) and x.strip() == "<ParameterSlotDescription>":
            return True
        cls = getattr(x, "__class__", type(x))
        if "ParameterSlotDescription" in getattr(cls, "__name__", ""):
            return True
        if isinstance(x, dict):
            keys = set(x.keys())
            if ("_default_parameter_name" in keys or "ResultingName" in keys) and any(k.startswith("_") for k in keys):
                return True
    except Exception as ex:
        StaticDataObserver._log_error_static("is_psd failed", ex)
    return False


def _psd_static_label(x: Any) -> Optional[str]:
    try:
        for attr in ("name", "_default_parameter_name", "ResultingName"):
            v = getattr(x, attr, None)
            if isinstance(v, str) and v.strip():
                return v

        if isinstance(x, dict):
            for key in ("name", "_default_parameter_name", "ResultingName"):
                v = x.get(key)
                if isinstance(v, str) and v.strip():
                    return v
    except Exception as ex:
        StaticDataObserver._log_error_static("psd_static_label failed", ex)
    return None


def _psd_resolve_parameter(x: Any) -> Optional[Any]:
    try:
        getter = getattr(x, "get_parameter", None)
        if callable(getter):
            p = getter()
            return p if p is not None else None
    except Exception:
        pass

    try:
        param_getter = getattr(x, "parameter_getter", None)
        if callable(param_getter):
            p = param_getter()
            return p if p is not None else None
    except Exception:
        pass

    try:
        p = getattr(x, "parameter", None)
        if p is not None:
            return p
    except Exception:
        pass

    try:
        if isinstance(x, dict):
            g = x.get("get_parameter") or x.get("parameter_getter")
            if callable(g):
                p = g()
                return p if p is not None else None
            p = x.get("parameter")
            if p is not None:
                return p
    except Exception:
        pass

    return None


def _param_name(p: Any) -> Optional[str]:
    try:
        nm = getattr(p, "name", None)
        if isinstance(nm, str) and nm.strip():
            return nm
    except Exception:
        pass
    try:
        nm = getattr(p, "display_name", None)
        if isinstance(nm, str) and nm.strip():
            return nm
    except Exception:
        pass
    return None


def _norm_params(params_obj: Any) -> List[str]:
    out: List[str] = ["<empty>"] * 8
    try:
        if isinstance(params_obj, (list, tuple)):
            for i in range(min(8, len(params_obj))):
                v = params_obj[i]

                if _is_psd(v):
                    p = _psd_resolve_parameter(v)
                    if p is not None:
                        pname = _param_name(p)
                        if isinstance(pname, str) and pname.strip():
                            out[i] = "#%s" % pname
                            continue

                    lab = _psd_static_label(v)
                    if isinstance(lab, str) and lab.strip():
                        out[i] = "$%s" % lab
                        continue

                    out[i] = "<dynamic>"
                    continue

                if v is None:
                    out[i] = "<empty>"
                elif isinstance(v, str):
                    out[i] = v if v.strip() != "" else "<empty>"
                else:
                    out[i] = "<dynamic>" if _looks_dynamic(v) else _safe_str(v)
    except Exception as ex:
        StaticDataObserver._log_error_static("norm_params failed", ex)
    return out


def _norm_options(options_obj: Any) -> List[str]:
    out: List[str] = ["<empty>"] * 7
    try:
        if isinstance(options_obj, (list, tuple)):
            for i in range(min(7, len(options_obj))):
                v = options_obj[i]
                if isinstance(v, str):
                    out[i] = v if v.strip() != "" else "<empty>"
                elif bool(v):
                    out[i] = "option%d" % i
            return out

        if isinstance(options_obj, dict):
            for i in range(7):
                key = "option%d" % i
                if key not in options_obj:
                    continue
                v = options_obj.get(key)
                if isinstance(v, str):
                    out[i] = v if v.strip() != "" else "<empty>"
                elif bool(v):
                    out[i] = "option%d" % i
            return out
    except Exception as ex:
        StaticDataObserver._log_error_static("norm_options failed", ex)
    return out


def _collect_device_bank_names(dev_obj: Dict[str, Any]) -> List[str]:
    if not isinstance(dev_obj, dict):
        return []
    names: List[str] = []
    for k, v in dev_obj.items():
        if k == "Options":
            continue
        if isinstance(v, dict) and any(x in v for x in ("Parameters", "Options")):
            names.append(k)
    names.sort()
    return names


def _import_custom_bank_definitions():
    for name in (
        "Push2.Push2Original.custom_bank_definitions",
        "Push2Original.custom_bank_definitions",
    ):
        try:
            return importlib.import_module(name)
        except Exception:
            continue
    return None


def _get_banks_dict_from_module(mod: Any) -> Optional[Dict[str, Any]]:
    if mod is None:
        return None

    for attr in ("get_banks_dict", "load_banks_dict"):
        fn = getattr(mod, attr, None)
        if callable(fn):
            try:
                d = fn()
                if isinstance(d, dict):
                    return d
            except Exception:
                continue

    for attr in ("BANK_DEFINITIONS", "BANKS"):
        d = getattr(mod, attr, None)
        if isinstance(d, dict):
            return d

    return None


def _create_banks_dict() -> Dict[str, Any]:
    mod = _import_custom_bank_definitions()
    banks = _get_banks_dict_from_module(mod)
    if not isinstance(banks, dict):
        return {"__error__": "Could not load banks dict"}

    out: Dict[str, Any] = {}

    for device_name, dev_obj in banks.items():
        if not isinstance(dev_obj, dict):
            continue

        bank_names = _collect_device_bank_names(dev_obj)
        banks_list: List[Dict[str, Any]] = []

        for bank_name in bank_names:
            bank_obj = dev_obj.get(bank_name, {})
            if not isinstance(bank_obj, dict):
                continue

            params = _norm_params(bank_obj.get("Parameters"))
            opts = _norm_options(bank_obj.get("Options"))

            bank_entry: Dict[str, Any] = {
                "name": bank_name,
                "parameters": list(params),
            }

            if any(o != "<empty>" for o in opts):
                bank_entry["options"] = list(opts)

            banks_list.append(bank_entry)

        if banks_list:
            out[str(device_name)] = {"banks": banks_list}

    if not out:
        return {"__error__": "Banks dict was empty after normalization"}

    return out


# --------------------
# Helpers (colors)
# --------------------

def _normalize_rgb_components_to_int(r: Any, g: Any, b: Any) -> Optional[int]:
    try:
        rr = float(r)
        gg = float(g)
        bb = float(b)

        if 0.0 <= rr <= 1.0 and 0.0 <= gg <= 1.0 and 0.0 <= bb <= 1.0:
            rr *= 255.0
            gg *= 255.0
            bb *= 255.0

        ri = int(round(rr))
        gi = int(round(gg))
        bi = int(round(bb))

        if ri < 0:
            ri = 0
        elif ri > 255:
            ri = 255

        if gi < 0:
            gi = 0
        elif gi > 255:
            gi = 255

        if bi < 0:
            bi = 0
        elif bi > 255:
            bi = 255

        return ((ri & 255) << 16) | ((gi & 255) << 8) | (bi & 255)
    except Exception:
        return None


def _coerce_rgb_to_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None

        if isinstance(v, (list, tuple)) and len(v) >= 3:
            return _normalize_rgb_components_to_int(v[0], v[1], v[2])

        if isinstance(v, dict):
            if "r" in v and "g" in v and "b" in v:
                return _normalize_rgb_components_to_int(v.get("r"), v.get("g"), v.get("b"))
            if "red" in v and "green" in v and "blue" in v:
                return _normalize_rgb_components_to_int(v.get("red"), v.get("green"), v.get("blue"))

        if isinstance(v, (int, float)):
            x = int(v)
            if x < 0:
                x = 0
            if x <= 0xFFFFFF:
                return x & 0xFFFFFF
    except Exception:
        return None

    return None


def _decode_screen_color_to_int(io: Any, obj: Any, path: str) -> int:
    cls_name = getattr(getattr(obj, "__class__", None), "__name__", type(obj).__name__)

    for name in ("rgb", "color", "value", "packed"):
        try:
            v = getattr(obj, name, None)
        except Exception as ex:
            io.send("error", "colors: getattr failed", path, name, repr(ex))
            continue

        if v is None:
            continue

        rgb_int = _coerce_rgb_to_int(v)
        if rgb_int is not None:
            return rgb_int

    try:
        r = getattr(obj, "r", None)
        g = getattr(obj, "g", None)
        b = getattr(obj, "b", None)
        rgb_int = _normalize_rgb_components_to_int(r, g, b)
        if rgb_int is not None:
            return rgb_int
    except Exception as ex:
        io.send("error", "colors: r/g/b decode failed", path, repr(ex))

    try:
        r = getattr(obj, "red", None)
        g = getattr(obj, "green", None)
        b = getattr(obj, "blue", None)
        rgb_int = _normalize_rgb_components_to_int(r, g, b)
        if rgb_int is not None:
            return rgb_int
    except Exception as ex:
        io.send("error", "colors: red/green/blue decode failed", path, repr(ex))

    for name in ("to_tuple", "as_tuple", "to_dict", "as_dict"):
        try:
            fn = getattr(obj, name, None)
        except Exception as ex:
            io.send("error", "colors: getattr callable failed", path, name, repr(ex))
            continue

        if callable(fn):
            try:
                v = fn()
            except Exception as ex:
                io.send("error", "colors: callable decode failed", path, name, repr(ex))
                continue

            rgb_int = _coerce_rgb_to_int(v)
            if rgb_int is not None:
                return rgb_int

    try:
        r = repr(obj)
    except Exception as ex:
        io.send("error", "colors: repr failed", path, repr(ex))
        r = "<unreprable>"

    io.send("error", "colors: could not decode ScreenColor object", path, cls_name, r)
    return 0


def _jsonify_colors(io: Any, v: Any, path: str, depth: int = 0) -> Any:
    if depth > 6:
        io.send("error", "colors: jsonify depth exceeded", path)
        return 0

    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v

    if isinstance(v, (list, tuple)):
        out_list = []
        for i, item in enumerate(v):
            out_list.append(_jsonify_colors(io, item, "%s[%d]" % (path, i), depth + 1))
        return out_list

    if isinstance(v, dict):
        dd: Dict[str, Any] = {}
        for kk, vv in v.items():
            dd[str(kk)] = _jsonify_colors(io, vv, "%s.%s" % (path, str(kk)), depth + 1)
        return dd

    cls_name = getattr(getattr(v, "__class__", None), "__name__", "")
    if cls_name == "ScreenColor" or "ScreenColor" in cls_name:
        return _decode_screen_color_to_int(io, v, path)

    try:
        r = repr(v)
    except Exception as ex:
        io.send("error", "colors: repr failed for unknown object", path, repr(ex))
        r = "<unreprable>"

    io.send("error", "colors: non-json object encountered", path, cls_name or type(v).__name__, r)
    return 0


def _split_color_table(io: Any, v: Any) -> Dict[str, Any]:
    """
    Input is expected to be a list where each entry is one of:
      - (index, rgb_int, bw)
      - [index, rgb_int, bw]
      - dict with keys like index/rgb/bw (fallback)
    Output:
      {
        "color_table": [rgb_int, ...],
        "bw_table":    [bw, ...]
      }
    """
    if not isinstance(v, (list, tuple)):
        io.send("error", "colors: COLOR_TABLE is not list/tuple", type(v).__name__)
        return {"color_table": [], "bw_table": []}

    rgb_list: List[int] = []
    bw_list: List[int] = []

    for i, entry in enumerate(v):
        idx = None
        rgb = None
        bw = None

        if isinstance(entry, (list, tuple)) and len(entry) >= 3:
            idx = entry[0]
            rgb = entry[1]
            bw = entry[2]
        elif isinstance(entry, dict):
            idx = entry.get("index", entry.get("idx", i))
            rgb = entry.get("rgb", entry.get("rgb_int", entry.get("color")))
            bw = entry.get("bw", entry.get("brightness", entry.get("level")))
        else:
            io.send("error", "colors: COLOR_TABLE entry unexpected type", i, type(entry).__name__)
            continue

        try:
            # Keep ordering by index; assume table is already sorted by idx.
            _ = int(idx) if idx is not None else i
        except Exception as ex:
            io.send("error", "colors: COLOR_TABLE bad index", i, repr(ex))
            # still continue, using list order
        try:
            rgb_i = int(rgb) & 0xFFFFFF
        except Exception as ex:
            io.send("error", "colors: COLOR_TABLE bad rgb", i, repr(ex))
            rgb_i = 0

        try:
            bw_i = int(bw)
        except Exception as ex:
            io.send("error", "colors: COLOR_TABLE bad bw", i, repr(ex))
            bw_i = 0

        rgb_list.append(rgb_i)
        bw_list.append(bw_i)

    if not rgb_list:
        io.send("error", "colors: COLOR_TABLE split produced empty rgb_list")
    if not bw_list:
        io.send("error", "colors: COLOR_TABLE split produced empty bw_list")

    return {"color_table": rgb_list, "bw_table": bw_list}


def _create_colors_dict(io: Any) -> Dict[str, Any]:
    mod = None
    last_exc: Optional[Exception] = None

    for name in ("Push2.Push2Original.colors", "Push2Original.colors"):
        try:
            mod = importlib.import_module(name)
            break
        except Exception as ex:
            last_exc = ex
            mod = None

    if mod is None:
        io.send("error", "colors: could not import Push2Original.colors", repr(last_exc) if last_exc else "<no-exception>")
        return {"__error__": "Could not import Push2Original.colors"}

    out: Dict[str, Any] = {}
    missing: List[str] = []

    # Split COLOR_TABLE into two arrays
    color_table = getattr(mod, "COLOR_TABLE", None)
    if color_table is None:
        missing.append("COLOR_TABLE")
    else:
        split = _split_color_table(io, color_table)
        out["color_table"] = split.get("color_table", [])
        out["bw_table"] = split.get("bw_table", [])

    # Other tables
    wanted = (
        ("PUSH_INDEX_TO_COLOR_INDEX", "push_index_to_color_index"),
        ("COLOR_INDEX_TO_PUSH_INDEX", "color_index_to_push_index"),
        ("PUSH_INDEX_TO_SCREEN_COLOR", "push_index_to_screen_color"),
        ("COLOR_INDEX_TO_SCREEN_COLOR", "color_index_to_screen_color"),
        ("COLOR_INDEX_TO_SCREEN_COLOR_SHADES", "color_index_to_screen_color_shades"),
    )


    for attr, key in wanted:
        v = getattr(mod, attr, None)
        if v is None:
            missing.append(attr)
            continue
        # out[key] = _jsonify_colors(io, v, "colors.%s" % attr)
        normalized = _jsonify_colors(io, v, "colors.%s" % attr)

        # >>> ONLY CHANGE: convert inner shade lists to dict
        if key == "color_index_to_screen_color_shades":
            dict = {}
            dict[0] =  list(_jsonify_colors(io, v, "colors.%s" % attr)[0])
            dict[1] =  list(_jsonify_colors(io, v, "colors.%s" % attr)[1])
            dict[2] =  list(_jsonify_colors(io, v, "colors.%s" % attr)[2])
            dict[3] =  list(_jsonify_colors(io, v, "colors.%s" % attr)[3])
            dict[4] =  list(_jsonify_colors(io, v, "colors.%s" % attr)[4])
            normalized = dict
        
        out[key] = normalized

    if missing:
        io.send("error", "colors: missing expected tables in Push2Original.colors", missing)

    if not out:
        io.send("error", "colors: no color data collected (all expected tables missing)")
        return {"__error__": "No color data collected"}

    return out


# --------------------
# Observer
# --------------------

class StaticDataObserver(object):
    _INSTANCE: Optional["StaticDataObserver"] = None

    def __init__(self, host: Any, module_manager: Any, io: Any) -> None:
        self._host = host
        self._module_manager = module_manager
        self._io = io

        self._attached = False

        StaticDataObserver._INSTANCE = self

    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True

    @staticmethod
    def _log_error_static(msg: str, ex: Exception) -> None:
        inst = StaticDataObserver._INSTANCE
        if inst is None:
            return
        inst._io.send("error", msg, repr(ex))

    @staticmethod
    def load_banks_normalized() -> Any:
        inst = StaticDataObserver._INSTANCE
        return inst._load_banks_normalized_instance()

    @staticmethod
    def load_colors_normalized() -> Any:
        inst = StaticDataObserver._INSTANCE
        if inst is None:
            return {}
        return inst._load_colors_normalized_instance()

    def _load_colors_normalized_instance(self) -> Any:
        self._io.send("debug", "IN _LOAD_COLORS_NORMALIZED")

        raw = _create_colors_dict(self._io)

        if not isinstance(raw, dict):
            self._io.send("error", "colors: create_colors_dict returned non-dict", type(raw).__name__)
            return {"__error__": "create_colors_dict returned non-dict"}

        if "__error__" in raw:
            self._io.send("error", "colors: source returned error", raw.get("__error__"))
            return raw

        return raw


    @staticmethod
    def load_live_devices() -> Any:
        inst = StaticDataObserver._INSTANCE
        try:
            inst._io.send("debug", "IN _LOAD_BANKS_NORMALIZED")

            raw = _create_banks_dict()

            if not isinstance(raw, dict):
                inst._io.send("error", "banks: create_banks_dict returned non-dict", type(raw).__name__)
                return {"devices": {}, "__error__": "create_banks_dict returned non-dict"}

            if "__error__" in raw:
                inst._io.send("error", "banks: source returned error", raw.get("__error__"))
                return {"devices": {}, "__error__": raw.get("__error__")}

            #devices: List = []
            #for dev_key, dev_val in raw.items():
            #    devices.append(str(dev_key))
            devices = sorted(str(dev_key) for dev_key in raw.keys())

            if not devices:
                inst._io.send("error", "banks: normalized live_devices is empty")

            return devices
        except Exception as ex:
            inst._io.send('error', 'LOAD_LIVE_DEVICES', fmt_exc('error', ex))


    def _load_banks_normalized_instance(self) -> Any:
        self._io.send("debug", "IN _LOAD_BANKS_NORMALIZED")

        raw = _create_banks_dict()

        if not isinstance(raw, dict):
            self._io.send("error", "banks: create_banks_dict returned non-dict", type(raw).__name__)
            return {"devices": {}, "__error__": "create_banks_dict returned non-dict"}

        if "__error__" in raw:
            self._io.send("error", "banks: source returned error", raw.get("__error__"))
            return {"devices": {}, "__error__": raw.get("__error__")}

        devices: Dict[str, Any] = {}
        for dev_key, dev_val in raw.items():
            devices[str(dev_key)] = dev_val
        #devices = {str(k): raw[k] for k in sorted(raw.keys())}

        if not devices:
            self._io.send("error", "banks: normalized devices dict is empty")

        return devices

    # MIDI control id mapping tables.
    # Values < 128 are MIDI CC numbers (0..127).
    # Values >= 128 are MIDI Note numbers with +128 offset to avoid CC collisions.
    # Used by MidiObserver (LED cache) and by external tooling (Max).

    @staticmethod
    def get_midi_controls(io) -> Dict:
        controls_by_name = {
            # Encoders
            # 3 special encoders
            "tempo":           14, "swing":          15, "master_encoder":  79,
            "tempo_touch": 128+10, "swing_touch": 128+9, "master_touch": 128+8,

            # Central unit
            "encoder_1":       71, "encoder_2":      72, "encoder_3":       73, "encoder_4":      74, "encoder_5":       75, "encoder_6":       76, "encoder_7":        77, "encoder_8":     78,
            "touch_1":      128+0, "touch_2":     128+1, "touch_3":      128+2, "touch_4":     128+3, "touch_5":      128+4, "touch_6":      128+5, "touch_7":       128+6, "touch_8":    128+7,
            "detail_1":       102, "detail_2":      103, "detail_3":       104, "detail_4":      105, "detail_5":       106, "detail_6":       107, "detail_7":        108, "detail_8":     109,
            "track_1":         20, "track_2":        21, "track_3":         22, "track_4":        23, "track_5":         24, "track_6":         25, "track_7":          26, "track_8":       27,

            # Left buttons
            "tap_tempo":        3, "metronome":       9,
            "delete":         118,
            "undo":           119,
            "mute":            60, "solo":           61, "stop": 29,
            "convert":         35,
            "double_loop":    117,
            "quantize":       116,
            "duplicate":       88,
            "new":             87,
            "fixed_length":    90,
            "automate":        89,
            "arm":             86,
            "play":            85,

            "mod_wheel":       12,

            # Right buttons
            "setup":           30, "user":           59,
            "add_device":      52, "device":        110, "mix":            112,
            "add_track":       53, "browse":        111, "clip":           113,

            "master":          28,
            "up":              46, "left":           44, "right":           45, "down":           47,

            "repeat_1/32t":    43, "repeat_1/32":    42, "repeat_1/16t":    41, "repeat_1/16":    40,  "repeat_1/8t":    39, "repeat_1/8":      38, "repeat_1/4t":      37, "repeat_1/4":    36,

            "repeat":          56, "accent":         57,
            "scale":           58, "layout":         31,
            "note":            50, "session":        51,
            "octave_up":       55, "page_left":      62, "page_right":      63, "octave_down":    54,
            "shift":           49,
            "select":          48,

            # Matrix
            "matrix_8_1":  128+92, "matrix_8_2": 128+93, "matrix_8_3":  128+94, "matrix_8_4": 128+95, "matrix_8_5":  128+96, "matrix_8_6":  128+97, "matrix_8_7":  128+98, "matrix_8_8": 128+99,
            "matrix_7_1":  128+84, "matrix_7_2": 128+85, "matrix_7_3":  128+86, "matrix_7_4": 128+87, "matrix_7_5":  128+88, "matrix_7_6":  128+89, "matrix_7_7":  128+90, "matrix_7_8": 128+91,
            "matrix_6_1":  128+76, "matrix_6_2": 128+77, "matrix_6_3":  128+78, "matrix_6_4": 128+79, "matrix_6_5":  128+80, "matrix_6_6":  128+81, "matrix_6_7":  128+82, "matrix_6_8": 128+83,
            "matrix_5_1":  128+68, "matrix_5_2": 128+69, "matrix_5_3":  128+70, "matrix_5_4": 128+71, "matrix_5_5":  128+72, "matrix_5_6":  128+73, "matrix_5_7":  128+74, "matrix_5_8": 128+75,
            "matrix_4_1":  128+60, "matrix_4_2": 128+61, "matrix_4_3":  128+62, "matrix_4_4": 128+63, "matrix_4_5":  128+64, "matrix_4_6":  128+65, "matrix_4_7":  128+66, "matrix_4_8": 128+67,
            "matrix_3_1":  128+52, "matrix_3_2": 128+53, "matrix_3_3":  128+54, "matrix_3_4": 128+55, "matrix_3_5":  128+56, "matrix_3_6":  128+57, "matrix_3_7":  128+58, "matrix_3_8": 128+59,
            "matrix_2_1":  128+44, "matrix_2_2": 128+45, "matrix_2_3":  128+46, "matrix_2_4": 128+47, "matrix_2_5":  128+48, "matrix_2_6":  128+49, "matrix_2_7":  128+50, "matrix_2_8": 128+51,
            "matrix_1_1":  128+36, "matrix_1_2": 128+37, "matrix_1_3":  128+38, "matrix_1_4": 128+39, "matrix_1_5":  128+40, "matrix_1_6":  128+41, "matrix_1_7":  128+42, "matrix_1_8": 128+43,

            # Foot Pedal
            "foot_pedal":      64
        }
        control_name_lookup = {}
        for short_name, value in controls_by_name.items():
            control_name_lookup[value] = short_name

        bw_controls_base = {
            # Left buttons
            "tap_tempo":        3, "metronome":       9,
            "delete":         118,
            "undo":           119,
            "convert":         35,
            "double_loop":    117,
            "quantize":       116,
            "duplicate":       88,
            "new":             87,
            "fixed_length":    90,

            # Right buttons
            "setup":           30, "user":           59,
            "add_device":      52, "device":        110, "mix":            112,
            "add_track":       53, "browse":        111, "clip":           113,

            "master":          28,
            "up":              46, "left":           44, "right":           45, "down":           47,

            "repeat":          56, "accent":         57,
            "scale":           58, "layout":         31,
            "note":            50, "session":        51,
            "octave_up":       55, "page_left":      62, "page_right":      63, "octave_down":    54,
            "shift":           49,
            "select":          48,
        }

        #bw_controls = []
        #for short_name, value in bw_led_data.items():
        #    bw_controls.append(value)
        bw_controls = list(bw_controls_base.values())

        # Short names (your API) -> official LOM control names.
        # Order matches your buttons_and_encoders table.

        lom_name_by_control_name = {
            # Encoders (3 special encoders)
            "tempo":           "Tempo_Control",
            "swing":           "Swing_Control",
            "master_encoder":  "Master_Volume_Control",

            "tempo_touch":     "Tempo_Control_Tap",
            "swing_touch":     "Swing_Control_Tap",
            "master_touch":    "Master_Volume_Tap",

            # Central unit
            "encoder_1":       "Track_Control_0",
            "encoder_2":       "Track_Control_1",
            "encoder_3":       "Track_Control_2",
            "encoder_4":       "Track_Control_3",
            "encoder_5":       "Track_Control_4",
            "encoder_6":       "Track_Control_5",
            "encoder_7":       "Track_Control_6",
            "encoder_8":       "Track_Control_7",

            "touch_1":         "Track_Control_Touch_0",
            "touch_2":         "Track_Control_Touch_1",
            "touch_3":         "Track_Control_Touch_2",
            "touch_4":         "Track_Control_Touch_3",
            "touch_5":         "Track_Control_Touch_4",
            "touch_6":         "Track_Control_Touch_5",
            "touch_7":         "Track_Control_Touch_6",
            "touch_8":         "Track_Control_Touch_7",

            # Your detail_x == LOM Track_State_Button_x
            "detail_1":        "Track_State_Button0",
            "detail_2":        "Track_State_Button1",
            "detail_3":        "Track_State_Button2",
            "detail_4":        "Track_State_Button3",
            "detail_5":        "Track_State_Button4",
            "detail_6":        "Track_State_Button5",
            "detail_7":        "Track_State_Button6",
            "detail_8":        "Track_State_Button7",

            # Track select row
            "track_1":         "Track_Select_Button0",
            "track_2":         "Track_Select_Button1",
            "track_3":         "Track_Select_Button2",
            "track_4":         "Track_Select_Button3",
            "track_5":         "Track_Select_Button4",
            "track_6":         "Track_Select_Button5",
            "track_7":         "Track_Select_Button6",
            "track_8":         "Track_Select_Button7",

            # Left buttons
            "tap_tempo":       "Tap_Tempo_Button",
            "metronome":       "Metronome_Button",

            "delete":          "Delete_Button",
            "undo":            "Undo_Button",

            "mute":            "Global_Mute_Button",
            "solo":            "Global_Solo_Button",
            "stop":            "Track_Stop_Button",

            "convert":         "Convert",
            "double_loop":     "Double_Button",
            "quantize":        "Quantization_Button",
            "duplicate":       "Duplicate_Button",
            "new":             "New_Button",
            "fixed_length":    "Fixed_Length_Button",
            "automate":        "Automation_Button",
            "arm":             "Record_Button",
            "play":            "Play_Button",

            # "mod_wheel" is your short name; LOM calls it Touch_Strip_Control.
            "mod_wheel":       "Touch_Strip_Control",

            # Right buttons
            "setup":           "Setup_Button",
            "user":            "User_Button",

            "add_device":      "Create_Device_Button",
            "device":          "Device_Mode_Button",
            "mix":             "Vol_Mix_Mode_Button",

            "add_track":       "Create_Track_Button",
            "browse":          "Browse_Mode_Button",
            "clip":            "Clip_Mode_Button",

            "master":          "Master_Select_Button",

            "up":              "Up_Arrow",
            "left":            "Left_Arrow",
            "right":           "Right_Arrow",
            "down":            "Down_Arrow",

            # Your repeat timing buttons map to Scene_Launch_Button0..7 in your order:
            # 1/32t -> 0 ... 1/4 -> 7
            "repeat_1/32t":    "Scene_Launch_Button0",
            "repeat_1/32":     "Scene_Launch_Button1",
            "repeat_1/16t":    "Scene_Launch_Button2",
            "repeat_1/16":     "Scene_Launch_Button3",
            "repeat_1/8t":     "Scene_Launch_Button4",
            "repeat_1/8":      "Scene_Launch_Button5",
            "repeat_1/4t":     "Scene_Launch_Button6",
            "repeat_1/4":      "Scene_Launch_Button7",

            "repeat":          "Repeat_Button",
            "accent":          "Accent_Button",
            "scale":           "Scale_Presets_Button",
            "layout":          "Layout",

            "note":            "Note_Mode_Button",
            "session":         "Session_Mode_Button",

            "octave_up":       "Octave_Up_Button",
            "page_left":       "Page_Left_Button",
            "page_right":      "Page_Right_Button",
            "octave_down":     "Octave_Down_Button",

            "shift":           "Shift_Button",
            "select":          "Select_Button",

            # Matrix (8x8) -> Clip grid buttons
            "matrix_8_1":      "0_Clip_7_Button",
            "matrix_8_2":      "1_Clip_7_Button",
            "matrix_8_3":      "2_Clip_7_Button",
            "matrix_8_4":      "3_Clip_7_Button",
            "matrix_8_5":      "4_Clip_7_Button",
            "matrix_8_6":      "5_Clip_7_Button",
            "matrix_8_7":      "6_Clip_7_Button",
            "matrix_8_8":      "7_Clip_7_Button",

            "matrix_7_1":      "0_Clip_6_Button",
            "matrix_7_2":      "1_Clip_6_Button",
            "matrix_7_3":      "2_Clip_6_Button",
            "matrix_7_4":      "3_Clip_6_Button",
            "matrix_7_5":      "4_Clip_6_Button",
            "matrix_7_6":      "5_Clip_6_Button",
            "matrix_7_7":      "6_Clip_6_Button",
            "matrix_7_8":      "7_Clip_6_Button",

            "matrix_6_1":      "0_Clip_5_Button",
            "matrix_6_2":      "1_Clip_5_Button",
            "matrix_6_3":      "2_Clip_5_Button",
            "matrix_6_4":      "3_Clip_5_Button",
            "matrix_6_5":      "4_Clip_5_Button",
            "matrix_6_6":      "5_Clip_5_Button",
            "matrix_6_7":      "6_Clip_5_Button",
            "matrix_6_8":      "7_Clip_5_Button",

            "matrix_5_1":      "0_Clip_4_Button",
            "matrix_5_2":      "1_Clip_4_Button",
            "matrix_5_3":      "2_Clip_4_Button",
            "matrix_5_4":      "3_Clip_4_Button",
            "matrix_5_5":      "4_Clip_4_Button",
            "matrix_5_6":      "5_Clip_4_Button",
            "matrix_5_7":      "6_Clip_4_Button",
            "matrix_5_8":      "7_Clip_4_Button",

            "matrix_4_1":      "0_Clip_3_Button",
            "matrix_4_2":      "1_Clip_3_Button",
            "matrix_4_3":      "2_Clip_3_Button",
            "matrix_4_4":      "3_Clip_3_Button",
            "matrix_4_5":      "4_Clip_3_Button",
            "matrix_4_6":      "5_Clip_3_Button",
            "matrix_4_7":      "6_Clip_3_Button",
            "matrix_4_8":      "7_Clip_3_Button",

            "matrix_3_1":      "0_Clip_2_Button",
            "matrix_3_2":      "1_Clip_2_Button",
            "matrix_3_3":      "2_Clip_2_Button",
            "matrix_3_4":      "3_Clip_2_Button",
            "matrix_3_5":      "4_Clip_2_Button",
            "matrix_3_6":      "5_Clip_2_Button",
            "matrix_3_7":      "6_Clip_2_Button",
            "matrix_3_8":      "7_Clip_2_Button",

            "matrix_2_1":      "0_Clip_1_Button",
            "matrix_2_2":      "1_Clip_1_Button",
            "matrix_2_3":      "2_Clip_1_Button",
            "matrix_2_4":      "3_Clip_1_Button",
            "matrix_2_5":      "4_Clip_1_Button",
            "matrix_2_6":      "5_Clip_1_Button",
            "matrix_2_7":      "6_Clip_1_Button",
            "matrix_2_8":      "7_Clip_1_Button",

            "matrix_1_1":      "0_Clip_0_Button",
            "matrix_1_2":      "1_Clip_0_Button",
            "matrix_1_3":      "2_Clip_0_Button",
            "matrix_1_4":      "3_Clip_0_Button",
            "matrix_1_5":      "4_Clip_0_Button",
            "matrix_1_6":      "5_Clip_0_Button",
            "matrix_1_7":      "6_Clip_0_Button",
            "matrix_1_8":      "7_Clip_0_Button",

            # Foot Pedal
            "foot_pedal":      "Foot_Pedal",
        }

        lom_name_lookup = {}
        controls_by_lom_name = {}

        for short_name, lom_name in lom_name_by_control_name.items():
            value = controls_by_name.get(short_name)
            lom_name_lookup[value] = lom_name
            controls_by_lom_name[lom_name] = value

        # Explicit unmapped list (same order as appended leftovers above).
        unused_lom_controls = [
            "Single_Track_Mode_Button",
            "Pan_Send_Mode_Button",

            "Track_Select_Buttons",
            "Track_State_Buttons",
            "Scene_Launch_Buttons",
            "Track_Control_Touches",
            "Track_Controls",

            "Button_Matrix",
            "Double_Press_Matrix",
            "Single_Press_Event_Matrix",
            "Double_Press_Event_Matrix",

            "Touch_Strip_Tap",
        ]

        midi_controls = {
            'controls_by_name': controls_by_name,
            'control_name_lookup': control_name_lookup,
            'controls_by_lom_name': controls_by_lom_name,
            'lom_name_lookup': lom_name_lookup,
            'lom_name_by_control_name': lom_name_by_control_name,
            'bw_controls': bw_controls,
            'unused_lom_controls': unused_lom_controls

        }

        return midi_controls


    """
    # All LOM controls in "your table order first":
    # 1) all LOM names used by SHORT_TO_LOM, in the same order as your short table
    # 2) then any leftovers (unmapped) appended.
    ALL_LOM_CONTROLS = [

        # Used by your table (same order as SHORT_TO_LOM above)
        "Tempo_Control", "Swing_Control", "Master_Volume_Control",
        "Tempo_Control_Tap", "Swing_Control_Tap", "Master_Volume_Tap",

        "Track_Control_0", "Track_Control_1", "Track_Control_2", "Track_Control_3",
        "Track_Control_4", "Track_Control_5", "Track_Control_6", "Track_Control_7",

        "Track_Control_Touch_0", "Track_Control_Touch_1", "Track_Control_Touch_2", "Track_Control_Touch_3",
        "Track_Control_Touch_4", "Track_Control_Touch_5", "Track_Control_Touch_6", "Track_Control_Touch_7",

        "Track_State_Button0", "Track_State_Button1", "Track_State_Button2", "Track_State_Button3",
        "Track_State_Button4", "Track_State_Button5", "Track_State_Button6", "Track_State_Button7",

        "Track_Select_Button0", "Track_Select_Button1", "Track_Select_Button2", "Track_Select_Button3",
        "Track_Select_Button4", "Track_Select_Button5", "Track_Select_Button6", "Track_Select_Button7",

        "Tap_Tempo_Button", "Metronome_Button",
        "Delete_Button", "Undo_Button",
        "Global_Mute_Button", "Global_Solo_Button", "Track_Stop_Button",

        "Convert", "Double_Button", "Quantization_Button", "Duplicate_Button", "New_Button",
        "Fixed_Length_Button", "Automation_Button", "Record_Button", "Play_Button",

        "Touch_Strip_Control",

        "Setup_Button", "User_Button",
        "Create_Device_Button", "Device_Mode_Button", "Vol_Mix_Mode_Button",
        "Create_Track_Button", "Browse_Mode_Button", "Clip_Mode_Button",

        "Master_Select_Button",
        "Up_Arrow", "Left_Arrow", "Right_Arrow", "Down_Arrow",

        "Scene_Launch_Button0", "Scene_Launch_Button1", "Scene_Launch_Button2", "Scene_Launch_Button3",
        "Scene_Launch_Button4", "Scene_Launch_Button5", "Scene_Launch_Button6", "Scene_Launch_Button7",

        "Repeat_Button", "Accent_Button", "Scale_Presets_Button", "Layout",
        "Note_Mode_Button", "Session_Mode_Button",

        "Octave_Up_Button", "Page_Left_Button", "Page_Right_Button", "Octave_Down_Button",
        "Shift_Button", "Select_Button",

        "0_Clip_7_Button", "1_Clip_7_Button", "2_Clip_7_Button", "3_Clip_7_Button",
        "4_Clip_7_Button", "5_Clip_7_Button", "6_Clip_7_Button", "7_Clip_7_Button",

        "0_Clip_6_Button", "1_Clip_6_Button", "2_Clip_6_Button", "3_Clip_6_Button",
        "4_Clip_6_Button", "5_Clip_6_Button", "6_Clip_6_Button", "7_Clip_6_Button",

        "0_Clip_5_Button", "1_Clip_5_Button", "2_Clip_5_Button", "3_Clip_5_Button",
        "4_Clip_5_Button", "5_Clip_5_Button", "6_Clip_5_Button", "7_Clip_5_Button",

        "0_Clip_4_Button", "1_Clip_4_Button", "2_Clip_4_Button", "3_Clip_4_Button",
        "4_Clip_4_Button", "5_Clip_4_Button", "6_Clip_4_Button", "7_Clip_4_Button",

        "0_Clip_3_Button", "1_Clip_3_Button", "2_Clip_3_Button", "3_Clip_3_Button",
        "4_Clip_3_Button", "5_Clip_3_Button", "6_Clip_3_Button", "7_Clip_3_Button",

        "0_Clip_2_Button", "1_Clip_2_Button", "2_Clip_2_Button", "3_Clip_2_Button",
        "4_Clip_2_Button", "5_Clip_2_Button", "6_Clip_2_Button", "7_Clip_2_Button",

        "0_Clip_1_Button", "1_Clip_1_Button", "2_Clip_1_Button", "3_Clip_1_Button",
        "4_Clip_1_Button", "5_Clip_1_Button", "6_Clip_1_Button", "7_Clip_1_Button",

        "0_Clip_0_Button", "1_Clip_0_Button", "2_Clip_0_Button", "3_Clip_0_Button",
        "4_Clip_0_Button", "5_Clip_0_Button", "6_Clip_0_Button", "7_Clip_0_Button",

        "Foot_Pedal",

        # Leftovers (not present in your short table)
        "Single_Track_Mode_Button",
        "Pan_Send_Mode_Button",

        # Group / container controls (not individual hardware)
        "Track_Select_Buttons",
        "Track_State_Buttons",
        "Scene_Launch_Buttons",
        "Track_Control_Touches",
        "Track_Controls",

        # Matrix meta-events
        "Button_Matrix",
        "Double_Press_Matrix",
        "Single_Press_Event_Matrix",
        "Double_Press_Event_Matrix",

        # Touch strip touch (not in your short table as separate key)
        "Touch_Strip_Tap",
    ]
    """
