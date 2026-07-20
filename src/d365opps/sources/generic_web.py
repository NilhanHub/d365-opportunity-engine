from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from d365opps.schemas import ExtractedEvidence, FetchBatch, GenericPageTarget
from d365opps.sources.base import BaseSourceAdapter


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


class GenericWebSource(BaseSourceAdapter):
    source_name = "generic_web"

    def fetch(self, source, since: datetime, cursor: str | None = None, query=None, budget=None) -> FetchBatch:
        del since, cursor, query, budget
        targets = [GenericPageTarget.model_validate(item) for item in source.config_json.get("targets", [])]
        documents = []
        for target in targets:
            response = self.client.get(str(target.url))
            response.raise_for_status()
            documents.append(
                self._html_document(
                    url=str(target.url),
                    payload=response.content,
                    metadata={"label": target.label, "country": target.country, "procurement_type": target.procurement_type},
                )
            )
        return FetchBatch(documents=documents)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        soup = BeautifulSoup(payload, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        title = (
            (soup.find("h1") or soup.find("title")).get_text(" ", strip=True)
            if soup.find("h1") or soup.find("title")
            else raw_document.canonical_url
        )
        summary = None
        description = soup.find("meta", attrs={"name": "description"})
        if description and description.get("content"):
            summary = description["content"]
        elif soup.find("p"):
            summary = soup.find("p").get_text(" ", strip=True)
        schema_types: list[str] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                payload = json.loads(script.string or "")
            except (TypeError, ValueError):
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if isinstance(item, dict) and item.get("@type"):
                    schema_types.append(str(item["@type"]))
        first_email = next(iter(EMAIL_RE.findall(page_text)), None)
        response_url = raw_document.canonical_url
        record_type = "public_page"
        tags = ["generic_web"]
        lower_text = page_text.lower()
        if "jobposting" in " ".join(schema_types).lower() or any(token in lower_text for token in ("career", "vacancy", "hiring")):
            record_type = "job_posting"
            tags.append("job_posting")
        elif any(token in lower_text for token in ("board minutes", "budget", "strategy", "modernization", "roadmap")):
            record_type = "buyer_intent"
            tags.append("buyer_intent")
        for anchor in soup.find_all("a", href=True):
            label = anchor.get_text(" ", strip=True).lower()
            href = anchor["href"]
            if any(token in label for token in ("tender", "rfp", "procurement", "vendor", "bid")):
                response_url = href
                break
        return [
            ExtractedEvidence(
                record_type=record_type,
                title=title,
                summary=summary,
                buyer_name=raw_document.metadata_json.get("label"),
                buyer_country=raw_document.metadata_json.get("country") or source.country,
                procurement_type=raw_document.metadata_json.get("procurement_type"),
                notice_type="public procurement page",
                publication_date=datetime.now(UTC),
                close_date=None,
                source_url=raw_document.canonical_url,
                response_url=response_url,
                contact_email=first_email,
                attachment_metadata=[],
                raw_excerpt=page_text[:1000],
                tags=tags,
                acquisition_method=source.acquisition_method.value,
                source_provenance={"upstream": source.name, "label": raw_document.metadata_json.get("label")},
                extracted_data={"text_length": len(page_text), "schema_types": schema_types},
            )
        ]
