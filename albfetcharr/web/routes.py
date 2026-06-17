"""Web API routes for AlbFetcharr."""

import importlib.resources
import json
import logging
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, Response, jsonify, request
from spectree import Response as SpecResponse

from albfetcharr.config import load_lidarr_config, load_ui_defaults, load_yandex_options
from albfetcharr.download.locator import check_album_status, find_album_dir
from albfetcharr.download.tags import clear_comments
from albfetcharr.lidarr.client import (
    get_all_artists,
    get_artist_root_folder,
    get_lidarr_track_count,
    get_root_folders,
    get_wanted_albums,
)
from albfetcharr.lidarr.importer import post_import_cleanup, run_import
from albfetcharr.sources import all_providers, get_provider
from albfetcharr.sources.base import Match
from albfetcharr.web import schemas
from albfetcharr.web.spec import api

logger = logging.getLogger("albfetcharr")

log_queue = queue.Queue()
download_lock = threading.Lock()

# Stream claim state: protects single-consumer SSE access
_stream_claim_lock = threading.Lock()
_stream_claim_state = {
    "claimed": False,
    "claimed_at": None,
    "last_seen": None,
    # Monotonically incremented each time the claim is taken; the generator
    # captures its own generation at start and only clears in finally if it
    # still matches — prevents a stale generator from evicting a reconnected
    # client's claim.
    "generation": 0,
    # Number of generators currently inside log_queue.get() — see
    # _handoff_condition above.  Guarded by _handoff_condition, NOT by
    # _stream_claim_lock (different locks to avoid inversion).
    "handoffs_pending": 0,
}

# Handoff coordination: counts generators currently inside log_queue.get()
# that may need to appendleft a message back if they turn out to be stale.
# The new (owner) generator waits for this to reach zero before draining the
# queue and emitting the done sentinel, so no requeued message is orphaned.
# Separate Condition (own internal RLock) to avoid lock-inversion with
# _stream_claim_lock, which generate() and the claim endpoint both hold.
_handoff_condition = threading.Condition()


def log(msg: str | None):
    """Add message to the log queue."""
    log_queue.put(msg)


def register_routes(app: Flask):
    """Register all API routes."""

    @app.route("/")
    def index():
        try:
            index_html = (
                importlib.resources.files("albfetcharr.web")
                .joinpath("static/dist/index.html")
                .read_text()
            )
            return index_html, 200, {"Content-Type": "text/html; charset=utf-8"}
        except (FileNotFoundError, AttributeError):
            error_msg = (
                "Frontend not built — build the frontend repo "
                "(npm run build) and deploy its dist into static/dist"
            )
            return error_msg, 500, {"Content-Type": "text/plain"}

    @app.route("/api/config")
    @api.validate(resp=SpecResponse(HTTP_200=schemas.ConfigResponse), tags=["config"])
    def api_config():
        opts = load_yandex_options()
        try:
            default_quality = int(opts.quality)
        except (ValueError, TypeError):
            default_quality = 2
        ui_defaults = load_ui_defaults()
        lidarr_cfg = load_lidarr_config()
        return jsonify(
            {
                "default_quality": default_quality,
                "default_lang": ui_defaults.language,
                "default_theme": ui_defaults.theme,
                "import_enabled": bool(lidarr_cfg.import_path),
            }
        )

    @app.route("/api/sources")
    @api.validate(resp=SpecResponse(HTTP_200=schemas.SourcesResponse), tags=["sources"])
    def api_sources():
        providers = all_providers()
        return jsonify([{"id": p.id, "name": p.name} for p in providers])

    @app.route("/api/wanted")
    @api.validate(
        resp=SpecResponse(HTTP_200=schemas.WantedResponse, HTTP_502=schemas.ErrorResponse),
        tags=["wanted"],
    )
    def api_wanted():
        cfg = load_lidarr_config()
        try:
            albums = get_wanted_albums(cfg.base_url, cfg.api_key)
        except Exception as e:
            logger.warning("Could not fetch wanted albums: %s", e)
            return jsonify({"error": "Could not reach Lidarr"}), 502
        download_dir = os.environ.get("DOWNLOAD_DIR", "/downloads")

        root_folders = []
        artist_rf_map = {}
        try:
            root_folders = get_root_folders(cfg.base_url, cfg.api_key)
            all_artists = get_all_artists(cfg.base_url, cfg.api_key)
            for a in all_artists:
                aid = a.get("id")
                apath = a.get("path", "")
                if aid and apath:
                    artist_rf_map[aid] = get_artist_root_folder(apath, root_folders)
        except Exception:
            logger.warning("Could not fetch artists/root folders for library grouping")

        result = []
        for album in albums:
            artist_obj = album.get("artist", {})
            artist = artist_obj.get("artistName", "Unknown Artist")
            artist_id = artist_obj.get("id", 0)
            title = album.get("title", "Unknown Album")
            album_id = album.get("id", 0)
            release_date = (album.get("releaseDate") or "N/A")[:10]
            added = (album.get("added") or "")[:10]

            def _track_count_fetcher(aid=album_id):
                try:
                    return get_lidarr_track_count(cfg.base_url, cfg.api_key, aid)
                except Exception:
                    return 0

            status = check_album_status(
                download_dir,
                artist,
                title,
                _track_count_fetcher,
            )
            root_folder = artist_rf_map.get(artist_id, "")
            result.append(
                {
                    "artist": artist,
                    "title": title,
                    "album_id": album_id,
                    "release_date": release_date,
                    "added": added,
                    "status": status,
                    "root_folder": root_folder,
                }
            )
        return jsonify(result)

    @app.route("/api/search", methods=["POST"])
    @api.validate(
        json=schemas.SearchRequest,
        resp=SpecResponse(HTTP_200=schemas.SearchResponse, HTTP_503=schemas.SearchResponse),
        tags=["search"],
    )
    def api_search():
        data = request.context.json.model_dump()
        albums = data["albums"]
        sources = data["sources"]

        all_pvdrs = all_providers()
        if not all_pvdrs:
            return jsonify([]), 503

        selected_providers = []
        if sources:
            for src in sources:
                try:
                    pvdr = get_provider(src)
                    selected_providers.append(pvdr)
                except KeyError:
                    logger.warning("Source %s not found in registry", src)
        else:
            selected_providers = all_pvdrs

        if not selected_providers:
            return jsonify([]), 503

        results = []

        def search_provider(pvdr, artist, title):
            matches = pvdr.search(artist, title, limit=5)
            return [
                {
                    "source": match.source,
                    "source_name": pvdr.name,
                    "match_url": match.url,
                    "match_title": match.title,
                    "match_artists": match.artists,
                    "cover_url": match.cover_url or "",
                    "year": match.year,
                    "track_count": match.track_count,
                }
                for match in matches
            ]

        for album_req in albums:
            artist = album_req.get("artist")
            title = album_req.get("title")
            album_id = album_req.get("album_id")
            root_folder = album_req.get("root_folder", "")

            album_results = []
            album_errors = []

            with ThreadPoolExecutor(max_workers=len(selected_providers)) as executor:
                futures = {
                    executor.submit(search_provider, pvdr, artist, title): pvdr
                    for pvdr in selected_providers
                }

                for future in as_completed(futures):
                    pvdr = futures[future]
                    try:
                        album_results.extend(future.result())
                    except Exception as e:
                        logger.warning("Search failed: provider=%s: %s", pvdr.id, e)
                        album_errors.append(
                            {
                                "source": pvdr.id,
                                "source_name": pvdr.name,
                                "message": "Search failed",
                            }
                        )

            results.append(
                {
                    "artist": artist,
                    "title": title,
                    "album_id": album_id,
                    "root_folder": root_folder,
                    "results": album_results,
                    "errors": album_errors,
                }
            )

        return jsonify(results)

    @app.route("/api/download/stream/claim", methods=["POST"])
    @api.validate(
        resp=SpecResponse(HTTP_200=schemas.ClaimResponse, HTTP_409=schemas.ErrorResponse),
        tags=["download"],
    )
    def api_download_stream_claim():
        do_drain = False
        with _stream_claim_lock:
            now = time.monotonic()
            data = request.get_json(silent=True) or {}
            reconnect = data.get("reconnect", False)

            # Auto-release if idle for >60s
            if (
                _stream_claim_state["claimed"]
                and _stream_claim_state["last_seen"] is not None
                and now - _stream_claim_state["last_seen"] > 60
            ):
                _stream_claim_state["claimed"] = False
                _stream_claim_state["claimed_at"] = None
                _stream_claim_state["last_seen"] = None

            # Reconnect is allowed to forcibly take over an existing claim so
            # that a same-tab reconnect succeeds even while the old generator
            # is still blocking on queue.get(timeout=30).  Non-reconnect
            # requests still see 409 when the claim is held.
            if _stream_claim_state["claimed"] and not reconnect:
                return jsonify({"error": "stream already in use"}), 409

            # Claim is free (or reconnecting — force takeover).
            # Increment generation so the previous generator's finally block
            # is a no-op and does not evict this new claim.
            _stream_claim_state["generation"] += 1
            _stream_claim_state["claimed"] = True
            _stream_claim_state["claimed_at"] = now
            _stream_claim_state["last_seen"] = now

            if not reconnect:
                do_drain = True

        # Drain stale items from a crashed prior session — skip on reconnect
        # so live events already in the queue are not discarded.  Done outside
        # _stream_claim_lock to avoid lock-inversion with _handoff_condition,
        # which generate() acquires independently of _stream_claim_lock.
        if do_drain:
            with _handoff_condition:
                _stream_claim_state["handoffs_pending"] = 0
            while True:
                try:
                    log_queue.get_nowait()
                except queue.Empty:
                    break

        return jsonify({"claimed": True}), 200

    @app.route("/api/download", methods=["POST"])
    @api.validate(
        json=schemas.DownloadRequest,
        resp=SpecResponse(
            HTTP_202=schemas.DownloadStartedResponse,
            HTTP_400=schemas.ErrorResponse,
            HTTP_409=schemas.ErrorResponse,
        ),
        tags=["download"],
    )
    def api_download():
        items = request.context.json.model_dump()["items"]

        for item in items:
            try:
                get_provider(item["source"])
            except KeyError:
                return jsonify({"error": f"Unknown source: {item['source']}"}), 400

        if not download_lock.acquire(blocking=False):
            return jsonify({"error": "Download already in progress"}), 409

        def emit_progress(album_id, item_index, item_total, status, message="", **extra):
            """Emit a progress event to the SSE stream.

            ``extra`` carries optional fields the frontend renders when present
            (and ignores otherwise): ``progress`` (0-100 numeric for a real bar),
            ``track_index``/``track_total`` (per-track position), ``partial`` (the
            album finished with some failed tracks), and the per-track counts
            (``downloaded``/``existing``/``skipped``/``errors``).
            """
            payload = {
                "album_id": album_id,
                "item_index": item_index,
                "item_total": item_total,
                "status": status,
                "message": message,
            }
            payload.update(extra)
            log_queue.put({"progress": payload})

        def run_downloads():
            try:
                cfg = load_lidarr_config()
                download_dir = os.environ.get("DOWNLOAD_DIR", "/downloads")
                downloaded = []

                for idx, item in enumerate(items, 1):
                    artist = item.get("artist", "")
                    title = item.get("title", "")
                    source = item.get("source", "")
                    match_url = item.get("match_url", "")
                    album_id = item.get("album_id", 0)
                    quality = item.get("quality")

                    if not artist or not title or not source or not match_url:
                        log(f"[{idx}/{len(items)}] Skipping item with missing fields")
                        continue

                    try:
                        provider = get_provider(source)
                    except KeyError:
                        log(f"[{idx}/{len(items)}] Source '{source}' not available")
                        emit_progress(
                            album_id, idx, len(items), "failed", f"Source '{source}' not available"
                        )
                        continue

                    # Emit starting status
                    emit_progress(album_id, idx, len(items), "starting", f"{artist} — {title}")

                    quality_str = str(quality) if quality is not None else ""
                    quality_info = f" (quality: {quality_str})" if quality_str else ""
                    log(f"[{idx}/{len(items)}] {artist} — {title}{quality_info}")
                    log(f"  Downloading from {provider.name}: {match_url}")

                    # Emit downloading status. For providers that stream per-track
                    # progress, carry an explicit numeric progress at the band floor
                    # (10) so the bar holds at the "starting" level until the first
                    # per-track update climbs from there — without it the frontend
                    # buckets bare "downloading" to 50%, which then visibly snaps back
                    # down to the real per-track percent. Providers that don't stream
                    # progress keep the bare event (frontend's 50% bucket).
                    dl_extra = {"progress": 10} if provider.streams_progress else {}
                    emit_progress(
                        album_id,
                        idx,
                        len(items),
                        "downloading",
                        f"Downloading from {provider.name}",
                        **dl_extra,
                    )

                    # Per-track progress: providers that download track-by-track
                    # (YouTube Music) report a DownloadProgress after each track so
                    # the bar reflects real progress instead of a single mid bucket.
                    # We hold the last update to detect a partial album afterwards.
                    last_progress = {}

                    def _on_progress(p, _album_id=album_id, _idx=idx, _store=last_progress):
                        _store["p"] = p
                        # Map track completion into a 10-80 band so the numeric bar
                        # rises monotonically between "starting" (~10) and the
                        # post-download buckets ("downloaded" ~85) the frontend uses.
                        pct = 10 + round((p.completed / p.total) * 70) if p.total else 50
                        emit_progress(
                            _album_id,
                            _idx,
                            len(items),
                            "downloading",
                            p.message or f"Track {p.completed}/{p.total}",
                            progress=pct,
                            track_index=p.completed,
                            track_total=p.total,
                            downloaded=p.downloaded,
                            existing=p.existing,
                            skipped=p.skipped,
                            errors=p.errors,
                        )

                    # The on-disk album layout must key off the Lidarr album/artist
                    # names (item["title"]/item["artist"]), NOT the source's own
                    # metadata (match_title/match_artists): find_album_dir /
                    # check_album_status / post_import_cleanup all look albums up by
                    # the Lidarr names. Providers that write per-track files from the
                    # Match (YouTube Music) therefore receive the Lidarr names here,
                    # while url=match_url still carries the source identifier
                    # (e.g. the YouTube Music browseId) used to resolve the download.
                    # Yandex / SoundCloud ignore title/artists (they fetch by url only),
                    # so this is a no-op for them.
                    match = Match(
                        source=source,
                        url=match_url,
                        title=title,
                        artists=artist,
                        cover_url=None,
                        year=None,
                        track_count=None,
                    )

                    try:
                        success = provider.download(
                            match, quality=quality, log=log, on_progress=_on_progress
                        )
                    except Exception as e:
                        success = False
                        exc_name = type(e).__name__
                        log(f"  ERROR: {exc_name}")
                        emit_progress(
                            album_id, idx, len(items), "failed", f"Download failed: {exc_name}"
                        )
                        continue

                    if success:
                        if source == "yandex" and load_yandex_options().clear_comments:
                            album_dir = find_album_dir(download_dir, artist, title)
                            if album_dir:
                                log("  Clearing comments tags...")
                                clear_comments(album_dir)
                        downloaded.append(
                            {
                                "artist": artist,
                                "title": title,
                                "album_id": album_id,
                                "item_idx": idx,
                            }
                        )
                        # A partial album (some tracks failed but ≥1 succeeded) is a
                        # success we still import — surfaced as a warning, not FAILED.
                        # Same "downloaded" event either way; the partial case just
                        # carries extra fields the frontend renders as a warning.
                        p = last_progress.get("p")
                        partial = bool(p and p.errors > 0)
                        if partial:
                            log(f"  OK (partial: {p.errors} track(s) failed)")
                            message = f"Downloaded with {p.errors} failed track(s), awaiting import"
                            extra = {
                                "partial": True,
                                "errors": p.errors,
                                "downloaded": p.downloaded,
                                "existing": p.existing,
                                "skipped": p.skipped,
                                "track_total": p.total,
                            }
                        else:
                            log("  OK")
                            message = "Downloaded, awaiting import"
                            extra = {}
                        emit_progress(album_id, idx, len(items), "downloaded", message, **extra)
                    else:
                        log("  FAILED")
                        emit_progress(
                            album_id,
                            idx,
                            len(items),
                            "failed",
                            "Download failed — see log for details",
                        )

                log(f"\nDownloaded: {len(downloaded)}/{len(items)}")

                # Importing semantics: branch on cfg.import_path
                if downloaded and cfg.import_path:
                    # Import enabled: emit importing status, call run_import, emit done
                    log(f"Importing {len(downloaded)} album(s) into Lidarr…")
                    for d in downloaded:
                        album_id = d["album_id"]
                        idx = d["item_idx"]
                        emit_progress(
                            album_id, idx, len(items), "importing", "Importing into Lidarr…"
                        )

                    try:
                        import_ok = run_import(cfg.base_url, cfg.api_key, cfg.import_path, log=log)
                    except Exception as import_err:
                        log(f"  Import error: {import_err}")
                        for d in downloaded:
                            emit_progress(
                                d["album_id"],
                                d["item_idx"],
                                len(items),
                                "failed",
                                "Lidarr import error",
                            )
                        import_ok = None

                    if import_ok is True:
                        post_import_cleanup(
                            download_dir,
                            cfg.base_url,
                            cfg.api_key,
                            downloaded,
                            log=log,
                        )
                        log("  Cleanup done.")
                        for d in downloaded:
                            emit_progress(
                                d["album_id"], d["item_idx"], len(items), "done", "Import complete"
                            )
                    elif import_ok is False:
                        log("  Import did not complete successfully.")
                        for d in downloaded:
                            emit_progress(
                                d["album_id"],
                                d["item_idx"],
                                len(items),
                                "failed",
                                "Lidarr import failed",
                            )
                elif downloaded:
                    # Import disabled: emit done directly for downloaded albums
                    log(
                        "Lidarr import disabled "
                        "(ALBFETCHARR_LIDARR_IMPORT_PATH not set) — "
                        f"leaving {len(downloaded)} album(s) in downloads dir"
                    )
                    for d in downloaded:
                        album_id = d["album_id"]
                        idx = d["item_idx"]
                        emit_progress(
                            album_id,
                            idx,
                            len(items),
                            "done",
                            "Saved to downloads (Lidarr import disabled)",
                        )

            except Exception as e:
                log(f"\nERROR: {e}")
            finally:
                download_lock.release()
                log(None)

        thread = threading.Thread(target=run_downloads, daemon=True)
        try:
            thread.start()
        except Exception:
            log(None)
            download_lock.release()
            raise
        return jsonify({"status": "started"}), 202

    @app.route("/api/download/stream")
    def api_download_stream():
        def generate():
            # Capture generation at start so the finally block can detect
            # whether a reconnect has already taken over this claim.
            with _stream_claim_lock:
                my_gen = _stream_claim_state["generation"]
                _stream_claim_state["last_seen"] = time.monotonic()

            try:
                while True:
                    # Signal that we are about to block in get() and may need
                    # to hand a popped message back to the new owner if
                    # superseded while waiting.  The incoming owner waits for
                    # this counter to reach zero before draining the queue and
                    # yielding done, so no message is orphaned in the window
                    # between stale's pop and stale's appendleft.
                    with _handoff_condition:
                        _stream_claim_state["handoffs_pending"] += 1

                    try:
                        msg = log_queue.get(timeout=30)
                    except queue.Empty:
                        with _handoff_condition:
                            _stream_claim_state["handoffs_pending"] -= 1
                            _handoff_condition.notify_all()
                        # Update last_seen on timeout; also exit if superseded.
                        with _stream_claim_lock:
                            _stream_claim_state["last_seen"] = time.monotonic()
                            still_owner = _stream_claim_state["generation"] == my_gen
                        if not still_owner:
                            break
                        yield ": keepalive\n\n"
                        continue

                    # Update last_seen and check ownership.
                    with _stream_claim_lock:
                        _stream_claim_state["last_seen"] = time.monotonic()
                        still_owner = _stream_claim_state["generation"] == my_gen

                    if not still_owner:
                        # Restore at front to preserve FIFO order, THEN
                        # decrement so the new owner's wait (below) can see
                        # the message in the queue before it wakes up.
                        with log_queue.mutex:
                            log_queue.queue.appendleft(msg)
                            log_queue.not_empty.notify()
                        with _handoff_condition:
                            _stream_claim_state["handoffs_pending"] -= 1
                            _handoff_condition.notify_all()
                        break

                    if msg is None:
                        # Still the owner: decrement before None processing.
                        with _handoff_condition:
                            _stream_claim_state["handoffs_pending"] -= 1
                            _handoff_condition.notify_all()
                        # Wait for any stale generators currently between
                        # their get() and their appendleft — they increment
                        # handoffs_pending before entering get(), so if any
                        # remain > 0 here, a handoff is in flight.  Once the
                        # counter reaches zero the requeued message is already
                        # in the queue and the drain below will pick it up.
                        with _handoff_condition:
                            while _stream_claim_state["handoffs_pending"] > 0:
                                _handoff_condition.wait(timeout=1.0)
                        # Drain any messages requeued by stale generators
                        # before closing the stream.
                        while True:
                            try:
                                leftover = log_queue.get_nowait()
                                if leftover is None:
                                    break
                                if isinstance(leftover, dict):
                                    yield f"data: {json.dumps(leftover)}\n\n"
                                else:
                                    yield (f"data: {json.dumps({'log': leftover})}\n\n")
                            except queue.Empty:
                                break
                        yield f"data: {json.dumps({'done': True})}\n\n"
                        # Pre-takeover race guard: a reconnect may have
                        # incremented generation between our still_owner check
                        # and here.  If so, the new generator is already
                        # waiting on the queue but won't see a None because we
                        # just consumed it.  Re-queue it so the reconnected
                        # client receives the done signal.
                        with _stream_claim_lock:
                            if _stream_claim_state["generation"] != my_gen:
                                log_queue.put(None)
                        break

                    # Regular message: yield while still holding
                    # handoffs_pending so the new owner's drain (which waits
                    # for handoffs_pending == 0) cannot run until after we
                    # check ownership post-yield.  If superseded between the
                    # initial still_owner check and the yield completing,
                    # requeue at the front before decrementing so the new
                    # owner's drain picks it up.  Use try/finally so a client
                    # disconnect (GeneratorExit) cannot leave handoffs_pending
                    # elevated and block the new owner indefinitely.
                    # GeneratorExit propagation naturally terminates the loop,
                    # so the break after the block only runs on normal yields.
                    still_owner_after = True
                    try:
                        if isinstance(msg, dict):
                            yield f"data: {json.dumps(msg)}\n\n"
                        else:
                            yield f"data: {json.dumps({'log': msg})}\n\n"
                    finally:
                        with _stream_claim_lock:
                            still_owner_after = _stream_claim_state["generation"] == my_gen
                        if not still_owner_after:
                            with log_queue.mutex:
                                log_queue.queue.appendleft(msg)
                                log_queue.not_empty.notify()
                        with _handoff_condition:
                            _stream_claim_state["handoffs_pending"] -= 1
                            _handoff_condition.notify_all()
                    if not still_owner_after:
                        break
            finally:
                # Release the claim only if this generator still owns it.
                # A reconnect increments generation and takes a new claim;
                # in that case we must not evict the reconnected client.
                with _stream_claim_lock:
                    if _stream_claim_state["generation"] == my_gen:
                        _stream_claim_state["claimed"] = False
                        _stream_claim_state["claimed_at"] = None
                        _stream_claim_state["last_seen"] = None

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
