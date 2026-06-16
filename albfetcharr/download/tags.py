"""Audio file tag cleanup."""

import sys
from pathlib import Path

from mutagen import File as MutagenFile

from .locator import AUDIO_EXTENSIONS


def clear_comments(album_dir: Path) -> None:
    """Remove the 'comment' tag from all audio files in the album directory."""
    # Lowercase set for case-insensitive Vorbis comment matching (spec is case-insensitive)
    _vorbis_comment_keys = {"comment"}
    _mp4_comment_keys = {"\xa9cmt"}
    for f in album_dir.iterdir():
        if f.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        try:
            audio = MutagenFile(f, easy=False)
            if audio is None or audio.tags is None:
                continue
            removed = False
            for key in list(audio.tags.keys()):
                if (
                    key.startswith("COMM:")
                    or key.lower() in _vorbis_comment_keys
                    or key in _mp4_comment_keys
                ):
                    del audio.tags[key]
                    removed = True
            if removed:
                audio.save()
        except Exception as e:
            print(
                f"    Warning: could not clear comments for {f.name}: {e}",
                file=sys.stderr,
            )
