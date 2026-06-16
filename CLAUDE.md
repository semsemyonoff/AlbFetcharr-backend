# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AlbFetcharr is a Python service that bridges [Lidarr](https://lidarr.audio/) and music sources ([Yandex Music](https://music.yandex.ru/), [YouTube Music](https://music.youtube.com/), [SoundCloud](https://soundcloud.com/)): it fetches Lidarr's wanted/missing albums, searches available sources, downloads them, then triggers Lidarr's ManualImport API to move them into the library. The service is built on an extensible `SourceProvider` abstraction, allowing multiple sources to coexist. README.md is in Russian and is the canonical user-facing doc.

This repository is the **backend only**. The React + Vite SPA lives in a **separate repository** and talks to this backend purely over HTTP (`/api`, `/static`) — there is no shared code or filesystem with the frontend. Docker images and compose/deploy wiring also live outside this repo (DWE/services layer); this repo is backend source.

**Runtime dependencies:** ffmpeg is required for audio format conversion with yt-dlp sources (YouTube Music, SoundCloud). It is installed in the deployment image (built outside this repo) but must be available on the host when running outside a container.

## Architecture

The codebase is organized as a Python package under `albfetcharr/`, with tests in `tests/`. Dependencies are managed via `pyproject.toml` and the backend is installed as an editable package (`pip install -e ".[dev]"`). In production the frontend's build artifact is dropped into `albfetcharr/web/static/dist/` and served by Flask; that build happens in the separate frontend repository, not here.

- **`albfetcharr.cli`** — CLI entrypoint with subcommands `wanted` (fetch + search + download + import) and `download URL`. Initializes the Lidarr client and provider registry.
- **`albfetcharr.web.app`** — Flask app factory `create_app()` that exposes `/api/wanted`, `/api/search`, `/api/download` (with SSE log stream at `/api/download/stream`), `/api/download/stream/claim` (preflight for stream ownership), and `/api/config` (default language/theme). Single-process gunicorn, 1 worker / 4 threads — download concurrency is gated by `download_lock`. No background auto-download loop (UI is fully session-driven).
- **`albfetcharr.sources`** — extensible provider registry. `SourceProvider` ABC defines `search(artist, album, limit) -> list[Match]` and `download(match, quality, log) -> bool`. Currently implemented: `YandexMusicProvider` (via yandex-music-downloader), `YouTubeMusicProvider` (via yt-dlp), `SoundCloudProvider` (via yt-dlp). The `log` callback delivers progress lines to the web SSE stream or stdout (CLI). To add a new source, create a class inheriting from `SourceProvider` with these methods and register it in `bootstrap_default_providers()` (see `albfetcharr/sources/youtube_music.py` for a 50-line example). The registry uses `get_provider(id)` and `all_providers()` for enumeration; thread-safe because each provider call constructs its own client state (no shared mutable state across threads).
- **`albfetcharr.lidarr`** — three sub-modules: `client.py` (Lidarr HTTP wrappers: `get_wanted_albums`, `get_root_folders`, `get_all_artists`, `get_album_path`, `wait_for_command`); `library_map.py` (`parse_library_map`, `resolve_library_path`, `validate_library_map`); `importer.py` (`run_import` + `post_import_cleanup` — callers must call both in sequence).
- **`albfetcharr.download`** — two sub-modules: `locator.py` (`normalize_name`, `find_album_dir`, `check_album_status`); `tags.py` (`clear_comments`).
- **`albfetcharr.config`** — centralized env-var reading, including new `UIDefaults` dataclass for `ALBFETCHARR_DEFAULT_LANG` and `ALBFETCHARR_DEFAULT_THEME`.

**SSE streams (`/api/download/stream`):** Carries two event types — `{"log": "..."}` (existing log strings) and `{"progress": {...}}` (new structured updates with album_id, status, item_index/total, message). Status transitions per album: `starting → downloading → downloaded → [importing] → done` (importing step is conditionally emitted only if `ALBFETCHARR_LIDARR_IMPORT_PATH` is set). Ownership is negotiated via `POST /api/download/stream/claim` preflight to prevent orphaned server-side downloads.

### Path mapping (important and non-obvious)

Lidarr and AlbFetcharr see the music library at different mount points inside their containers. `ALBFETCHARR_LIBRARY_MAP` (`lidarr_path=albfetcharr_path,...`) translates a Lidarr-internal path (returned by the Lidarr API, e.g. `/data/library/Artist/Album`) into the corresponding AlbFetcharr-accessible path so the post-import cover-art move works. `resolve_library_path` does longest-prefix matching; `validate_library_map(root_folders, mapping=None)` warns at startup if any Lidarr root folder is unmapped — callers must fetch `root_folders` themselves via `get_root_folders()` and pass the result; the function does **not** make HTTP calls. `ALBFETCHARR_LIDARR_IMPORT_PATH` is a separate variable: the *Lidarr-internal* view of the downloads folder, used as the `folder=` argument to `/api/v1/manualimport`.

`bootstrap_default_providers()` is called explicitly from `cli.main()` and `create_app()` — **never at module import time**. This keeps the test registry empty by default. Tests register their own fakes via `register()` and isolate via the `_clean_registry` autouse fixture in `tests/conftest.py`.

### Album-status state machine

`check_album_status` returns `missing` / `incomplete` / `complete` by counting audio files in the local download dir (`find_album_dir` uses `normalize_name` for fuzzy artist/album-folder matching) against Lidarr's expected track count (`get_lidarr_track_count`). `complete` albums skip the download step and go directly to the import queue; `incomplete` re-downloads (yandex-music-downloader handles `--skip-existing`).

## Commands

```bash
# Install locally with dev dependencies (Python 3.13+)
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage report
pytest --cov=albfetcharr

# Lint code
ruff check albfetcharr/ tests/

# Run locally (after `pip install -e ".[dev]"`)
LIDARR_URL=... LIDARR_API_KEY=... YANDEX_MUSIC_TOKEN=... python -m albfetcharr wanted            # CLI
LIDARR_URL=... LIDARR_API_KEY=... YANDEX_MUSIC_TOKEN=... python -m flask --app albfetcharr.web.app run  # dev server on :5000

# Run web app in production
gunicorn "albfetcharr.web.app:create_app()"
```

The SPA is developed and built in the separate frontend repository; during local UI development run its Vite dev server (it proxies `/api` and `/static` to this backend on `:5000`). To preview the production index served by Flask, drop the frontend's build output into `albfetcharr/web/static/dist/`.

Tests are written with pytest. They cover pure functions (library mapping, path normalization, album status checking, tag clearing) plus mocked HTTP interactions. `mutagen` is a runtime dependency (used in `clear_comments`) and is declared explicitly in `pyproject.toml`. Code is linted with ruff (E, F, W, I rules; line-length=100).

## Conventions

- README.md is in Russian; keep user-facing additions to it in Russian. Code, comments, and log output are in English.
- The package, image, and product are all `albfetcharr`. Legacy `yamdarr` references appear only in the README's migration section (for upgrading users).
- All env vars are `ALBFETCHARR_*` (app-level settings), `LIDARR_*` (Lidarr integration), or `YANDEX_MUSIC_*` (source-specific). No `YAMDARR_*` references in code.
