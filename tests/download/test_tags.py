"""Tests for albfetcharr.download.tags module."""

from unittest.mock import MagicMock

from albfetcharr.download.tags import clear_comments


class TestClearComments:
    """Tests for clear_comments function."""

    def test_clear_id3_comments(self, tmp_path, mocker):
        """Remove ID3 comment tags from MP3 file."""
        album_dir = tmp_path / "album"
        album_dir.mkdir()

        mp3_file = album_dir / "track.mp3"
        mp3_file.write_bytes(b"dummy")

        mock_audio = MagicMock()
        mock_tags = {"COMM::'eng'": "value", "COMM::'rus'": "value", "TIT2": "title"}
        mock_audio.tags = mock_tags

        mock_file_fn = mocker.patch("albfetcharr.download.tags.MutagenFile")
        mock_file_fn.return_value = mock_audio

        clear_comments(album_dir)

        mock_audio.save.assert_called_once()
        assert "COMM::'eng'" not in mock_tags

    def test_clear_vorbis_comments(self, tmp_path, mocker):
        """Remove Vorbis comment tags from FLAC file."""
        album_dir = tmp_path / "album"
        album_dir.mkdir()

        flac_file = album_dir / "track.flac"
        flac_file.write_bytes(b"dummy")

        mock_audio = MagicMock()
        mock_tags = {"comment": ["test"], "artist": ["artist"]}
        mock_audio.tags = mock_tags

        mock_file_fn = mocker.patch("albfetcharr.download.tags.MutagenFile")
        mock_file_fn.return_value = mock_audio

        clear_comments(album_dir)

        mock_audio.save.assert_called_once()
        assert "comment" not in mock_tags
        assert "artist" in mock_tags

    def test_handles_none_tags(self, tmp_path, mocker):
        """Handle files with no tags."""
        album_dir = tmp_path / "album"
        album_dir.mkdir()

        mp3_file = album_dir / "track.mp3"
        mp3_file.write_bytes(b"dummy")

        mock_audio = MagicMock()
        mock_audio.tags = None

        mock_file_fn = mocker.patch("albfetcharr.download.tags.MutagenFile")
        mock_file_fn.return_value = mock_audio

        clear_comments(album_dir)

        mock_audio.save.assert_not_called()

    def test_handles_none_audio_file(self, tmp_path, mocker):
        """Handle files that mutagen can't parse."""
        album_dir = tmp_path / "album"
        album_dir.mkdir()

        mp3_file = album_dir / "track.mp3"
        mp3_file.write_bytes(b"dummy")

        mock_file_fn = mocker.patch("albfetcharr.download.tags.MutagenFile")
        mock_file_fn.return_value = None

        clear_comments(album_dir)

        mock_file_fn.assert_called_once()

    def test_ignores_non_audio_files(self, tmp_path, mocker):
        """Skip non-audio files."""
        album_dir = tmp_path / "album"
        album_dir.mkdir()

        (album_dir / "cover.jpg").write_bytes(b"JPEG")
        (album_dir / "track.mp3").write_bytes(b"dummy")

        mock_file_fn = mocker.patch("albfetcharr.download.tags.MutagenFile")

        clear_comments(album_dir)

        mock_file_fn.assert_called_once_with(album_dir / "track.mp3", easy=False)

    def test_handles_exceptions(self, tmp_path, mocker, capsys):
        """Handle exceptions when clearing comments."""
        album_dir = tmp_path / "album"
        album_dir.mkdir()

        mp3_file = album_dir / "track.mp3"
        mp3_file.write_bytes(b"dummy")

        mock_file_fn = mocker.patch("albfetcharr.download.tags.MutagenFile")
        mock_file_fn.side_effect = Exception("Test error")

        clear_comments(album_dir)

        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "track.mp3" in captured.err

    def test_removes_all_comment_key_variants(self, tmp_path, mocker):
        """Remove all variations of comment tags."""
        album_dir = tmp_path / "album"
        album_dir.mkdir()

        mp3_file = album_dir / "track.mp3"
        mp3_file.write_bytes(b"dummy")

        mock_audio = MagicMock()
        mock_tags = {
            "COMM::'eng'": "eng comment",
            "COMM::'rus'": "rus comment",
            "COMM::": "default comment",
            "COMM:something:else": "custom comm",
            "comment": "vorbis comment",
            "\xa9cmt": "mp4 comment",
            "artist": "artist",
        }
        mock_audio.tags = mock_tags

        mock_file_fn = mocker.patch("albfetcharr.download.tags.MutagenFile")
        mock_file_fn.return_value = mock_audio

        clear_comments(album_dir)

        assert "COMM::'eng'" not in mock_tags
        assert "COMM::'rus'" not in mock_tags
        assert "COMM::" not in mock_tags
        assert "COMM:something:else" not in mock_tags
        assert "comment" not in mock_tags
        assert "\xa9cmt" not in mock_tags
        assert "artist" in mock_tags
