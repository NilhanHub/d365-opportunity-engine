from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


def _new_id(length: int = 32) -> str:
    return uuid.uuid4().hex[:length]


@dataclass(slots=True)
class CorrelationState:
    trace_id: str | None = None
    span_id: str | None = None
    request_id: str | None = None
    run_id: str | None = None
    job_run_id: str | None = None
    crawl_run_id: str | None = None
    source_id: str | None = None
    query_id: str | None = None
    document_id: str | None = None
    evidence_id: str | None = None
    opportunity_id: str | None = None
    account_id: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "job_run_id": self.job_run_id,
            "crawl_run_id": self.crawl_run_id,
            "source_id": self.source_id,
            "query_id": self.query_id,
            "document_id": self.document_id,
            "evidence_id": self.evidence_id,
            "opportunity_id": self.opportunity_id,
            "account_id": self.account_id,
        }


_STATE: contextvars.ContextVar[CorrelationState] = contextvars.ContextVar(
    "d365opps_correlation_state",
    default=CorrelationState(),
)


def current_correlation() -> CorrelationState:
    return _STATE.get()


def ensure_correlation(*, request_id: str | None = None, trace_id: str | None = None, span_id: str | None = None) -> CorrelationState:
    current = current_correlation()
    if current.trace_id and current.span_id and current.request_id:
        return current
    state = CorrelationState(
        trace_id=current.trace_id or trace_id or _new_id(32),
        span_id=current.span_id or span_id or _new_id(16),
        request_id=current.request_id or request_id or _new_id(20),
        run_id=current.run_id,
        job_run_id=current.job_run_id,
        crawl_run_id=current.crawl_run_id,
        source_id=current.source_id,
        query_id=current.query_id,
        document_id=current.document_id,
        evidence_id=current.evidence_id,
        opportunity_id=current.opportunity_id,
        account_id=current.account_id,
    )
    _STATE.set(state)
    return state


def set_correlation(**kwargs: str | None) -> CorrelationState:
    current = ensure_correlation()
    payload = current.as_dict()
    payload.update(kwargs)
    state = CorrelationState(**payload)
    _STATE.set(state)
    return state


@contextmanager
def correlation_scope(**kwargs: str | None) -> Iterator[CorrelationState]:
    current = ensure_correlation()
    payload = current.as_dict()
    payload.update(kwargs)
    token = _STATE.set(CorrelationState(**payload))
    try:
        yield _STATE.get()
    finally:
        _STATE.reset(token)


def new_child_span(**kwargs: str | None) -> CorrelationState:
    payload = ensure_correlation().as_dict()
    payload["span_id"] = _new_id(16)
    payload.update(kwargs)
    state = CorrelationState(**payload)
    _STATE.set(state)
    return state


def traceparent() -> str:
    state = ensure_correlation()
    return f"00-{state.trace_id or _new_id(32)}-{state.span_id or _new_id(16)}-01"
