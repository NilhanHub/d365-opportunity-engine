from __future__ import annotations

import io
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from d365opps.blob_store import LocalBlobStore
from d365opps.config import get_settings


class AttachmentHarvester:
    def __init__(self, blob_store: LocalBlobStore, client: httpx.Client | None = None) -> None:
        settings = get_settings()
        self.blob_store = blob_store
        self.client = client or httpx.Client(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        )
        self.settings = settings

    def harvest(self, source_name: str, urls: list[str]) -> list[dict[str, Any]]:
        if not self.settings.attachment_fetch_enabled:
            return []
        metadata: list[dict[str, Any]] = []
        for url in urls[: self.settings.max_attachment_fetch_per_record]:
            if not self._is_public_http(url):
                continue
            try:
                response = self.client.get(url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            if len(response.content) > self.settings.max_attachment_bytes:
                continue
            content_type = response.headers.get("content-type", "application/octet-stream")
            suffix = self._suffix_for(url, content_type)
            blob = self.blob_store.put_bytes(source_name, self._external_id(url), response.content, suffix)
            excerpt = self._extract_excerpt(response.content, content_type)
            metadata.append(
                {
                    "url": url,
                    "content_type": content_type,
                    "blob_path": blob.path,
                    "checksum": blob.checksum,
                    "size": blob.size,
                    "title": self._external_id(url),
                    "excerpt": excerpt[:2000] if excerpt else "",
                }
            )
        return metadata

    def _extract_excerpt(self, payload: bytes, content_type: str) -> str:
        lowered = content_type.lower()
        if "pdf" in lowered:
            try:
                reader = PdfReader(io.BytesIO(payload))
                text_parts = []
                for page in reader.pages[:3]:
                    text_parts.append(page.extract_text() or "")
                return " ".join(text_parts).strip()
            except Exception:
                return ""
        if "html" in lowered:
            soup = BeautifulSoup(payload, "html.parser")
            return soup.get_text(" ", strip=True)
        try:
            return payload.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    def _external_id(self, url: str) -> str:
        path = urlparse(url).path.rsplit("/", 1)[-1]
        return path or "attachment"

    def _is_public_http(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _suffix_for(self, url: str, content_type: str) -> str:
        path = urlparse(url).path.lower()
        if path.endswith(".pdf") or "pdf" in content_type.lower():
            return ".pdf"
        if path.endswith(".html") or "html" in content_type.lower():
            return ".html"
        if path.endswith(".txt"):
            return ".txt"
        return ".bin"
