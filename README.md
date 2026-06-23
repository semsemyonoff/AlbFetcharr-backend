# AlbFetcharr backend

The application behind AlbFetcharr — a Flask service that reads Lidarr's
**wanted** albums, searches and downloads them from
[Yandex Music](https://music.yandex.ru/),
[YouTube Music](https://music.youtube.com/),
[SoundCloud](https://soundcloud.com/), and [Bandcamp](https://bandcamp.com/),
and imports them back into [Lidarr](https://lidarr.audio/). It serves the HTTP
API, the bundled SPA, and an equivalent CLI; sources are pluggable.

> **This repo is the service, not its deployment.** For self-hosting (the Docker
> image, `docker-compose`, library mapping, Lidarr wiring, registries, and the
> release process) see the deploy repo:
> [`AlbFetcharr/deploy`](https://github.com/semsemyonoff/AlbFetcharr-deploy).
> The React/Vite UI lives in its own repo: `AlbFetcharr/frontend`.

## How it works

1. **Wanted** — fetch the list of missing albums from the Lidarr API.
2. **Search** — for each album, query the enabled sources and rank candidates.
3. **Download** — fetch the chosen candidate at the chosen quality/format
   (Yandex via `yandex-music-downloader`; the rest via `yt-dlp`), writing tagged
   files into the download dir.
4. **Import** — hand the album to Lidarr's ManualImport API and copy cover art
   next to the imported album (translating Lidarr's path back through the
   library map).

The same flow is available three ways: the step-by-step web UI, the HTTP API,
and the `albfetcharr` CLI.

## Architecture

```
albfetcharr/
├── cli.py            # `albfetcharr` entry point: wanted / download subcommands
├── config.py         # environment + settings-store resolution into a typed config
├── version.py        # APP_VERSION reporting (see "Versioning")
├── logging_config.py # app log setup (ALBFETCHARR_LOG_LEVEL / app_log_level)
├── sources/          # pluggable source providers
│   ├── base.py           # Source protocol: search() + download()
│   ├── yandex.py         # Yandex Music (yandex-music API + yandex-music-downloader)
│   ├── youtube_music.py  # YouTube Music (ytmusicapi search + yt-dlp download)
│   ├── soundcloud.py     # SoundCloud (yt-dlp)
│   ├── bandcamp.py       # Bandcamp (autocomplete API + yt-dlp)
│   └── ytdlp_base.py     # shared yt-dlp plumbing for the yt-dlp-backed sources
├── download/         # locator (path layout) + tags (metadata writing)
├── lidarr/           # client (API), importer (ManualImport), library_map
├── settings/         # optional persistent settings store
│   ├── store.py / registry.py / resolver.py  # SQLite store + key registry + precedence
│   ├── crypto.py     # Fernet encryption for secret values
│   └── file_status.py# oauth/cookies file presence checks
└── web/              # app (factory), routes, schemas, spec (OpenAPI), static/
```

A **source** implements `search(query)` → ranked candidates and
`download(candidate)` → tagged files. Adding a source is implementing that
protocol and registering it; the UI, CLI, and import flow are source-agnostic.

## Sources

| Source        | Requirement          | Notes                                                                          |
|---------------|----------------------|--------------------------------------------------------------------------------|
| Yandex Music  | `YANDEX_MUSIC_TOKEN` | Most accurate search, best metadata; AAC 64/192 or FLAC                         |
| YouTube Music | on by default        | `ytmusicapi` search (anonymous works but gets bot-gated → empty results; OAuth recommended); per-track download via `yt-dlp` |
| SoundCloud    | on by default        | Sets/playlists; search can be loose, tags may be incomplete                    |
| Bandcamp      | on by default        | Real albums with correct tags; mostly indie/self-releases; free stream is MP3 128 |

### Yandex Music
- Requires a valid auth token. Best metadata quality.
- Quality via `YANDEX_MUSIC_QUALITY`: `0` AAC 64, `1` AAC 192, `2` FLAC.

### YouTube Music
- Search uses [ytmusicapi](https://github.com/sigma67/ytmusicapi). It works
  anonymously, but YouTube increasingly bot-gates anonymous requests — the call
  succeeds yet returns **empty results**. The fix is to authenticate search via
  OAuth (optional; see [OAuth for YouTube Music search](#oauth-for-youtube-music-search)).
- Download is per-track (`youtube.com/watch?v=…`) via
  [yt-dlp](https://github.com/yt-dlp/yt-dlp); tags are written from the ytmusicapi
  album metadata (`title`, `artist`, `album`, `albumartist`, `tracknumber`, `date`).
- YouTube downloads need a **JS runtime `deno`** (on `PATH`) and the
  **`yt-dlp-ejs`** package: yt-dlp 2026.x uses them to solve YouTube's
  signature/n-challenge. Without them some formats are unavailable and downloads
  fail with `HTTP 403`. Both are baked into the Docker image; running outside
  Docker, install `deno` and `pip install yt-dlp-ejs` (already a dependency).
- Each track is retried on transient errors (e.g. `HTTP 403`), controlled by
  `ALBFETCHARR_YTDLP_RETRIES` (default 3).
- Modern YouTube often requires cookies ("Sign in to confirm you're not a bot").
  If you hit that, supply a `cookies.txt` (see [Cookies for YouTube](#cookies-for-youtube)).
- Tracks that stay unavailable after all retries are skipped and the album
  imports **partially** (`partial: N/M` in the log; marked *Partial*, not
  *Failed*, in the UI); the missing tracks stay on the wanted list.

### SoundCloud
- Uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) for search and download; needs
  ffmpeg for audio conversion.
- Search can be inaccurate — **review results in the UI before downloading.**
- `artist` / `album` / `title` / `tracknumber` come from the playlist metadata;
  loosely tagged sources may need manual fixups before import.

### Bandcamp
- Search goes through Bandcamp's public autocomplete API (no keys, albums-only
  filter); album download is via `yt-dlp` (`BandcampAlbumIE`), with real track
  numbers and tags.
- The catalog is mostly **indie/self-releases** — major-label artists are usually
  absent, and mainstream queries often surface third-party tributes/covers, so
  search checks the artist name and drops clear mismatches, ranking by closeness.
- Free stream is **MP3 128 kbit/s**; full/lossless needs a purchase. Needs ffmpeg.

### Cookies for YouTube

YouTube downloads may require cookies from a signed-in account (the *"Sign in to
confirm you're not a bot"* error). Cookie support is **optional**:

1. Export cookies in Netscape format (`cookies.txt`) from a browser signed in to
   YouTube — e.g. the
   [Get cookies.txt LOCALLY](https://github.com/kairi003/Get-cookies.txt-LOCALLY)
   extension or `yt-dlp --cookies-from-browser`.
2. Place the file where the process can read it and set its path in
   `ALBFETCHARR_YTDLP_COOKIES` (a container path when running in Docker).
3. Restart. The file is picked up only if it exists.

If unset or missing, nothing changes: the other sources work as before. YouTube
*search* does not use these cookies — for that, see OAuth below.

### OAuth for YouTube Music search

Anonymous `ytmusicapi` search eventually gets bot-gated by YouTube — the request
succeeds but **results are empty**. To stop being anonymous, authenticate search
via OAuth. This is **optional**: with no file, search stays anonymous.

You need two things: a **Google OAuth client** (`client_id` + `client_secret`)
and a **token file** (`oauth.json`):

- `client_id` / `client_secret` identify the *application*. They grant no account
  access on their own and aren't handed out as a file — create them once in
  Google Cloud (step 1).
- `oauth.json` is the *sign-in itself*: an `access_token` / `refresh_token` bound
  to your account, generated by Google in exchange for the client id/secret plus a
  browser authorization (step 2). It self-refreshes and doesn't expire like cookies.

1. **Create an OAuth client.** In the
   [Google Cloud Console](https://console.cloud.google.com/) → new project →
   enable **YouTube Data API v3** → *Credentials* → *Create credentials* →
   *OAuth client ID* → type **TVs and Limited Input devices**. Note the
   `client_id` and `client_secret`. (ytmusicapi used to ship a public client, but
   Google revoked it — your own client is now required.)
2. **Generate the token.** On any machine with Python: `pip install ytmusicapi`, then
   ```bash
   ytmusicapi oauth --client-id <CLIENT_ID> --client-secret <CLIENT_SECRET>
   ```
   Authorize in the browser via the printed link. This writes `oauth.json`.
3. **Make `oauth.json` available** at the path in `ALBFETCHARR_YTMUSIC_OAUTH`
   (default `/config/ytmusic_oauth.json`). Always required — it is the token.
   Picked up only if it exists; otherwise search stays anonymous.
4. **Give the app the client id/secret** — either add `"client_id"` /
   `"client_secret"` fields to `oauth.json`, **or** set
   `ALBFETCHARR_YTMUSIC_CLIENT_ID` / `ALBFETCHARR_YTMUSIC_CLIENT_SECRET`. Then restart.

The app reads the token as a dict and does **not** overwrite your file on refresh.
If the file is broken or missing the client id/secret, search silently falls back
to anonymous (with a warning in the logs). More on obtaining the token:
[ytmusicapi OAuth docs](https://ytmusicapi.readthedocs.io/en/stable/setup/oauth.html).

## HTTP API

`gunicorn "albfetcharr.web.app:create_app()"` serves the API and the bundled SPA
on port `5000`. Interactive API docs are at `/apidoc/scalar` (Scalar), with
Swagger UI (`/apidoc/swagger`), Redoc (`/apidoc/redoc`), and the raw spec
(`/apidoc/openapi.json`) alongside. Requests/responses are validated against the
spec. `GET /api/version` reports the service version plus the bundled yt-dlp /
yandex-music-downloader versions.

The web UI is a three-step flow (the session ends when a download finishes):

1. **Select** — load the wanted list from Lidarr, filter/sort, pick sources.
2. **Results** — search the selected albums across enabled sources; pick the best
   match and a quality/format per album.
3. **Download** — fetch with live progress (per-album bars, terminal log) and
   auto-import into Lidarr (when `ALBFETCHARR_LIDARR_IMPORT_PATH` is set).

## CLI

The package installs an `albfetcharr` entry point (also `python -m albfetcharr`):

```bash
albfetcharr wanted                     # fetch every wanted album, import into Lidarr
albfetcharr wanted --no-import         # fetch only, no import
albfetcharr wanted --source youtube_music   # restrict to one source
albfetcharr download "https://music.yandex.ru/album/12345"   # one album, source auto-detected
albfetcharr download --source soundcloud "https://soundcloud.com/..."
```

## Development

Requires **Python 3.13+**.

```bash
pip install -e ".[dev]"     # editable install with dev tools
pytest                      # tests (see pyproject for coverage config)
ruff check . && ruff format .
```

Running the server locally:

```bash
gunicorn "albfetcharr.web.app:create_app()" --bind 0.0.0.0:5000 --threads 4
```

The frontend (React + Vite SPA) lives in a **separate repo** and is built there
(`npm ci && npm run build`, **Node.js 20+**). To have Flask serve the UI when
running the backend outside Docker, drop the built SPA into
`albfetcharr/web/static/dist/`. The production Docker image does this for you (see
the deploy repo's `Dockerfile`).

### Versioning

The installed package version (`pyproject [project].version`, read via
`importlib.metadata`) is the single source of truth, re-exported as
`albfetcharr.__version__`. The version the service *reports* is `APP_VERSION`: in
the production image a build-time `APP_VERSION` env (wired from the release tag by
the deploy repo's build script) is baked in; otherwise it falls back to the
package version.

## Environment variables

The app's full configuration contract. Anything also exposed in the settings
store can be changed at runtime from the UI (see [Settings store](#settings-store)).

### Required

| Variable             | Description                                                                              |
|----------------------|------------------------------------------------------------------------------------------|
| `YANDEX_MUSIC_TOKEN` | [Yandex Music auth token](https://yandex-music.readthedocs.io/en/main/token.html)        |
| `LIDARR_URL`         | Lidarr base URL (e.g. `http://lidarr:8686`)                                               |
| `LIDARR_API_KEY`     | Lidarr API key                                                                           |

### Service

| Variable                         | Default     | Description                                                                 |
|----------------------------------|-------------|-----------------------------------------------------------------------------|
| `ALBFETCHARR_PORT`               | `5000`      | Port the server binds (the container always serves on 5000)                 |
| `ALBFETCHARR_LIDARR_IMPORT_PATH` | —           | Download dir as Lidarr sees it (for ManualImport)                           |
| `ALBFETCHARR_LIBRARY_MAP`        | —           | Library path map `lidarr_path=albfetcharr_path,…` (cover-art copy)          |
| `DOWNLOAD_DIR`                   | `/downloads`| Download dir inside the container                                           |
| `CHOWN_DIRS`                     | `true`      | Chown writable dirs on startup (`true` / `false`)                           |
| `ALBFETCHARR_DEFAULT_LANG`       | `en`        | Default UI language (`en` / `ru`)                                           |
| `ALBFETCHARR_DEFAULT_THEME`      | `system`    | Default UI theme (`system` / `light` / `dark`)                             |
| `ALBFETCHARR_LOG_LEVEL`          | `INFO`      | Log level (`DEBUG`…`CRITICAL`); `DEBUG` logs internal HTTP calls. Also the `app_log_level` setting (applies without restart) |

### Download tuning

| Variable                          | Default | Description                                                              |
|-----------------------------------|---------|--------------------------------------------------------------------------|
| `YANDEX_MUSIC_QUALITY`            | `2`     | `0` AAC 64, `1` AAC 192, `2` FLAC                                         |
| `ALBFETCHARR_LYRICS_FORMAT`       | `lrc`   | Lyrics: `none`, `text`, `lrc`                                             |
| `ALBFETCHARR_COVER_RESOLUTION`    | `400`   | Cover size in px, or `original`                                          |
| `ALBFETCHARR_EMBED_COVER`         | `0`     | Embed cover in the audio file (`0` / `1`)                                 |
| `ALBFETCHARR_SKIP_EXISTING`       | `1`     | Skip already-downloaded tracks (`0` / `1`)                               |
| `ALBFETCHARR_CLEAR_COMMENTS`      | `0`     | Strip the comments tag (`0` / `1`)                                       |
| `ALBFETCHARR_DELAY`               | `0`     | Delay between requests (seconds)                                         |
| `ALBFETCHARR_STICK_TO_ARTIST`     | `0`     | Only download albums by the requested artist (`0` / `1`)                 |
| `ALBFETCHARR_ONLY_MUSIC`          | `0`     | Music only, no podcasts/audiobooks (`0` / `1`)                           |
| `ALBFETCHARR_COMPAT_LEVEL`        | `1`     | Compatibility level (`0`–`1`)                                            |
| `ALBFETCHARR_UNSAFE_PATH`         | `0`     | Don't sanitize paths (`0` / `1`)                                        |
| `ALBFETCHARR_YTDLP_FORMAT`        | `opus`  | yt-dlp source format: `best` (no re-encode), `opus`, `m4a`, `mp3`        |
| `ALBFETCHARR_YTDLP_QUALITY`       | `192`   | Bitrate (kbit/s) for lossy formats; ignored for `best`                  |
| `ALBFETCHARR_YTDLP_COOKIES`       | —       | Path to a Netscape `cookies.txt` for yt-dlp (see [Cookies for YouTube](#cookies-for-youtube)) |
| `ALBFETCHARR_YTDLP_RETRIES`       | `3`     | Per-track download retries on transient errors. Minimum 1               |
| `ALBFETCHARR_YTMUSIC_OAUTH`       | `/config/ytmusic_oauth.json` | OAuth token file for authenticated YT Music search (used only if present) |
| `ALBFETCHARR_YTMUSIC_CLIENT_ID`   | —       | Google OAuth `client_id` (if not inside the oauth file)                 |
| `ALBFETCHARR_YTMUSIC_CLIENT_SECRET`| —      | Google OAuth `client_secret` (if not inside the oauth file)            |
| `ALBFETCHARR_ENABLE_YANDEX`       | `1`     | Enable Yandex Music (`1`/`true`/`yes` on, `0`/`false`/`no` off)          |
| `ALBFETCHARR_ENABLE_YOUTUBE_MUSIC`| `1`     | Enable YouTube Music (same truthy/falsey set)                           |
| `ALBFETCHARR_ENABLE_SOUNDCLOUD`   | `1`     | Enable SoundCloud (same truthy/falsey set)                              |

### Network (Yandex Music)

| Variable                        | Default | Description                                          |
|---------------------------------|---------|------------------------------------------------------|
| `ALBFETCHARR_YANDEX_TIMEOUT`    | `20`    | Request timeout (seconds). Formerly `ALBFETCHARR_TIMEOUT` |
| `ALBFETCHARR_YANDEX_TRIES`      | `20`    | Retries on network errors. Formerly `ALBFETCHARR_TRIES`   |
| `ALBFETCHARR_YANDEX_RETRY_DELAY`| `5`     | Delay between retries (seconds). Formerly `ALBFETCHARR_RETRY_DELAY` |

### Container

| Variable | Default | Description                |
|----------|---------|----------------------------|
| `UID`    | `1000`  | Container user UID         |
| `GID`    | `1000`  | Container user GID         |
| `UMASK`  | `022`   | umask                      |

## Settings store

AlbFetcharr supports an optional persistent settings store (SQLite). Without it
the app is env-only — behavior is unchanged from earlier versions.

| Variable                 | Default                    | Description                                                                 |
|--------------------------|----------------------------|-----------------------------------------------------------------------------|
| `ALBFETCHARR_DB_PATH`    | `/config/albfetcharr.db`   | SQLite settings-store path. Mount `/config` persistently to keep settings   |
| `ALBFETCHARR_SECRET_KEY` | —                          | Fernet key encrypting secrets (token, API key, …) at rest. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **If lost, encrypted secrets can't be recovered — back it up.** Without it, secret writes to the DB are refused and reads fall through to env |

Settings are also available over HTTP:

- `GET /api/settings` — all settings with their source (`db` / `env` / `default`),
  secrets masked; each item has `readonly: bool` and `file_status`.
- `PUT /api/settings` — update settings (`{"key": "value", …}`); a readonly key
  (`ytmusic_oauth_file`, `ytdlp_cookies_file`, `lidarr_import_path`, `library_map`)
  returns `400`.
- `DELETE /api/settings/{key}` — drop a DB override (fall back to env / default).

> **`lidarr_import_path` and `library_map` are env-only.** They are read-only in
> the UI ("Environment" section) and `PUT` is rejected (`400`) — set them via
> `ALBFETCHARR_LIDARR_IMPORT_PATH` / `ALBFETCHARR_LIBRARY_MAP`. Previously stored
> DB values still apply until removed via `DELETE`.

> **`enable_*` semantics:** `ALBFETCHARR_ENABLE_YANDEX`,
> `ALBFETCHARR_ENABLE_YOUTUBE_MUSIC`, `ALBFETCHARR_ENABLE_SOUNDCLOUD` accept only
> `1`/`true`/`yes` (on) and `0`/`false`/`no` (off). Earlier versions treated any
> non-empty value (even `false`) as "on" for two of them — a bug. If you set these
> explicitly, double-check the value.

The path-pattern variables (`ALBFETCHARR_YANDEX_PATH_PATTERN` /
`ALBFETCHARR_YTDLP_PATH_PATTERN`) are no longer read — the path layout is fixed
in code. Remove them if present.

## Dependencies

- [yandex-music-downloader](https://github.com/llistochek/yandex-music-downloader) — Yandex track downloads
- [yandex-music](https://github.com/MarshalX/yandex-music-api) — Yandex album search API
- [ytmusicapi](https://github.com/sigma67/ytmusicapi) — YouTube Music search
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube Music / SoundCloud / Bandcamp downloads
- [yt-dlp-ejs](https://github.com/yt-dlp/ejs) + [deno](https://deno.com/) — JS runtime / challenge solver for YouTube (without them some formats 403). Bundled in the Docker image; install `deno` + `pip install yt-dlp-ejs` when running outside Docker
- [ffmpeg](https://ffmpeg.org/) — audio conversion for the yt-dlp sources (in the image; required on the host otherwise)
- [Lidarr](https://lidarr.audio/) — library, wanted list, import

## Thanks

- The [yandex-music-api](https://github.com/MarshalX/yandex-music-api) developers
- The [yandex-music-downloader](https://github.com/llistochek/yandex-music-downloader) developers
- The [Lidarr](https://github.com/Lidarr/Lidarr) developers

## Disclaimer

This is an independent project, not affiliated with Yandex, Google, or SoundCloud.

Downloading music from the internet may be restricted by copyright law in your
jurisdiction. **You are solely responsible for ensuring the music content
complies with local law.** When using YouTube Music and SoundCloud as sources,
mind those services' terms of use — automated downloading via yt-dlp may violate
them.

## License

MIT — see [LICENSE](LICENSE).
