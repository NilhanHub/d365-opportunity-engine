from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urljoin

from d365opps.schemas import ExtractedEvidence, FetchBatch, FetchedDocument
from d365opps.sources.base import BaseSourceAdapter


PROCUREMENT_HINTS = ("procurement", "tender", "vendor", "supplier", "contract", "rfp", "opportunity")


class SitemapPortalSource(BaseSourceAdapter):
    source_name = "sitemap_portal"

    def fetch(self, source, since: datetime, cursor: str | None = None, query=None, budget=None) -> FetchBatch:
        del since, cursor, query, budget
        response = self.client.get(source.endpoint)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        documents: list[FetchedDocument] = []
        if root.tag.endswith("sitemapindex"):
            for loc in root.findall(".//{*}loc")[:5]:
                if not loc.text:
                    continue
                child_response = self.client.get(loc.text.strip())
                child_response.raise_for_status()
                documents.append(
                    FetchedDocument(
                        external_id=loc.text.strip().rsplit("/", 1)[-1],
                        canonical_url=loc.text.strip(),
                        document_url=loc.text.strip(),
                        content_type=child_response.headers.get("content-type", "application/xml"),
                        payload=child_response.content,
                        metadata={"sitemap_parent": source.endpoint},
                    )
                )
        else:
            documents.append(
                FetchedDocument(
                    external_id="sitemap",
                    canonical_url=str(response.url),
                    document_url=str(response.url),
                    content_type=response.headers.get("content-type", "application/xml"),
                    payload=response.content,
                    metadata={},
                )
            )
        return FetchBatch(documents=documents, next_cursor=None)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        root = ET.fromstring(payload)
        evidence: list[ExtractedEvidence] = []
        for loc in root.findall(".//{*}loc")[:100]:
            if not loc.text:
                continue
            href = loc.text.strip()
            if not any(token in href.lower() for token in PROCUREMENT_HINTS):
                continue
            evidence.append(
                ExtractedEvidence(
                    record_type="discovered_page",
                    title=href.rsplit("/", 1)[-1].replace("-", " ").title(),
                    buyer_country=source.country,
                    procurement_type="Sitemap procurement page",
                    publication_date=self._parse_dt(next((node.text for node in root.findall(".//{*}lastmod") if node.text), None)),
                    source_url=href,
                    response_url=href,
                    tags=["sitemap", source.name],
                    raw_excerpt=href,
                    acquisition_method=source.acquisition_method.value,
                    source_provenance={"upstream": source.name, "sitemap": raw_document.canonical_url},
                    extracted_data={"sitemap_parent": raw_document.metadata_json.get("sitemap_parent")},
                )
            )
        return evidence
