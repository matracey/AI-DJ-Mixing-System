"""Read artist/title metadata from audio files, with filename fallback.

Exposes read_artist_title(path) -> (artist, title). Never raises: on any
failure it falls back to ("Unknown", filename_stem).
"""

import os
import re


def read_artist_title(path):
    """Return (artist, title) for an audio file.

    Tries audio tags via mutagen first, then falls back to parsing the
    filename. Always returns a tuple and never raises.
    """
    filename = os.path.basename(path)
    stem = os.path.splitext(filename)[0]

    try:
        import mutagen
        audio = mutagen.File(path, easy=True)
        if audio is not None:
            artist = audio.get("artist", [None])[0]
            title = audio.get("title", [None])[0]
            if artist and title:
                return (artist, title)
    except Exception:
        pass

    try:
        name = stem
        # Strip a leading "[...]" bracket group (e.g. "[iSongs.info] ...")
        name = re.sub(r"^\s*\[[^\]]*\]\s*", "", name)
        # Strip leading track numbers like "01 - ", "1. ", "03 "
        name = re.sub(r"^\d+\s*[-.\s]+", "", name)
        name = name.strip()

        parts = name.split(" - ", 1)
        if len(parts) == 2:
            return (parts[0].strip(), parts[1].strip())
        return ("Unknown", name)
    except Exception:
        return ("Unknown", stem)
