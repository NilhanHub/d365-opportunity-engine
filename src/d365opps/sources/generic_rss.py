from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from d365opps.schemas import ExtractedEvidence, FetchBatch, FetchedDocument
from d365opps.sources.base import BaseSourceAdapter


class GenericRssSource(BaseSourceAdapter):
    source_name = "generic_rss"

    def fetch(self, source, since: datetime, cursor: str | None = None, query=None, budget=None) -> FetchBatch:
        del since, cursor, query, budget
        response = self.client.get(source.endpoint)
        response.raise_for_status()
        document = FetchedDocument(
            external_id="rss_feed",
            canonical_url=str(response.url),
            document_url=str(response.url),
            content_type=response.headers.get("content-type", "application/rss+xml"),
            payload=response.content,
            metadata={},
        )
        return FetchBatch(documents=[document], next_cursor=None)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        root = ET.fromstring(payload)
        evidence: list[ExtractedEvidence] = []
        if root.tag.endswith("rss"):
            items = root.findall(".//item")
            for item in items[:50]:
                title = _child_text(item, "title") or "RSS notice"
                summary = _child_text(item, "description")
                link = _child_text(item, "link") or raw_document.canonical_url
                evidence.append(
                    ExtractedEvidence(
                        title=title,
                        summary=summary,
                        buyer_country=source.country,
                        procurement_type="RSS feed item",
                        publication_date=self._parse_dt(_child_text(item, "pubDate")),
                        source_url=link,
                        response_url=link,
                        tags=["rss", source.name],
                        raw_excerpt=(summary or title)[:1500],
                        acquisition_method=source.acquisition_method.value,
                        source_provenance={"upstream": source.name, "feed_url": raw_document.canonical_url},
                        extracted_data={"categories": [_child_text(node, ".") for node in item.findall("category")]},
                    )
                )
            return evidence
        for entry in root.findall(".//{*}entry"):
            title = _child_text(entry, "{*}title") or "Atom notice"
            summary = _child_text(entry, "{*}summary") or _child_text(entry, "{*}content")
            link_node = entry.find("{*}link")
            link = link_node.get("href") if link_node is not None else raw_document.canonical_url
            evidence.append(
                ExtractedEvidence(
                    title=title,
                    summary=summary,
                    buyer_country=source.country,
                    procurement_type="Atom feed item",
                    publication_date=self._parse_dt(_child_text(entry, "{*}updated") or _child_text(entry, "{*}published")),
                    source_url=link,
                    response_url=link,
                    tags=["atom", source.name],
                    raw_excerpt=(summary or title)[:1500],
                    acquisition_method=source.acquisition_method.value,
                    source_provenance={"upstream": source.name, "feed_url": raw_document.canonical_url},
                    extracted_data={},
                )
            )
        return evidence


def _child_text(node, path: str) -> str | None:
    if path == ".":
        return node.text.strip() if node.text else None
    child = node.find(path)
    if child is None or child.text is None:
        return None
    return child.text.strip()
