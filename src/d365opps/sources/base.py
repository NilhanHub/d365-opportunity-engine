from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import re

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from d365opps.config import get_settings
from d365opps.models import SourceRegistry
from d365opps.schemas import ExtractedEvidence, FetchBatch, FetchedDocument


class BaseSourceAdapter(ABC):
    source_name: str

    def __init__(self, client: httpx.Client | None = None) -> None:
        settings = get_settings()
        self.client = client or httpx.Client(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        )

    @abstractmethod
    def fetch(
        self,
        source: SourceRegistry,
        since: datetime,
        cursor: str | None = None,
        query: Any | None = None,
        budget: Any | None = None,
    ) -> FetchBatch:
        raise NotImplementedError

    @abstractmethod
    def extract(self, source: SourceRegistry, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        raise NotImplementedError

    def _json_document(
        self,
        *,
        external_id: str,
        url: str,
        payload: dict[str, Any],
        published_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FetchedDocument:
        return FetchedDocument(
            external_id=external_id,
            canonical_url=url,
            document_url=url,
            content_type="application/json",
            payload=json.dumps(payload).encode("utf-8"),
            published_at=published_at,
            metadata=metadata or {},
        )

    def _html_document(self, *, url: str, payload: bytes, metadata: dict[str, Any] | None = None) -> FetchedDocument:
        return FetchedDocument(
            external_id=urlparse(url).path.strip("/").replace("/", "_") or "root",
            canonical_url=url,
            document_url=url,
            content_type="text/html",
            payload=payload,
            metadata=metadata or {},
        )

    def _parse_dt(self, value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        raw = str(value)
        if re.match(r"^\d{4}-\d{2}-\d{2}[+-]\d{2}:\d{2}$", raw):
            raw = raw[:10] + "T00:00:00" + raw[10:]
        elif re.match(r"^\d{4}-\d{2}-\d{2}Z$", raw):
            raw = raw[:10] + "T00:00:00Z"
        try:
            parsed = date_parser.parse(raw)
        except (ValueError, TypeError, OverflowError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def _load_json(self, payload: bytes) -> dict[str, Any]:
        return json.loads(payload.decode("utf-8"))

    def _load_html(self, payload: bytes) -> BeautifulSoup:
        return BeautifulSoup(payload, "html.parser")

    def suffix_for_content_type(self, content_type: str) -> str:
        if "json" in content_type:
            return ".json"
        if "html" in content_type:
            return ".html"
        if "pdf" in content_type:
            return ".pdf"
        if "xml" in content_type:
            return ".xml"
        return Path(urlparse(content_type).path).suffix or ".bin"
