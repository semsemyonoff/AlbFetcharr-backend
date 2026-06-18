# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AlbFetcharr is a Python service that bridges [Lidarr](https://lidarr.audio/) and music sources ([Yandex Music](https://music.yandex.ru/), [YouTube Music](https://music.youtube.com/), [SoundCloud](https://soundcloud.com/)): it fetches Lidarr's wanted/missing albums, searches available sources, downloads them, then triggers Lidarr's ManualImport API to move them into the library. The service is built on an extensible `SourceProvider` abstraction, allowing multiple sources to coexist. README.md is in Russian and is the canonical user-facing doc.

This repository is the **backend only**. The React + Vite SPA lives in a **separate repository** and talks to this backend purely over HTTP (`/api`, `/static`) — there is no shared code or filesystem with the frontend. How the service is packaged, hosted, or orchestrated is out of scope for this repo, which is pure application source; the app runs anywhere a Python 3.13+ environment and its dependencies are available.

**System requirements:** ffmpeg must be on `PATH` — it is required for audio format conversion with yt-dlp sources (YouTube Music, SoundCloud). YouTube downloads additionally need a **JavaScript runtime** (`deno`, on `PATH`) **and** the **`yt-dlp-ejs`** package (a declared dependency): yt-dlp 2026.x solves YouTube's signature / n-challenge with these, and without both, formats are missing and downloads 403. The dev image bakes deno in (`images/backend/Dockerfile`); the production image (separate repo) must provide it too.

## Architecture

The codebase is organized as a Python package under `albfetcharr/`, with tests in `tests/`. Dependencies and tooling are configured in `pyproject.toml` (runtime under `[project]`, dev tools under the `dev` extra; ruff, pytest, and coverage are all configured there); the backend installs as an editable package (`pip install -e ".[dev]"`). Flask serves the frontend's build artifact from `albfetcharr/web/static/dist/` when present; that build is produced in the separate frontend repository, not here.

- **`albfetcharr.cli`** — CLI entrypoint with subcommands `wanted` (fetch + search + download + import) and `download URL`. Initializes the Lidarr client and provider registry.
- **`albfetcharr.web.app`** — Flask app factory `create_app()` that exposes `/api/wanted`, `/api/search`, `/api/download` (with SSE log stream at `/api/download/stream`), `/api/download/stream/claim` (preflight for stream ownership), `/api/config` (default language/theme), and the spectree doc routes `/apidoc/openapi.json`, `/apidoc/scalar`, `/apidoc/swagger`, `/apidoc/redoc`. Single-process gunicorn, 1 worker / 4 threads — download concurrency is gated by `download_lock`. No background auto-download loop (UI is fully session-driven).
- **`albfetcharr.web.spec`** — module-level `SpecTree` singleton (`api`) used by `create_app()` and `register_routes()`. `mode="strict"` means only routes decorated with `@api.validate(...)` appear in the OpenAPI spec; the HTML index `/` and the SSE stream `/api/download/stream` are intentionally undecorated and excluded.
- **`albfetcharr.web.schemas`** — pydantic v2 request/response models for all JSON endpoints: `ConfigResponse`, `SourceItem`/`SourcesResponse`, `WantedAlbum`/`WantedResponse`, `SearchRequest`/`SearchResponse` (+ `AlbumQuery`, `MatchResult`, `SearchError`, `SearchResultItem`), `DownloadItem`/`DownloadRequest`/`DownloadStartedResponse`, `ClaimResponse`, `ErrorResponse`. Malformed `/api/search` and `/api/download` requests now return `422` (spectree validation) instead of the former `400 {error}`; all other error codes (`400` unknown-source, `409` download-lock, `502` Lidarr unreachable, `503` no providers) are unchanged.
- **`albfetcharr.sources`** — extensible provider registry. `SourceProvider` ABC defines `search(artist, album, limit) -> list[Match]` and `download(match, quality, log) -> bool`. Currently implemented: `YandexMusicProvider` (via yandex-music-downloader), `YouTubeMusicProvider` (search via `ytmusicapi` — optional OAuth; download per-track via yt-dlp), `SoundCloudProvider` (via yt-dlp). The `log` callback delivers progress lines to the web SSE stream or stdout (CLI). To add a new source, create a class inheriting from `SourceProvider` with these methods and register it in `bootstrap_default_providers()` (see `albfetcharr/sources/soundcloud.py` for a compact example; `youtube_music.py` is the elaborate per-track case). The registry uses `get_provider(id)` and `all_providers()` for enumeration; thread-safe because each provider call constructs its own client state (no shared mutable state across threads).
- **`albfetcharr.lidarr`** — three sub-modules: `client.py` (Lidarr HTTP wrappers: `get_wanted_albums`, `get_root_folders`, `get_all_artists`, `get_album_path`, `wait_for_command`); `library_map.py` (`parse_library_map`, `resolve_library_path`, `validate_library_map`); `importer.py` (`run_import` + `post_import_cleanup` — callers must call both in sequence).
- **`albfetcharr.download`** — two sub-modules: `locator.py` (`normalize_name`, `find_album_dir`, `check_album_status`); `tags.py` (`clear_comments`).
- **`albfetcharr.config`** — dataclasses (`AppConfig`, `YandexOptions`, `YtDlpOptions`, `LidarrConfig`, `UIDefaults`) and helpers `_parse_bool`/`_parse_int`. The old `load_*` env-reading functions have been removed; all config is now produced by `resolve_app_config` (see below).
- **`albfetcharr.settings`** — the persistent settings layer, composed of four sub-modules:
  - `registry.py` — `Setting` dataclass and the full catalog (Tiers 1–4). Each entry carries `key`, `type`, `default`, `choices`, `env` (env-var name), `scope` (`global`/`session`), `secret`, `group`, and `provider` (`yandex`/`ytdlp`/`lidarr`/`app`/`ui`). Call `get(key)`, `all_settings()`, `by_group()`, `session_keys()`, `is_session_key(key)`. `validate_value(setting, raw)` is the single validation gate; it raises `ValueError` on bad input. **Provider classification rule:** settings that map to yandex-music-downloader flags are tagged `provider="yandex"` (e.g. `yandex_lyrics_format`, `yandex_net_timeout`); settings for yt-dlp are tagged `provider="ytdlp"` (e.g. `ytdlp_format`, `ytdlp_path_pattern`). This distinction matters for the resolver's explicit field mapping and for UI grouping.
  - `store.py` — thin SQLite wrapper (`ALBFETCHARR_DB_PATH`, default `/config/albfetcharr.db`). Opens a fresh connection per call (commit-and-close). API: `get_raw(key)`, `set_raw(key, value, *, is_secret)`, `delete(key)`, `all_raw() -> dict[str, tuple[str, bool]]`.
  - `crypto.py` — Fernet encrypt/decrypt/mask gated on `ALBFETCHARR_SECRET_KEY`. `is_enabled()`, `encrypt(plaintext)`, `decrypt(ciphertext) -> str | None` (None on invalid token), `mask(plaintext) -> str` (shows last 4 chars).
  - `resolver.py` — **`resolve_app_config(session_overrides=None) -> AppConfig`** is the single config chokepoint. Precedence: session override (Tier-3 only) → DB → env → hardcoded default. Takes one `all_raw()` snapshot, resolves every key, decrypts secrets (falls through to env on decrypt failure), then builds `LidarrConfig`, `YandexOptions`, `YtDlpOptions`, `UIDefaults`, and `AppConfig` via an **explicit** key→field mapping. Env vars are resolved at read time (no seed-copy to DB); an empty DB with no `SECRET_KEY` behaves identically to the old env-only mode.

**SSE streams (`/api/download/stream`):** Carries two event types — `{"log": "..."}` (existing log strings) and `{"progress": {...}}` (structured updates with album_id, status, item_index/total, message). Status transitions per album: `starting → downloading → downloaded → [importing] → done` (importing step is conditionally emitted only if `ALBFETCHARR_LIDARR_IMPORT_PATH` is set). Ownership is negotiated via `POST /api/download/stream/claim` preflight to prevent orphaned server-side downloads.

`progress` events also carry optional fields the frontend renders when present (and ignores otherwise): `progress` (0-100 numeric for a real bar), `track_index`/`track_total` (per-track position within an album), `partial` (album finished with some failed tracks — see below), and per-track counts (`downloaded`/`existing`/`skipped`/`errors`). Per-track granularity is driven by the provider's optional `on_progress` callback (a `DownloadProgress`), wired up in `routes.py`; providers that download an album as one unit (Yandex, SoundCloud) don't report it, so those rows fall back to the per-status bucket map on the frontend.

### Path mapping (important and non-obvious)

Lidarr and AlbFetcharr may see the music library at different mount points in their respective runtime environments. `ALBFETCHARR_LIBRARY_MAP` (`lidarr_path=albfetcharr_path,...`) translates a Lidarr-internal path (returned by the Lidarr API, e.g. `/data/library/Artist/Album`) into the corresponding AlbFetcharr-accessible path so the post-import cover-art move works. `resolve_library_path` does longest-prefix matching; `validate_library_map(root_folders, mapping=None)` warns at startup if any Lidarr root folder is unmapped — callers must fetch `root_folders` themselves via `get_root_folders()` and pass the result; the function does **not** make HTTP calls. `ALBFETCHARR_LIDARR_IMPORT_PATH` is a separate variable: the *Lidarr-internal* view of the downloads folder, used as the `folder=` argument to `/api/v1/manualimport`.

`bootstrap_default_providers()` is called explicitly from `cli.main()` and `create_app()` — **never at module import time**. This keeps the test registry empty by default. Tests register their own fakes via `register()` and isolate via the `_clean_registry` autouse fixture in `tests/conftest.py`. The function is **re-runnable**: it builds the enabled set into a fresh dict, then atomically replaces `_REGISTRY` (CPython dict assignment is atomic), so `PUT`/`DELETE /api/settings` calls it after every successful mutation to apply `enable_*` / token / credential-path changes without a restart.

**Session overrides (per-run provider construction):** Providers are singletons built at bootstrap; only `quality` was traditionally per-call. For Tier-3 session overrides (e.g. `ytdlp_format`, `yandex_lyrics_format`) to take effect, the download path constructs fresh providers from `resolve_app_config(overrides)` per run rather than using the global registry singletons. Downloads are single-flight under `download_lock`, so this is cheap. The global registry singletons remain the source for enumeration and search; only the download thread constructs per-run providers.

### Album-status state machine

`check_album_status` returns `missing` / `incomplete` / `complete` by counting audio files in the local download dir (`find_album_dir` uses `normalize_name` for fuzzy artist/album-folder matching) against Lidarr's expected track count (`get_lidarr_track_count`). `complete` albums skip the download step and go directly to the import queue; `incomplete` re-downloads (yandex-music-downloader handles `--skip-existing`).

### YouTube Music provider (search/download mechanism)

`YouTubeMusicProvider` does **not** drive yt-dlp's YouTube-Music search/playlist extractors (they trip the bot gate and return nothing). Instead:

- **Search** uses `ytmusicapi` (`YTMusic().search(..., filter="albums")`), constructed fresh per call (thread-safe by construction). The client is built by `_build_ytmusic_client(opts)`: anonymous by default, but **authenticated via OAuth** when `YtDlpOptions.ytmusic_oauth_file` (env `ALBFETCHARR_YTMUSIC_OAUTH`, default `/config/ytmusic_oauth.json`) points at an existing credentials file — anonymous search is increasingly bot-gated by YouTube (empty results). The token is read as a dict (so ytmusicapi never rewrites the file); client id/secret come from the file or `ALBFETCHARR_YTMUSIC_CLIENT_ID`/`_SECRET`; any read/auth error degrades to anonymous. Each album `Match` carries the YouTube-Music `browseId` inside `url` (`https://music.youtube.com/browse/<browseId>`) so `download()` can re-resolve the album.
- **Download** resolves the album with `YTMusic().get_album(browseId)` and downloads each track as an individual `youtube.com/watch?v=<videoId>` video via yt-dlp (far more robust than YT-Music album playlists). Tags are written cleanly with mutagen from the ytmusicapi metadata, **not** from the messy per-video tags.
- **Folder identity uses the requested Lidarr names, not source metadata.** `/api/download` (`routes.py`) passes the `Match` with `title=item["title"]` / `artists=item["artist"]` so the on-disk layout is `<lidarr-artist>/<lidarr-album>/NN - title.<audio_format>` — the exact strings `find_album_dir`/`check_album_status`/`post_import_cleanup` look up by. Source metadata desync (Various Artists, romanized names) can no longer break lookups.
- **Per-track retries.** Each downloadable track is attempted up to `YtDlpOptions.download_retries` times (env `ALBFETCHARR_YTDLP_RETRIES`, default 3, clamped to ≥1) — a *fresh* extraction per attempt to ride out transient HTTP 403 / bot-gate failures; yt-dlp's own `retries`/`fragment_retries`/`extractor_retries` cover in-extraction blips.
- **Partial albums import what's available — and are a warning, not a failure.** Tracks ytmusicapi reports unavailable (`isAvailable=False` / no `videoId`) are skipped (not errors). A track that errors after all retries is counted but does **not** fail the album: `download()` returns `True` whenever ≥1 track was produced/existed (even with some errored tracks), logging a `partial: N/M` summary. `False` only on parse failure or zero produced tracks. Partiality is conveyed to the caller via the final `on_progress` `DownloadProgress.errors` count, not the bool; `routes.py` then emits the `downloaded` event with `partial=True` (never `failed`), and the frontend renders it as an amber warning while still importing what's available. `check_album_status` reports `incomplete` and the rest stays wanted.
- **Optional cookies (shared).** `YtDlpOptions.cookies_file` (env `ALBFETCHARR_YTDLP_COOKIES`) and the `apply_cookies()` helper in `ytdlp_base.py` add a `cookiefile` to yt-dlp opts **only when** the configured file exists on disk — used by the YouTube per-track download and (via `build_ydl_opts`) by SoundCloud. Absent/missing → no `cookiefile` key (byte-for-byte today's behavior). ytmusicapi search uses no cookies; it authenticates separately via the optional OAuth file above (`ALBFETCHARR_YTMUSIC_OAUTH`).

## Commands

```bash
# Install locally with dev dependencies (Python 3.13+)
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage report (scoped to the albfetcharr package)
pytest --cov=albfetcharr

# Lint and format
ruff check .
ruff format .

# Run locally (after `pip install -e ".[dev]"`)
LIDARR_URL=... LIDARR_API_KEY=... YANDEX_MUSIC_TOKEN=... python -m albfetcharr wanted            # CLI
LIDARR_URL=... LIDARR_API_KEY=... YANDEX_MUSIC_TOKEN=... python -m flask --app albfetcharr.web.app run  # dev server on :5000

# Run the web app with gunicorn (single process: 1 worker / 4 threads)
gunicorn "albfetcharr.web.app:create_app()"
```

A `Makefile` wraps the common tasks against a local `.venv`:
`make install | test | lint | fmt | coverage | run`.

The SPA is developed and built in the separate frontend repository; during local UI development run its Vite dev server (it proxies `/api` and `/static` to this backend on `:5000`). To preview the production index served by Flask, drop the frontend's build output into `albfetcharr/web/static/dist/`.

Tests are written with pytest (HTTP is mocked via `responses`). They cover pure functions (library mapping, path normalization, album status checking, tag clearing) plus mocked HTTP interactions; coverage is scoped to the `albfetcharr` package. `mutagen` is a runtime dependency (used in `clear_comments`) and is declared explicitly in `pyproject.toml`. `spectree==2.0.1` and `pydantic>=2.11,<3` are runtime dependencies added for OpenAPI generation and request/response validation; they are declared in `pyproject.toml`. Code is linted **and** formatted with ruff: lint rules `E`, `F`, `W`, `I` with line length 100, but `E501` is ignored in the linter because `ruff format` owns line wrapping — run `ruff format .` before committing.

## Conventions

- README.md is in Russian; keep user-facing additions to it in Russian. Code, comments, and log output are in English.
- The package, image, and product are all `albfetcharr`. Legacy `yamdarr` references appear only in the README's migration section (for upgrading users).
- All env vars are `ALBFETCHARR_*` (app-level settings), `LIDARR_*` (Lidarr integration), or `YANDEX_MUSIC_*` (source-specific). No `YAMDARR_*` references in code. The Yandex network knobs are `ALBFETCHARR_YANDEX_TIMEOUT`/`_TRIES`/`_RETRY_DELAY` (renamed from the generic `ALBFETCHARR_TIMEOUT/TRIES/RETRY_DELAY`). Yandex path pattern is `ALBFETCHARR_YANDEX_PATH_PATTERN` (renamed from `ALBFETCHARR_PATH_PATTERN`); yt-dlp path template is `ALBFETCHARR_YTDLP_PATH_PATTERN` (new). Settings store: `ALBFETCHARR_DB_PATH` (SQLite file, default `/config/albfetcharr.db`) and `ALBFETCHARR_SECRET_KEY` (Fernet key for encrypting Tier-1 secrets in DB; optional — omitting disables secret writes to DB). `ALBFETCHARR_YTDLP_COOKIES` (optional) points at a Netscape `cookies.txt` for yt-dlp downloads (YouTube/SoundCloud) and no-ops when unset or the file is missing. `ALBFETCHARR_YTDLP_RETRIES` (optional, default 3) sets the per-track download attempt count for yt-dlp sources. `ALBFETCHARR_YTMUSIC_OAUTH` (optional, default `/config/ytmusic_oauth.json`) plus `ALBFETCHARR_YTMUSIC_CLIENT_ID`/`ALBFETCHARR_YTMUSIC_CLIENT_SECRET` enable authenticated YouTube Music search; no-op (anonymous) when the file is absent.
