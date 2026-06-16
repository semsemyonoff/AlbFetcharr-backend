"""Tests for albfetcharr.download.locator module."""


from albfetcharr.download.locator import (
    AUDIO_EXTENSIONS,
    check_album_status,
    find_album_dir,
    normalize_name,
)


class TestNormalizeName:
    """Tests for normalize_name function."""

    def test_lowercase_conversion(self):
        assert normalize_name("HELLO WORLD") == "hello world"

    def test_punctuation_removal(self):
        assert normalize_name("Hello, World!") == "hello world"
        assert normalize_name("Test-Album") == "test album"
        assert normalize_name("Album (Deluxe)") == "album deluxe"

    def test_whitespace_collapse(self):
        assert normalize_name("Hello    World") == "hello world"
        assert normalize_name("  Spaced  Out  ") == "spaced out"

    def test_special_characters(self):
        assert normalize_name("Rock & Roll") == "rock roll"
        assert normalize_name("Album s Name") == "album s name"
        assert normalize_name("Track Remix") == "track remix"

    def test_empty_string(self):
        assert normalize_name("") == ""

    def test_only_punctuation(self):
        assert normalize_name("!!!???") == ""

    def test_underscore_dash_handling(self):
        assert normalize_name("Artist_Name") == "artist name"
        assert normalize_name("Artist-Name") == "artist name"


class TestFindAlbumDir:
    """Tests for find_album_dir function."""

    def test_find_exact_artist_and_album(self, tmp_path):
        """Find album with exact normalized match."""
        artist_dir = tmp_path / "The Beatles"
        artist_dir.mkdir()
        album_dir = artist_dir / "Abbey Road"
        album_dir.mkdir()

        result = find_album_dir(str(tmp_path), "The Beatles", "Abbey Road")
        assert result == album_dir

    def test_find_with_normalized_names(self, tmp_path):
        """Find album when names differ only in punctuation."""
        artist_dir = tmp_path / "The-Beatles"
        artist_dir.mkdir()
        album_dir = artist_dir / "Abbey_Road"
        album_dir.mkdir()

        result = find_album_dir(str(tmp_path), "The Beatles", "Abbey Road")
        assert result == album_dir

    def test_album_name_substring_match(self, tmp_path):
        """Find album using substring matching."""
        artist_dir = tmp_path / "Artist"
        artist_dir.mkdir()
        album_dir = artist_dir / "My Album Extended Edition"
        album_dir.mkdir()

        result = find_album_dir(str(tmp_path), "Artist", "My Album")
        assert result == album_dir

    def test_artist_not_found(self, tmp_path):
        """Return None when artist directory doesn't exist."""
        result = find_album_dir(str(tmp_path), "NonExistent", "Album")
        assert result is None

    def test_album_not_found(self, tmp_path):
        """Return None when album directory doesn't exist in artist."""
        artist_dir = tmp_path / "Artist"
        artist_dir.mkdir()

        result = find_album_dir(str(tmp_path), "Artist", "NonExistent")
        assert result is None

    def test_ignore_non_directories(self, tmp_path):
        """Ignore files when looking for artist/album directories."""
        file_in_root = tmp_path / "file.txt"
        file_in_root.write_text("test")
        artist_dir = tmp_path / "Artist"
        artist_dir.mkdir()
        album_dir = artist_dir / "Album"
        album_dir.mkdir()

        result = find_album_dir(str(tmp_path), "Artist", "Album")
        assert result == album_dir

    def test_case_insensitive_match(self, tmp_path):
        """Match artists/albums case-insensitively."""
        artist_dir = tmp_path / "ARTIST"
        artist_dir.mkdir()
        album_dir = artist_dir / "ALBUM"
        album_dir.mkdir()

        result = find_album_dir(str(tmp_path), "artist", "album")
        assert result == album_dir


class TestCheckAlbumStatus:
    """Tests for check_album_status function."""

    def test_missing_no_album_dir(self, tmp_path):
        """Return 'missing' when album directory doesn't exist."""
        result = check_album_status(
            str(tmp_path),
            "Artist",
            "Album",
            lambda: 5,
        )
        assert result == "missing"

    def test_missing_empty_album_dir(self, tmp_path):
        """Return 'missing' when album directory has no audio files."""
        artist_dir = tmp_path / "Artist"
        artist_dir.mkdir()
        album_dir = artist_dir / "Album"
        album_dir.mkdir()
        (album_dir / "file.txt").write_text("not an audio file")

        result = check_album_status(
            str(tmp_path),
            "Artist",
            "Album",
            lambda: 5,
        )
        assert result == "missing"

    def test_complete_expected_tracks(self, tmp_path):
        """Return 'complete' when all tracks are downloaded."""
        artist_dir = tmp_path / "Artist"
        artist_dir.mkdir()
        album_dir = artist_dir / "Album"
        album_dir.mkdir()
        (album_dir / "track1.mp3").write_text("dummy")
        (album_dir / "track2.mp3").write_text("dummy")
        (album_dir / "track3.flac").write_text("dummy")

        result = check_album_status(
            str(tmp_path),
            "Artist",
            "Album",
            lambda: 3,
        )
        assert result == "complete"

    def test_incomplete_when_lidarr_reports_zero_tracks(self, tmp_path):
        """Return 'incomplete' (not 'missing') when files exist but Lidarr has no track metadata."""
        artist_dir = tmp_path / "Artist"
        artist_dir.mkdir()
        album_dir = artist_dir / "Album"
        album_dir.mkdir()
        (album_dir / "track1.mp3").write_text("dummy")

        result = check_album_status(
            str(tmp_path),
            "Artist",
            "Album",
            lambda: 0,
        )
        assert result == "incomplete"

    def test_incomplete_fewer_tracks(self, tmp_path):
        """Return 'incomplete' when fewer tracks than expected."""
        artist_dir = tmp_path / "Artist"
        artist_dir.mkdir()
        album_dir = artist_dir / "Album"
        album_dir.mkdir()
        (album_dir / "track1.mp3").write_text("dummy")
        (album_dir / "track2.mp3").write_text("dummy")

        result = check_album_status(
            str(tmp_path),
            "Artist",
            "Album",
            lambda: 5,
        )
        assert result == "incomplete"

    def test_complete_with_non_audio_files(self, tmp_path):
        """Count only audio files, ignore others."""
        artist_dir = tmp_path / "Artist"
        artist_dir.mkdir()
        album_dir = artist_dir / "Album"
        album_dir.mkdir()
        (album_dir / "track1.mp3").write_text("dummy")
        (album_dir / "track2.mp3").write_text("dummy")
        (album_dir / "cover.jpg").write_text("dummy")
        (album_dir / "info.txt").write_text("dummy")

        result = check_album_status(
            str(tmp_path),
            "Artist",
            "Album",
            lambda: 2,
        )
        assert result == "complete"

    def test_audio_extensions_recognized(self, tmp_path):
        """Recognize all audio extensions."""
        artist_dir = tmp_path / "Artist"
        artist_dir.mkdir()
        album_dir = artist_dir / "Album"
        album_dir.mkdir()

        for ext in AUDIO_EXTENSIONS:
            (album_dir / f"track{ext}").write_text("dummy")

        result = check_album_status(
            str(tmp_path),
            "Artist",
            "Album",
            lambda: len(AUDIO_EXTENSIONS),
        )
        assert result == "complete"

    def test_case_insensitive_extension(self, tmp_path):
        """Recognize audio files with uppercase extensions."""
        artist_dir = tmp_path / "Artist"
        artist_dir.mkdir()
        album_dir = artist_dir / "Album"
        album_dir.mkdir()
        (album_dir / "track1.MP3").write_text("dummy")
        (album_dir / "track2.FLAC").write_text("dummy")

        result = check_album_status(
            str(tmp_path),
            "Artist",
            "Album",
            lambda: 2,
        )
        assert result == "complete"
