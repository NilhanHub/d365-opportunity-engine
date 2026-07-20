from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm import Session

from d365opps.config import get_settings
from d365opps.correlation import current_correlation, ensure_correlation
from d365opps.models import PipelineEvent


_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnuknQAAAAASUVORK5CYII="
)
_SECRET_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "apikey",
    "token",
    "password",
    "secret",
    "access_token",
    "refresh_token",
}


def json_default(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool, dict, list)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return getattr(value, "value")
    return str(value)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(secret in lowered for secret in _SECRET_KEYS):
        return "<redacted>"
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    if isinstance(value, str) and any(secret in value.lower() for secret in ("bearer ", "api_key=", "token=", "password=")):
        return "<redacted>"
    return value


def redact_mapping(mapping: dict[str, Any] | None) -> dict[str, Any]:
    if not mapping:
        return {}
    return {key: redact_value(key, value) for key, value in mapping.items()}


def low_cardinality_error(exc: Exception | None) -> tuple[bool, bool, bool]:
    if exc is None:
        return False, False, False
    message = str(exc).lower()
    return ("ssl" in message, "dns" in message or "name or service not known" in message, "transport" in message or "connection" in message)


class ForensicRecorder:
    def __init__(self, session: Session, *, service: str = "pipeline") -> None:
        self.session = session
        self.settings = get_settings()
        self.service = service
        self.logs_root = self.settings.log_root / "runs"
        self.logs_root.mkdir(parents=True, exist_ok=True)

    def emit_event(
        self,
        event_type: str,
        *,
        level: str = "info",
        component: str | None = None,
        phase: str | None = None,
        run_id: str | None = None,
        job_run_id: str | None = None,
        crawl_run_id: str | None = None,
        source_id: str | None = None,
        source_name: str | None = None,
        query_id: str | None = None,
        query_family: str | None = None,
        document_id: str | None = None,
        evidence_id: str | None = None,
        opportunity_id: str | None = None,
        account_id: str | None = None,
        message: str | None = None,
        issue_code: str | None = None,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> PipelineEvent:
        correlation = ensure_correlation()
        record = PipelineEvent(
            level=level,
            event_type=event_type,
            service=self.service,
            component=component,
            phase=phase,
            run_id=run_id or correlation.run_id or correlation.job_run_id or correlation.crawl_run_id,
            job_run_id=job_run_id or correlation.job_run_id,
            crawl_run_id=crawl_run_id or correlation.crawl_run_id,
            source_id=source_id or correlation.source_id,
            source_name=source_name,
            query_id=query_id or correlation.query_id,
            query_family=query_family,
            document_id=document_id or correlation.document_id,
            evidence_id=evidence_id or correlation.evidence_id,
            opportunity_id=opportunity_id or correlation.opportunity_id,
            account_id=account_id or correlation.account_id,
            trace_id=correlation.trace_id,
            span_id=correlation.span_id,
            request_id=correlation.request_id,
            message=message,
            issue_code=issue_code,
            status=status,
            payload_json=payload or {},
        )
        self.session.add(record)
        self.session.flush()
        self._write_log_line(
            {
                "ts": record.timestamp,
                "level": level,
                "service": self.service,
                "component": component,
                "phase": phase,
                "env": "demo" if self.settings.demo_mode else "live",
                "version": "0.1.0",
                "trace_id": correlation.trace_id,
                "span_id": correlation.span_id,
                "request_id": correlation.request_id,
                "run_id": record.run_id,
                "job_run_id": record.job_run_id,
                "crawl_run_id": record.crawl_run_id,
                "source_id": record.source_id,
                "query_id": record.query_id,
                "document_id": record.document_id,
                "event_type": event_type,
                "issue_code": issue_code,
                "status": status,
                "message": message,
                "payload": payload or {},
            },
            run_id=record.run_id or record.job_run_id or record.crawl_run_id,
        )
        return record

    def log(self, *, level: str, component: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        correlation = ensure_correlation()
        self._write_log_line(
            {
                "ts": datetime.now(UTC).replace(tzinfo=None),
                "level": level,
                "service": self.service,
                "component": component,
                "env": "demo" if self.settings.demo_mode else "live",
                "version": "0.1.0",
                "trace_id": correlation.trace_id,
                "span_id": correlation.span_id,
                "request_id": correlation.request_id,
                "run_id": correlation.run_id,
                "job_run_id": correlation.job_run_id,
                "crawl_run_id": correlation.crawl_run_id,
                "source_id": correlation.source_id,
                "query_id": correlation.query_id,
                "document_id": correlation.document_id,
                "event_type": event_type,
                "message": message,
                "payload": payload or {},
            },
            run_id=correlation.run_id or correlation.job_run_id or correlation.crawl_run_id,
        )

    def cleanup_old_logs(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=self.settings.forensic_log_retention_days)
        for path in self.logs_root.glob("*.ndjson"):
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified < cutoff:
                path.unlink(missing_ok=True)

    def _write_log_line(self, payload: dict[str, Any], *, run_id: str | None) -> None:
        target = self.logs_root / f"{run_id or 'system'}.ndjson"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=json_default) + "\n")


def config_presence_report(settings=None) -> dict[str, Any]:
    settings = settings or get_settings()
    raw = settings.model_dump()
    presence: dict[str, Any] = {}
    for key, value in raw.items():
        if key.endswith("_key") or "password" in key or "token" in key:
            presence[key] = {"present": bool(value), "value": "<redacted>" if value else None}
        else:
            presence[key] = redact_value(key, value)
    return presence


def environment_presence_report() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith("D365_OPPS_"):
            continue
        payload[key] = {"present": bool(value), "value": "<redacted>" if any(secret in key.lower() for secret in ("key", "token", "password")) else value}
    return payload


def write_placeholder_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_PLACEHOLDER_PNG)


def write_checksums(paths: Iterable[Path], target: Path) -> None:
    lines = [f"{sha256_file(path)}  {path.name}" for path in sorted(paths)]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
