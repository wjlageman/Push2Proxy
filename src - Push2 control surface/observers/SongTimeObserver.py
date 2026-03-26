# Push2/observers/SongTimeObserver.py
#
# Minimal observer for song.current_song_time.
# Provides a high-rate main-thread tick source while Live is playing.
#
# - Attaches a SubjectSlot listener to song.current_song_time.
# - On each event it calls io.tick().
# - Exceptions are reported via io.send("error", ...).

from __future__ import annotations

from typing import Any, Optional

from _Framework.SubjectSlot import SlotManager, SubjectSlotError, subject_slot


def _has_listener_api(subject: Any, prop: str) -> bool:
    try:
        return (
            callable(getattr(subject, "add_%s_listener" % prop, None)) and
            callable(getattr(subject, "remove_%s_listener" % prop, None))
        )
    except Exception:
        return False


class SongTimeObserver(SlotManager):
    """
    Observe song.current_song_time and call io.tick() on each update.
    """

    def __init__(self, proxy: Any, io: Any) -> None:
        super(SongTimeObserver, self).__init__()

        self._proxy = proxy
        self._io = io
        self._song = None

    def attach(self, song: Any) -> None:
        """
        Attach to the given Song object.
        """
        self.detach()

        self._song = song
        if song is None:
            self._io.send('error', 'SongTimeObserver: no song')
            return

        if _has_listener_api(song, "current_song_time"):
            self._set_subject_safe(self._on_song_time, song)
        else:
            self._io.send("error", "SongTimeObserver: song has no current_song_time listener API")

    def detach(self) -> None:
        """
        Detach from the current Song object.
        """
        self._set_subject_safe(self._on_song_time, None)
        self._song = None

    def disconnect(self) -> None:
        self.detach()
        self._io = None

    def _set_subject_safe(self, slot_obj: Any, subject: Any) -> None:
        try:
            slot_obj.subject = subject
        except SubjectSlotError:
            # Unsupported property on this Live build/object.
            pass
        except Exception as ex:
            try:
                if self._io is not None:
                    self._io.send("error", "SongTimeObserver: set_subject failed", str(ex))
            except Exception:
                pass

    @subject_slot("current_song_time")
    def _on_song_time(self) -> None:
        try:
            io = self._io
            if io is not None:
                #io.send('debug', 'SongTime tick')
                io.tick()
        except Exception as ex:
            try:
                if self._io is not None:
                    self._io.send("error", "SongTimeObserver: io.tick failed", str(ex))
            except Exception:
                pass
