"""Command-line interface for AlbFetcharr."""

import argparse
import sys

from albfetcharr.config import load_app_config
from albfetcharr.download.locator import check_album_status, find_album_dir
from albfetcharr.download.tags import clear_comments
from albfetcharr.lidarr.client import get_lidarr_track_count, get_root_folders, get_wanted_albums
from albfetcharr.lidarr.importer import post_import_cleanup, run_import
from albfetcharr.lidarr.library_map import validate_library_map
from albfetcharr.sources import Match, bootstrap_default_providers, get_provider


def detect_source(url: str) -> str | None:
    """Auto-detect the source provider from a URL.

    Returns:
        Source ID ("yandex", "youtube_music", "soundcloud") or None if unrecognized.
    """
    if "music.yandex" in url:
        return "yandex"
    if any(domain in url for domain in ("music.youtube.com", "youtube.com", "youtu.be")):
        return "youtube_music"
    if "soundcloud.com" in url:
        return "soundcloud"
    return None


def cmd_wanted(args):
    """Handle the 'wanted' subcommand."""
    import os

    cfg = load_app_config()
    lidarr_cfg = cfg.lidarr
    download_dir = os.environ.get("DOWNLOAD_DIR", "/downloads")

    if not lidarr_cfg.base_url or not lidarr_cfg.api_key:
        print(
            "Error: LIDARR_URL and LIDARR_API_KEY environment variables are required",
            file=sys.stderr,
        )
        sys.exit(1)

    root_folders = get_root_folders(lidarr_cfg.base_url, lidarr_cfg.api_key)
    validate_library_map(root_folders)

    albums = get_wanted_albums(lidarr_cfg.base_url, lidarr_cfg.api_key)

    if not albums:
        print("No wanted albums found.")
        return

    print(f"Wanted albums ({len(albums)}):\n")

    to_download = []
    ready_for_import = []
    provider_id = args.source or "yandex"
    try:
        ym_provider = get_provider(provider_id)
    except KeyError:
        print(
            f"Error: source provider {provider_id!r} is not available. "
            "Check that the required token/credential env var is set.",
            file=sys.stderr,
        )
        sys.exit(1)

    for i, album in enumerate(albums, 1):
        artist = album.get("artist", {}).get("artistName", "Unknown Artist")
        title = album.get("title", "Unknown Album")
        album_id = album.get("id", 0)
        release_date = (album.get("releaseDate") or "N/A")[:10]

        search_results = ym_provider.search(artist, title, limit=1)
        ym_url = search_results[0].url if search_results else None
        ym_status = ym_url if ym_url else "not found"

        status = check_album_status(
            download_dir,
            artist,
            title,
            lambda aid=album_id: get_lidarr_track_count(
                lidarr_cfg.base_url, lidarr_cfg.api_key, aid
            ),
        )
        status_labels = {
            "complete": " [complete]",
            "incomplete": " [incomplete]",
            "missing": "",
        }

        print(f"  {i:3d}. {artist} — {title} ({release_date}){status_labels[status]}")
        print(f"       {ym_provider.name}: {ym_status}")

        album_info = {
            "artist": artist,
            "title": title,
            "album_id": album_id,
            "ym_url": ym_url,
        }
        if status == "complete":
            ready_for_import.append(album_info)
        elif ym_url:
            to_download.append(album_info)

    if to_download:
        print(f"\nDownloading {len(to_download)} album(s)...\n")
        downloaded = 0
        for idx, item in enumerate(to_download, 1):
            print(f"  [{idx}/{len(to_download)}] {item['artist']} — {item['title']}")

            match = Match(
                source=provider_id,
                url=item["ym_url"],
                title=item["title"],
                artists=item["artist"],
                cover_url=None,
                year=None,
                track_count=None,
            )

            if ym_provider.download(match):
                if provider_id == "yandex" and cfg.yandex_options.clear_comments:
                    album_dir = find_album_dir(
                        download_dir,
                        item["artist"],
                        item["title"],
                    )
                    if album_dir:
                        print("    Clearing comments tags...")
                        clear_comments(album_dir)
                ready_for_import.append(item)
                downloaded += 1
        print(f"\nDownloaded: {downloaded}/{len(to_download)}")
    else:
        print("\nNothing to download.")

    if ready_for_import and lidarr_cfg.import_path and not args.no_import:
        if run_import(
            lidarr_cfg.base_url,
            lidarr_cfg.api_key,
            lidarr_cfg.import_path,
        ):
            post_import_cleanup(
                download_dir,
                lidarr_cfg.base_url,
                lidarr_cfg.api_key,
                [
                    {
                        "artist": item["artist"],
                        "title": item["title"],
                        "album_id": item["album_id"],
                    }
                    for item in ready_for_import
                ],
            )


def cmd_download(args):
    """Handle the 'download' subcommand."""
    url = args.url

    source_id = args.source
    if not source_id:
        source_id = detect_source(url)
        if not source_id:
            print(f"Error: Could not infer source from URL: {url}", file=sys.stderr)
            sys.exit(1)

    try:
        provider = get_provider(source_id)
    except KeyError:
        print(
            f"Error: source provider {source_id!r} is not available. "
            "Check that the required token/credential env var is set.",
            file=sys.stderr,
        )
        sys.exit(1)

    match = Match(
        source=source_id,
        url=url,
        title="",
        artists="",
        cover_url=None,
        year=None,
        track_count=None,
    )

    if provider.download(match):
        print("Download completed successfully.")
    else:
        print("Download failed.", file=sys.stderr)
        sys.exit(1)


def main():
    """Main entry point for AlbFetcharr CLI."""
    parser = argparse.ArgumentParser(
        description="AlbFetcharr: download wanted albums from Lidarr via Yandex Music"
    )
    subparsers = parser.add_subparsers(dest="command", help="subcommand")

    wanted_parser = subparsers.add_parser(
        "wanted", help="Fetch wanted albums from Lidarr and download from source"
    )
    wanted_parser.add_argument(
        "--no-import",
        action="store_true",
        help="Skip Lidarr import after downloading",
    )
    wanted_parser.add_argument(
        "--source",
        type=str,
        help="Source provider ID (default: yandex)",
    )
    wanted_parser.set_defaults(func=cmd_wanted)

    download_parser = subparsers.add_parser("download", help="Download a single album by URL")
    download_parser.add_argument(
        "url", help="Album URL to download (e.g., https://music.yandex.ru/album/12345)"
    )
    download_parser.add_argument(
        "--source",
        type=str,
        help="Source provider ID (inferred from URL if not specified)",
    )
    download_parser.set_defaults(func=cmd_download)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    bootstrap_default_providers()

    args.func(args)


if __name__ == "__main__":
    main()
