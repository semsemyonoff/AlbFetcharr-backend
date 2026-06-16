"""Web test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _clean_stream_state():
    """Reset shared SSE stream state before and after each test."""
    from albfetcharr.web.routes import (
        _handoff_condition,
        _stream_claim_lock,
        _stream_claim_state,
        log_queue,
    )

    def _reset():
        with _stream_claim_lock:
            _stream_claim_state["claimed"] = False
            _stream_claim_state["claimed_at"] = None
            _stream_claim_state["last_seen"] = None
            _stream_claim_state["generation"] = 0
        with _handoff_condition:
            _stream_claim_state["handoffs_pending"] = 0
        while not log_queue.empty():
            try:
                log_queue.get_nowait()
            except Exception:
                break

    _reset()
    yield
    _reset()
