# Push2/observers/RedringObserver.py
#
# Observer that reads and optionally moves Ableton's Session Ring ("redring").
#
# Emits JSON via Data.upsert + Data.emit_json.
#
# Frame state (preferred for Max UI / performance):
#   emit_frame() sends a burst of small messages:
#       - redring::redring        (array)   [track_offset, scene_offset, width, height]
#       - redring::clips          (dict)    {track_offset, scene_offset, width, height, track_count, scene_count, return_track_count}
#       - redring::tracks::<x>    (short dict) 8 items
#       - redring::scenes::<y>    (short dict) 8 items
#       - redring::grid::<y>::<x> (cell dict) 64 items
#
# IMPORTANT NOTES:
# - x/y in all payloads are RELATIVE (0..7).
# - track_index/scene_index are ABSOLUTE.
# - For emit_frame(), we always emit 8x8, including empty rows/cols beyond track/scene counts.
#
# This version intentionally contains NO SubjectSlot observers/listeners.
# We run purely in "poll + frame emit" mode.
#
# NOTE:
# - Booleans are encoded as 0/1 for Max.

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import time

from ..utils import fmt_exc


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _b01(v: Any) -> int:
    try:
        return 1 if bool(v) else 0
    except Exception:
        return 0


def _safe_str(v: Any, default: str = "") -> str:
    try:
        if v is None:
            return default
        return str(v)
    except Exception:
        return default


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


class Redring(object):
    def __init__(self, host: Any) -> None:
        self._host = host

    def locate(self) -> Tuple[Optional[Any], str, str]:
        h = self._host
        if not h:
            return (None, "<none>", "<none>")

        try:
            ring = getattr(h, "_session_ring", None)
            if ring is not None:
                return (ring, "_session_ring", type(ring).__name__)
        except Exception:
            pass

        candidates = [
            ("_session_ring", "_session_ring"),
            ("session_ring", "session_ring"),
            ("session_ring_component", "session_ring_component"),
            ("session_ring_object", "session_ring_object"),
            ("session_ring_component._session_ring", "session_ring_component._session_ring"),
        ]

        for label, path in candidates:
            try:
                obj = h
                ok = True
                for part in path.split("."):
                    obj = getattr(obj, part, None)
                    if obj is None:
                        ok = False
                        break
                if ok and obj is not None:
                    return (obj, path, type(obj).__name__)
            except Exception:
                continue

        return (None, "<none>", "<none>")

    def read_atoms(self) -> Optional[List[int]]:
        ring, owner_attr, owner_type = self.locate()
        if ring is None:
            return None

        def _get(obj: Any, names, default=0) -> int:
            for nm in names:
                try:
                    val = getattr(obj, nm, None)
                    if val is None:
                        continue
                    if callable(val):
                        val = val()
                    return int(val)
                except Exception:
                    continue
            return int(default)

        atoms: List[int] = []
        atoms.append(_get(ring, ["track_offset", "_track_offset", "track_offset_value"]))
        atoms.append(_get(ring, ["scene_offset", "_scene_offset", "scene_offset_value"]))
        atoms.append(_get(ring, ["width", "num_tracks", "_num_tracks"], default=8))
        atoms.append(_get(ring, ["height", "num_scenes", "_num_scenes"], default=8))
        return atoms

    def set_offsets(self, track_offset: int, scene_offset: int) -> bool:
        t = int(track_offset)
        s = int(scene_offset)

        ring, owner_attr, owner_type = self.locate()
        if ring is None:
            return False

        try:
            fn = getattr(ring, "set_offsets", None)
            if callable(fn):
                fn(t, s)
                return True
        except Exception:
            pass

        ok_any = False

        try:
            fn = getattr(ring, "set_track_offset", None)
            if callable(fn):
                fn(t)
                ok_any = True
        except Exception:
            pass

        try:
            fn = getattr(ring, "set_scene_offset", None)
            if callable(fn):
                fn(s)
                ok_any = True
        except Exception:
            pass

        if ok_any:
            return True

        attr_ok = False

        try:
            if hasattr(ring, "track_offset"):
                ring.track_offset = t
                attr_ok = True
            elif hasattr(ring, "_track_offset"):
                ring._track_offset = t
                attr_ok = True
        except Exception:
            pass

        try:
            if hasattr(ring, "scene_offset"):
                ring.scene_offset = s
                attr_ok = True
            elif hasattr(ring, "_scene_offset"):
                ring._scene_offset = s
                attr_ok = True
        except Exception:
            pass

        return bool(attr_ok)


class RedringObserver(object):
    _instance = None
    _redraw_time = 0.0

    @staticmethod
    def start(host: Any, module_manager: Any, io: Any) -> "RedringObserver":
        """
        Start (or rewire) the singleton observer with its required dependencies.
        Host is injected explicitly to avoid proxy/router lookups.
        """
        inst = RedringObserver._instance
        if inst is None:
            inst = RedringObserver()
            RedringObserver._instance = inst

        inst._host = host
        inst._module_manager = module_manager
        inst._io = io

        if host is None:
            inst._io.send("error", "RedringObserver: start(host= None)")

        return inst

    """
    @staticmethod
    def emit_state() -> None:
        inst = RedringObserver._instance
        if inst is None:
            return

        try:
            start_time = time.time()

            host = getattr(inst, "_host", None)
            if host is None:
                inst._io.send("error", "RedringObserver: host is None (emit_state)")
                return

            redring = Redring(host)

            atoms = redring.read_atoms()
            if not atoms or len(atoms) < 4:
                atoms = [0, 0, 8, 8]

            track_offset = _safe_int(atoms[0], 0)
            scene_offset = _safe_int(atoms[1], 0)
            width = _safe_int(atoms[2], 8)
            height = _safe_int(atoms[3], 8)

            tracks_d, scenes_d, grid_d, track_count, scene_count, return_track_count = RedringObserver._build_tracks_scenes_grid(
                host=host,
                track_offset=track_offset,
                scene_offset=scene_offset,
                width=width,
                height=height
            )

            from ..Data import upsert, emit_json

            payload = {
                "redring": [track_offset, scene_offset, width, height],
                "clips": {
                    "track_offset": int(track_offset),
                    "scene_offset": int(scene_offset),
                    "width": int(width),
                    "height": int(height),
                    "track_count": int(track_count),
                    "scene_count": int(scene_count),
                    "return_track_count": int(return_track_count),
                },
                "tracks": tracks_d,
                "scenes": scenes_d,
                "grid": grid_d,
            }

            build_ms = int((time.time() - start_time) * 1000.0)

            upsert("redring", payload)
            emit_json("redring")

            total_ms = int((time.time() - start_time) * 1000.0)

            inst._io.send(
                "debug",
                "REDRING emit_state",
                "build_ms",
                build_ms,
                "total_ms",
                total_ms,
                "track_count",
                int(track_count),
                "return_track_count",
                int(return_track_count),
                "scene_count",
                int(scene_count),
            )

        except Exception as ex:
            inst._io.send("error", fmt_exc("redring.emit_state failed", ex))
    """

    @staticmethod
    def redraw_frame(now: bool = False) -> None:
        if now or time.time() >= RedringObserver._redraw_time:
            RedringObserver.emit_frame()
            RedringObserver._redraw_time = time.time() + 0.020

    @staticmethod
    def emit_frame() -> None:
        inst = RedringObserver._instance
        if inst is None:
            return

        from ..Data import upsert, emit_json
        try:
            host = getattr(inst, "_host", None)
            if host is None:
                inst._io.send("error", "RedringObserver: host is None (emit_frame)")
                return

            redring = Redring(host)

            atoms = redring.read_atoms()
            if not atoms or len(atoms) < 4:
                atoms = [0, 0, 8, 8]

            track_offset = _safe_int(atoms[0], 0)
            scene_offset = _safe_int(atoms[1], 0)

            width = _safe_int(atoms[2], 8)
            height = _safe_int(atoms[3], 8)

            if upsert("redring", "redring", atoms):
                emit_json("redring", "redring")

            # Get the song object
            song = None
            try:
                song = getattr(host, "song", None)
                if callable(song):
                    song = song()
            except Exception:
                song = None

            if song is None:
                return ({}, {}, {}, 0, 0, 0)

            # Get the tracks
            tracks = list(getattr(song, "tracks", []) or [])
            try:
                track_count = len(tracks)
            except Exception:
                track_count = 0
            track_lookup = {}
            track_index = 0
            for track in tracks:
                track_lookup[getattr(track, "name", "<no_name>")] = {'index': track_index, 'clip_slots': getattr(track, "clip_slots", None)}
                track_index += 1

            # get the return_tracks
            return_tracks = list(getattr(song, "return_tracks", []) or [])
            try:
                return_track_count = len(return_tracks)
            except Exception:
                return_track_count = 0
            return_track_lookup = {}
            return_track_index = 0
            for return_track in return_tracks:
                return_track_lookup[getattr(return_track, "name", "<no_name>")] = {'index': return_track_index}
                return_track_index += 1

            # get the scenes
            scenes = list(getattr(song, "scenes", []) or [])
            try:
                scene_count = len(scenes)
            except Exception:
                scene_count = 0

            # Send meta data
            clips_meta = {
                "track_offset": int(track_offset),
                "scene_offset": int(scene_offset),
                "width": int(width),
                "height": int(height),
                "track_count": int(track_count),
                #"visible_track_count": int(visible_track_count),
                "scene_count": int(scene_count),
                "return_track_count": int(return_track_count),
            }
            if upsert("redring", "clips", clips_meta):
                emit_json("redring", "clips")

            # Show the scenes
            for y_rel in range(0, height):
                scene_index = int(y_rel + scene_offset)
                if scene_index < len(scenes):
                    scene = RedringObserver._scene_info(scenes[scene_index], y_rel, scene_index)
                    scene_info = RedringObserver._scene_info_short(y_rel, scene)
                else:
                    scene_info = {
                        "y": int(y_rel),
                        "scene_index": -1,
                        "name": "",
                        "color_index": -1
                    }

                if upsert("redring", "scenes", y_rel, scene_info):
                    emit_json("redring", "scenes", y_rel)

            # Get the redring
            redring_tracks = RedringObserver._get_redring_tracks()
            if not isinstance(redring_tracks, list) or len(redring_tracks) != 8:
                inst._io.send('debug', 'Redring tracks are missing or length != 8', redring_tracks)
                redring_tracks = [None, None, None, None, None, None, None, None]

            # draw the tracks
            for x_rel in range(0, width):
                #inst._io.send('debug', 'REDRING_JSON', 'X_REL', x_rel)
                track = redring_tracks[x_rel]

                clip_slots = None
                if track != None:
                    track_info = RedringObserver._track_info_from_tracklist_item(track, x_rel)
                    name = track_info.get('name', '<no_name>')
                    nesting_level = track.get('nesting_level', -1)
                    if nesting_level == 0:
                        if track.get('is_return', 0):
                            track_info['type'] = 'return_track'
                            track_info['index'] = return_track_lookup[name]['index']
                        elif track.get('is_master', 0):
                            track_info['type'] = 'master_track'
                        else:
                            track_info["type"] = 'track'
                            track_index = track_lookup[name]["index"]
                            track_info["index"] = track_index
                            clip_slots = track_lookup[name]["clip_slots"]
                    else:
                        track_info['type'] = 'chain'
                else:
                    track_info = {
                        "x": int(x_rel),
                        "name": "",
                        "color_index": -1
                    }
                    track_info['type'] = 'empty'

                if upsert("redring", "tracks", x_rel, track_info):
                    emit_json("redring", "tracks", x_rel)


                for y_rel in range(0, 8):
                    if clip_slots != None and y_rel + scene_offset < len(clip_slots):
                        # Normal track with clip_slot and maybe a clip
                        clip_slot = clip_slots[scene_offset + y_rel]
                        cell = RedringObserver._slot_cell(clip_slot, x_rel, y_rel, track_index, scene_offset + y_rel)
                    else:
                        # empty clip_slot
                        cell = RedringObserver._empty_cell(int(x_rel), int(y_rel), -1, -1)

                    if upsert("redring", "grid", str(y_rel), str(x_rel), cell):
                        emit_json("redring", "grid", str(y_rel), str(x_rel))

        except Exception as ex:
            inst._io.send("error", fmt_exc("redring.emit_frame failed", ex))

    """
    @staticmethod
    def dump_track(track):
        data = {}
        for name in dir(track):
            if name.startswith("_"):
                continue
            try:
                value = getattr(track, name)
            except Exception:
                continue
            if callable(value):
                data[name] = value
                continue
            data[name] = value
        return data
    """


    @staticmethod
    def move_redring(track_offset: int, scene_offset: int) -> None:
        inst = RedringObserver._instance
        if inst is None:
            return

        try:
            host = getattr(inst, "_host", None)
            if host is None:
                inst._io.send("error", "RedringObserver: host is None (move_redring)")
                return

            inst._io.send("debug", "REDRING", "MOVE_REDRING", track_offset, scene_offset)
            Redring(host).set_offsets(track_offset, scene_offset)
            RedringObserver.redraw_frame(True)

        except Exception as ex:
            inst._io.send("error", fmt_exc("redring.move_and_emit failed", ex))


    @staticmethod
    def _get_redring_tracks() -> Optional[List[Any]]:
        try:
            from ..Data import select
            tracks = select(["tracks"])
            if isinstance(tracks, dict):
                arr = tracks.get("tracks", None)
                if isinstance(arr, list):
                    return arr
        except Exception:
            pass
        return None
        

    @staticmethod
    def _track_info_from_tracklist_item(item: Dict[str, Any], x: int) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "x": int(x),
            "name": _safe_str(item.get("name", "")),
        }

        info["activated"] = _b01(item.get("activated", True))
        info["arm"] = _b01(item.get("arm", False))
        info["mute"] = _b01(item.get("mute", False))
        info["solo"] = _b01(item.get("solo", False))

        info["is_foldable"] = _b01(item.get("is_foldable", False))
        info["is_frozen"] = _b01(item.get("is_frozen", False))
        info["color_index"] = _safe_int(item.get("color_index", -1), -1)

        info["is_audio"] = _b01(item.get("is_audio", False))
        info["is_return"] = _b01(item.get("is_return", False))
        info["is_master"] = _b01(item.get("is_master", False))

        info["nesting_level"] = _safe_int(item.get("nesting_level", 0), 0)

        try:
            out_r = item.get("output_routing", None)
            info["output_routing"] = _safe_str(out_r, "")
        except Exception:
            info["output_routing"] = ""

        return info


    @staticmethod
    def _scene_info(scene: Any, rel_index: int, abs_index: int) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "y": int(rel_index),
            "scene_index": int(abs_index),
            "name": _safe_str(_get_attr(scene, "name", "")),
        }

        info["color_index"] = _safe_int(_get_attr(scene, "color_index", -1), -1)

        tempo = _get_attr(scene, "tempo", None)
        if tempo is not None:
            try:
                info["tempo"] = float(tempo)
            except Exception:
                pass

        sig_num = _get_attr(scene, "signature_numerator", None)
        sig_den = _get_attr(scene, "signature_denominator", None)
        if sig_num is not None and sig_den is not None:
            info["signature_numerator"] = _safe_int(sig_num, 4)
            info["signature_denominator"] = _safe_int(sig_den, 4)

        return info

    @staticmethod
    def _track_info_short(x_rel, track_info_full: Dict[str, Any]) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        d["x"] = int(x_rel)
        d["track_index"] = _safe_int(track_info_full.get("track_index", 0), 0)
        d["name"] = _safe_str(track_info_full.get("name", ""), "")
        d["color_index"] = _safe_int(track_info_full.get("color_index", -1), -1)
        d["activated"] = _safe_int(track_info_full.get("activated", 1), 1)
        d["arm"] = _safe_int(track_info_full.get("arm", 0), 0)
        d["mute"] = _safe_int(track_info_full.get("mute", 0), 0)
        d["solo"] = _safe_int(track_info_full.get("solo", 0), 0)
        return d

    @staticmethod
    def _scene_info_short(y_rel, scene_info_full: Dict[str, Any]) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        d["y"] = int(y_rel)
        d["scene_index"] = _safe_int(scene_info_full.get("scene_index", 0), 0)
        d["name"] = _safe_str(scene_info_full.get("name", ""), "")
        d["color_index"] = _safe_int(scene_info_full.get("color_index", -1), -1)
        tempo = scene_info_full.get("tempo", None)
        if tempo is not None:
            try:
                d["tempo"] = float(tempo)
            except Exception:
                pass
        return d

    @staticmethod
    def _empty_cell(x: int, y: int, track_index: int, scene_index: int) -> Dict[str, Any]:
        # IMPORTANT:
        # - name is the CLIP name (not track name)
        # - for "no clip" cells: name MUST be ""
        cell: Dict[str, Any] = {
            "x": int(x),
            "y": int(y),
            "track_index": int(track_index),
            "scene_index": int(scene_index),
            "is_triggered": 0,
            "is_playing": 0,
            "has_stop_button": 0,
            "is_present": 0,
            "name": "",
            "color_index": -1
        }
        return cell

    @staticmethod
    def _slot_cell(slot: Any, x: int, y: int, track_index: int, scene_index: int) -> Dict[str, Any]:
        cell: Dict[str, Any] = {
            "x": int(x),
            "y": int(y),
            "track_index": int(track_index),
            "scene_index": int(scene_index),
        }

        # Hebben we dit nodig?
        """
        try:
            if _b01(_get_attr(track, "is_return_track", 0)) or _b01(_get_attr(track, "is_master_track", 0)):
                cell["is_triggered"] = 0
                cell["is_playing"] = 0
                cell["has_stop_button"] = 0
                cell["is_present"] = 0
                cell["name"] = ""
                cell["color_index"] = -1
                cell["is_triggered"] = 0
                cell["is_playing"] = 0
                return cell
        except Exception:
            pass
        """

        """
        slot = None
        try:
            slots = getattr(track, "clip_slots", None)
            if slots is not None:
                if scene_index >= 0 and scene_index < len(slots):
                    slot = slots[scene_index]
        except Exception:
            slot = None

        if slot is None:
            cell["is_triggered"] = 0
            cell["is_playing"] = 0
            cell["has_stop_button"] = 0
            cell["is_present"] = 0
            cell["name"] = ""
            cell["color_index"] = -1
            cell["is_triggered"] = 0
            cell["is_playing"] = 0
            return cell

        """

        cell["is_triggered"] = _b01(_get_attr(slot, "is_triggered", 0))
        cell["is_playing"] = _b01(_get_attr(slot, "is_playing", 0))
        cell["has_stop_button"] = _b01(_get_attr(slot, "has_stop_button", 0))

        clip = None
        try:
            clip = getattr(slot, "clip", None)
        except Exception:
            clip = None

        if clip is None:
            cell["is_present"] = 0
            cell["name"] = ""
            cell["color_index"] = -1
            cell["is_triggered"] = 1 if int(cell["is_triggered"]) else 0
            cell["is_playing"] = 1 if int(cell["is_playing"]) else 0
            return cell

        cell["is_present"] = 1
        cell["name"] = _safe_str(_get_attr(clip, "name", ""))
        cell["color_index"] = _safe_int(_get_attr(clip, "color_index", -1), -1)
        cell["is_recording"] = _b01(_get_attr(clip, "is_recording", 0))
        cell["is_audio"] = _b01(_get_attr(clip, "is_audio_clip", 0))

        cell["loop_start"] = _get_attr(clip, "loop_start", None)
        cell["loop_end"] = _get_attr(clip, "loop_end", None)

        w = _get_attr(clip, "warping", None)
        if w is not None:
            cell["warping"] = _b01(w)

        sn = _get_attr(clip, "signature_numerator", None)
        sd = _get_attr(clip, "signature_denominator", None)
        if sn is not None and sd is not None:
            cell["signature_numerator"] = _safe_int(sn, 4)
            cell["signature_denominator"] = _safe_int(sd, 4)

        pos = _get_attr(clip, "positions", None)
        if pos is not None:
            cell["positions"] = pos
        else:
            cell["positions"] = None

        return cell