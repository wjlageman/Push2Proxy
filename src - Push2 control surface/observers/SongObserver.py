# Push2/observers/SongObserver.py
#
# Minimal observer for Song.view selection changes.
#
# Responsibilities:
# - Attach listeners on Song.view for:
#     - selected_track
#     - appointed_device
# - Forward changes to ModuleManager:
#     - emit_track_change(track)
#     - emit_device_change(device)
#
# Non-responsibilities:
# - No Data cache writes here.
# - No UDP/Max output here.
# - No policy decisions (modules decide what to do with the objects).
#
# Notes:
# - Listener APIs can differ across Live builds; missing listener methods are reported
#   but do not crash the host.
# - Double-add is prevented per (object id, add_method, callback name).

from __future__ import annotations

import json
import time
import traceback
from typing import Any, Set, Tuple


_inst = None

import json
import time


def handle_liveset(cmd, *args):
    song = _inst._song
    t0_total = time.perf_counter()

    _inst._io.send('debug', 'IN SONGOBSERVER LIVESET', repr(song))

    # 1) tracks
    t0 = time.perf_counter()
    tracks = _get_tracks(song)
    #_send_liveset_json('tracks', tracks)
    #    payload = json.dumps(obj)
    _inst._io.send('json', 'liveset', 'tracks', json.dumps(tracks))
    _inst._io.send('debug', 'Timing', 'get_tracks + send(tracks)', t0)

    # 2) clips per zichtbare track (alleen type == track)
    t0_clips_all = time.perf_counter()
    for track_obj in tracks:
        if track_obj.get('type') == 'track':
            t0_clip = time.perf_counter()
            clips_payload = _get_clips_payload(song, track_obj['index'], track_obj['visible_track_index'])
            _inst._io.send('json', 'liveset', 'clips', clips_payload)
            _inst._io.send('debug', 'Timing', 
                'get_clips(track_index=%s, visible_track_index=%s) + send(clips)' % (
                    track_obj['index'],
                    track_obj['visible_track_index']
                ),
                t0_clip
            )
    _inst._io.send('debug', 'Timing', 'all clips total', t0_clips_all)

    # 3) return_tracks
    t0 = time.perf_counter()
    return_tracks = _get_return_tracks(song)
    _inst._io.send('json', 'liveset', 'return_tracks', json.dumps(return_tracks))
    _inst._io.send('debug', 'Timing', 'get_return_tracks + send(return_tracks)', t0)

    # 4) scenes
    t0 = time.perf_counter()
    scenes_payload = _get_scenes(song)
    _inst._io.send('json', 'liveset', 'scenes', scenes_payload)
    _inst._io.send('debug', 'Timing', 'get_scenes + send(scenes)', t0)

    _inst._io.send('debug', 'Timing', 'TOTAL handle_liveset', t0_total)


# ----------------------------
# Helpers
# ----------------------------

def _safe_name(obj):
    try:
        return obj.name
    except Exception:
        return ''


def _safe_color_index(obj):
    try:
        return int(obj.color_index)
    except Exception:
        return 0


def _is_showing_chains(obj):
    """
    In Max LOM gebruik je is_showing_chains.
    In Python Remote Script API kan dit per object/Live-versie verschillen.
    Daarom defensief:
    - direct obj.is_showing_chains
    - of obj.view.is_showing_chains
    Anders: False
    """
    try:
        value = getattr(obj, 'is_showing_chains', None)
        if value is not None:
            return bool(value)
    except Exception:
        pass

    try:
        view = getattr(obj, 'view', None)
        if view is not None:
            value = getattr(view, 'is_showing_chains', None)
            if value is not None:
                return bool(value)
    except Exception:
        pass

    return False


def _can_have_chains(device):
    try:
        return bool(device.can_have_chains)
    except Exception:
        return False


# ----------------------------
# Tracks / chains
# ----------------------------

def _get_tracks(song):
    tracks = []
    index = 0

    visible_tracks = list(getattr(song, 'visible_tracks', []))

    for visible_track_index, track in enumerate(visible_tracks):
        obj = {
            'index': index,
            'type': 'track',
            'visible_track_index': visible_track_index,
            'name': _safe_name(track),
            'color': _safe_color_index(track),
        }
        tracks.append(obj)
        index += 1

        if _is_showing_chains(track):
            index = _get_chains(track, tracks, index)

    return tracks


def _get_chains(parent, tracks, index, indent=''):
    """
    Zelfde recursieve structuur als je Max V8-code.
    We lopen door devices; als een device chains heeft en die zichtbaar zijn,
    voegen we de chains toe en recursen we verder op die chain.
    """
    devices = list(getattr(parent, 'devices', []))

    for device in devices:
        if not _can_have_chains(device):
            continue

        if not _is_showing_chains(device):
            continue

        chains = list(getattr(device, 'chains', []))
        for chain in chains:
            obj = {
                'index': index,
                'type': 'chain',
                'name': _safe_name(chain),
                'color': _safe_color_index(chain),
            }
            tracks.append(obj)
            index += 1

            index = _get_chains(chain, tracks, index, indent + '    ')

    return index


# ----------------------------
# Clips
# ----------------------------

def _get_clips_payload(song, index, visible_track_index):
    clips = []

    visible_tracks = list(getattr(song, 'visible_tracks', []))
    if visible_track_index < 0 or visible_track_index >= len(visible_tracks):
        return {
            'index': index,
            'clips': clips
        }

    track = visible_tracks[visible_track_index]
    clip_slots = list(getattr(track, 'clip_slots', []))

    for slot in clip_slots:
        clip_obj = None

        try:
            has_clip = bool(slot.has_clip)
        except Exception:
            has_clip = False

        if has_clip:
            try:
                clip = slot.clip
                clip_obj = {
                    'name': _safe_name(clip),
                    'color': _safe_color_index(clip),
                }
            except Exception:
                clip_obj = None

        clips.append(clip_obj)

    return {
        'index': index,
        'clips': clips
    }


# ----------------------------
# Return tracks / scenes
# ----------------------------

def _get_return_tracks(song):
    tracks = []

    return_tracks = list(getattr(song, 'return_tracks', []))
    for i, track in enumerate(return_tracks):
        obj = {
            'index': i,
            'type': 'return_track',
            'name': _safe_name(track),
            'color': _safe_color_index(track),
        }
        tracks.append(obj)

    return tracks


def _get_scenes(song):
    scenes = list(getattr(song, 'scenes', []))
    return {
        'count': len(scenes)
    }


class SongObserver(object):
    def __init__(self, env: Any, module_manager: Any, io: Any) -> None:
        self._env = env
        self._module_manager = module_manager
        self._io = io

        self._attached = False
        self._view = None

        # Prevent double-add (same obj + method + cbname)
        self._added: Set[Tuple[int, str, str]] = set()

    def attach(self, song: Any, view: Any) -> None:
        if self._attached:
            self._io.send('debug', 'SongObserver', 'attach skipped (already attached)')
            return

        try:
            global _inst
            self._song = song
            self._view = view

            # Soft attach: missing listener methods are reported but not fatal.
            #self._add(self._view, "add_selected_track_listener", self._on_selected_track)
            #self._add(self._view, "add_appointed_device_listener", self._on_appointed_device)

            self._attached = True
            _inst = self

        except Exception:
            self._io.send('error', "SongObserver attach failed:\n" + traceback.format_exc())
            raise

        # Baseline emit (no cache responsibility here)
        self._on_selected_track()
        self._on_appointed_device()

    def _add(self, obj: Any, add_name: str, cb: Any) -> None:
        try:
            add = getattr(obj, add_name, None)
            if not callable(add):
                self._io.send('log', 'Warning: SongObserver is missing', add_name, 'on', type(obj).__name__)
                return

            key = (id(obj), add_name, getattr(cb, "__name__", "cb"))
            if key in self._added:
                self._io.send('debug', 'SongObserver', 'already added', add_name, getattr(cb, "__name__", "cb"))
                return

            add(cb)
            self._added.add(key)

        except Exception:
            self._io.send('error', 'SongObserver safe_add failed:\n' + traceback.format_exc())

    def _on_selected_track(self) -> None:
        try:
            track = getattr(self._view, "selected_track", None) if self._view is not None else None
            self._module_manager.emit_track_change(track)
        except Exception:
            self._io.send("error", 'CALLBACK', "SongObserver _on_selected_track error:\n" + traceback.format_exc())

    def _on_appointed_device(self) -> None:
        try:
            dev = getattr(self._view, "appointed_device", None) if self._view is not None else None
            self._module_manager.emit_device_change(dev)
        except Exception:
            self._io.send("error", 'CALLBACK', "SongObserver _on_appointed_device error:\n" + traceback.format_exc())
