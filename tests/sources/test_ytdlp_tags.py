"""Tests for yt-dlp tag repair functionality."""

import shutil
from pathlib import Path

import pytest
from mutagen import File as MutagenFile

from albfetcharr.sources.ytdlp_base import repair_tags_from_info

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "audio"


class TestRepairTagsFromInfo:
    """Test repair_tags_from_info function."""

    @pytest.fixture
    def album_dir(self, tmp_path):
        """Create a temporary album directory with fixture audio files."""
        if not FIXTURES_DIR.exists():
            pytest.fail(f"Audio fixtures directory not found: {FIXTURES_DIR}")

        album_dir = tmp_path / "Test Artist" / "Test Album"
        album_dir.mkdir(parents=True)

        for src in FIXTURES_DIR.glob("*.mp3"):
            dst = album_dir / src.name
            shutil.copy2(src, dst)

        return album_dir

    def test_happy_path_files_already_tagged(self, album_dir):
        """Test that already-tagged files are not modified."""
        # Prepare: tag the files
        for audio_file in album_dir.glob("*.mp3"):
            tags = MutagenFile(str(audio_file), easy=True)
            tags["artist"] = ["Test Artist"]
            tags["album"] = ["Test Album"]
            tags["title"] = [f"Track {audio_file.stem.split('0')[1]}"]
            tags["tracknumber"] = [audio_file.stem.split("0")[1]]
            tags.save()

        # Record mtimes
        original_mtimes = {f: f.stat().st_mtime for f in album_dir.glob("*.mp3")}

        # Execute
        info = {
            "title": "Different Album",
            "uploader": "Different Artist",
            "entries": [
                {"title": "Different Track 1", "artist": "Different Artist 1"},
                {"title": "Different Track 2", "artist": "Different Artist 2"},
            ],
        }
        repair_tags_from_info(album_dir, info)

        # Verify: tags unchanged and files not rewritten
        for audio_file in album_dir.glob("*.mp3"):
            tags = MutagenFile(str(audio_file), easy=True)
            assert tags.get("artist") == ["Test Artist"]
            assert tags.get("album") == ["Test Album"]
            assert audio_file.stat().st_mtime == original_mtimes[audio_file]

    def test_partial_repair_missing_artist(self, album_dir):
        """Test that missing artist is filled from info_dict."""
        # Prepare: set only title
        for audio_file in album_dir.glob("*.mp3"):
            tags = MutagenFile(str(audio_file), easy=True)
            tags["title"] = [f"Track {audio_file.stem.split('0')[1]}"]
            tags.save()

        # Execute
        info = {"title": "Test Album", "uploader": "Test Artist", "entries": []}
        repair_tags_from_info(album_dir, info)

        # Verify
        for audio_file in album_dir.glob("*.mp3"):
            tags = MutagenFile(str(audio_file), easy=True)
            assert tags.get("artist") == ["Test Artist"]
            assert tags.get("album") == ["Test Album"]

    def test_partial_repair_missing_title(self, album_dir):
        """Test that missing title is filled from entry or filename."""
        # Prepare: set only artist and album
        for audio_file in album_dir.glob("*.mp3"):
            tags = MutagenFile(str(audio_file), easy=True)
            tags["artist"] = ["Test Artist"]
            tags["album"] = ["Test Album"]
            tags.save()

        # Execute
        info = {
            "title": "Test Album",
            "uploader": "Test Artist",
            "entries": [
                {"title": "Track One", "artist": "Test Artist"},
                {"title": "Track Two", "artist": "Test Artist"},
            ],
        }
        repair_tags_from_info(album_dir, info)

        # Verify: each file gets the title from the corresponding entry by index
        expected_titles = [["Track One"], ["Track Two"]]
        for idx, audio_file in enumerate(sorted(album_dir.glob("*.mp3"))):
            tags = MutagenFile(str(audio_file), easy=True)
            assert tags.get("title") == expected_titles[idx]

    def test_partial_repair_missing_tracknumber(self, album_dir):
        """Test that missing tracknumber is filled from position."""
        # Prepare: set only title and artist
        for audio_file in album_dir.glob("*.mp3"):
            tags = MutagenFile(str(audio_file), easy=True)
            tags["artist"] = ["Test Artist"]
            tags["album"] = ["Test Album"]
            tags["title"] = [f"Track {audio_file.stem.split('0')[1]}"]
            tags.save()

        # Execute
        info = {"title": "Test Album", "uploader": "Test Artist", "entries": []}
        repair_tags_from_info(album_dir, info)

        # Verify: tracknumber should be set based on position
        for idx, audio_file in enumerate(sorted(album_dir.glob("*.mp3"))):
            tags = MutagenFile(str(audio_file), easy=True)
            assert tags.get("tracknumber") == [str(idx + 1)]

    def test_non_audio_files_skipped(self, album_dir):
        """Test that non-audio files are skipped."""
        # Add non-audio files
        (album_dir / "cover.jpg").write_text("fake jpg")
        (album_dir / "info.txt").write_text("info")

        # Prepare: tag one audio file
        audio_files = list(album_dir.glob("*.mp3"))
        if audio_files:
            tags = MutagenFile(str(audio_files[0]), easy=True)
            tags.save()

        # Execute
        info = {"title": "Test Album", "uploader": "Test Artist", "entries": []}
        repair_tags_from_info(album_dir, info)

        # Verify: no errors, and non-audio files still exist
        assert (album_dir / "cover.jpg").exists()
        assert (album_dir / "info.txt").exists()

    def test_missing_entry_mapping(self, album_dir):
        """Test handling when there are more files than entries."""
        # Execute
        info = {
            "title": "Test Album",
            "uploader": "Test Artist",
            "entries": [{"title": "Track One", "artist": "Artist One"}],
        }
        repair_tags_from_info(album_dir, info)

        # Verify: first file gets entry data, others fall back to album-level
        audio_files = sorted(album_dir.glob("*.mp3"))
        if len(audio_files) > 0:
            tags0 = MutagenFile(str(audio_files[0]), easy=True)
            assert tags0.get("artist") is not None
            assert tags0.get("album") == ["Test Album"]

    def test_nonexistent_directory(self, tmp_path):
        """Test handling of nonexistent directory."""
        nonexistent = tmp_path / "nonexistent"
        info = {"title": "Album", "uploader": "Artist", "entries": []}

        # Should not raise
        repair_tags_from_info(nonexistent, info)

    def test_empty_directory(self, tmp_path):
        """Test handling of empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        info = {"title": "Album", "uploader": "Artist", "entries": []}

        # Should not raise
        repair_tags_from_info(empty_dir, info)

    def test_log_callback_invoked(self, album_dir):
        """Test that log callback is invoked with repair messages."""
        log_messages = []

        def capture_log(msg):
            log_messages.append(msg)

        # Prepare: untagged file
        for audio_file in album_dir.glob("*.mp3"):
            tags = MutagenFile(str(audio_file), easy=True)
            tags.clear()
            tags.save()

        # Execute
        info = {"title": "Test Album", "uploader": "Test Artist", "entries": []}
        repair_tags_from_info(album_dir, info, log=capture_log)

        # Verify: log was called
        assert len(log_messages) > 0
        assert any("Repaired" in msg for msg in log_messages)
