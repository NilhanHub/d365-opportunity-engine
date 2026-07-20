from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from d365opps.config import get_settings
from d365opps.retrieval import QueryCompiler
from d365opps.schemas import ExtractedEvidence, FetchBatch
from d365opps.sources.base import BaseSourceAdapter


ENGLISH_KEYS = ("eng", "en")


def _flatten_localized(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        for key, localized in value.items():
            normalized = str(key or "").strip().lower()
            if any(normalized.startswith(prefix) for prefix in ENGLISH_KEYS):
                preferred = _flatten_localized(localized)
                if preferred:
                    return preferred
        parts: list[str] = []
        for localized in value.values():
            if isinstance(localized, list):
                parts.extend(str(item) for item in localized)
            else:
                parts.append(str(localized))
        return "; ".join(dict.fromkeys(parts))
    return str(value)


def _escape_term(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _ted_clause(terms: list[str]) -> str:
    phrases = [term for term in terms if term and " " in term]
    if not phrases:
        phrases = ["Dynamics 365", "Microsoft Dynamics", "Business Central"]
    unique_phrases = list(dict.fromkeys(phrases))[:6]
    return " OR ".join(f'notice-title ~ "{_escape_term(term)}"' for term in unique_phrases)


class TedSource(BaseSourceAdapter):
    source_name = "ted"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_compiler = QueryCompiler()

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del budget
        settings = get_settings()
        rendered = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        date_filter = since.astimezone(UTC).strftime("%Y%m%d")
        anchor_terms = list(rendered.required_anchors) or ["Dynamics 365", "Microsoft Dynamics", "Business Central"]
        ted_query = str(rendered.rendered_query_text or "").strip()
        if rendered.renderer == "ted_api" and ted_query:
            query_text = f"publication-date >= {date_filter} AND ({ted_query})"
        else:
            query_text = f"publication-date >= {date_filter} AND ({_ted_clause(anchor_terms)})"
        payload: dict[str, Any] = {
            "query": query_text,
            "fields": source.config_json.get(
                "fields",
                [
                    "publication-number",
                    "notice-title",
                    "buyer-name",
                    "publication-date",
                    "links",
                    "deadline-receipt-tender-date-lot",
                    "classification-cpv",
                ],
            ),
            "limit": source.config_json.get("limit", settings.ted_limit),
            "scope": source.config_json.get("scope", settings.ted_scope),
            "paginationMode": "ITERATION",
        }
        if cursor:
            payload["iterationNextToken"] = cursor
        response = self.client.post(source.endpoint, json=payload)
        response.raise_for_status()
        body = response.json()
        document = self._json_document(
            external_id=f"ted-{cursor or 'start'}-{date_filter}",
            url=source.endpoint,
            payload=body,
            metadata={
                "query": query_text,
                "query_id": rendered.query_id,
                "query_text": rendered.rendered_query_text,
                "abstract_query_text": rendered.abstract_query_text,
                "query_family": rendered.query_family,
                "phase": rendered.phase,
                "target_field": rendered.target_field,
                "renderer": rendered.renderer,
                "count": len(body.get("notices", [])),
            },
        )
        return FetchBatch(documents=[document], next_cursor=body.get("iterationNextToken"))

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        body = json.loads(payload.decode("utf-8"))
        acquisition_method = getattr(getattr(source, "acquisition_method", None), "value", None)
        source_name = getattr(source, "name", self.source_name)
        metadata = getattr(raw_document, "metadata_json", {}) or {}
        evidence: list[ExtractedEvidence] = []
        for notice in body.get("notices", []):
            links = notice.get("links", {}) or {}
            source_url = (
                (links.get("html") or {}).get("ENG")
                or (links.get("xml") or {}).get("MUL")
                or next(iter((links.get("pdf") or {}).values()), None)
                or raw_document.canonical_url
            )
            alternate_links = {key.lower(): value for key, value in (links.get("html") or {}).items() if value}
            cpv = notice.get("classification-cpv", {})
            cpv_codes = []
            if isinstance(cpv, dict):
                cpv_codes.extend(cpv.keys())
            elif isinstance(cpv, list):
                cpv_codes.extend(str(item) for item in cpv)
            summary = _flatten_localized(notice.get("short-description")) or _flatten_localized(notice.get("notice-title"))
            buyer_country = (
                notice.get("buyer-country")
                or notice.get("buyer-country-code")
                or ((notice.get("buyer-address") or {}).get("country"))
                or source.country
            )
            evidence.append(
                ExtractedEvidence(
                    title=_flatten_localized(notice.get("notice-title")) or notice.get("publication-number"),
                    summary=summary,
                    buyer_name=_flatten_localized(notice.get("buyer-name")),
                    buyer_country=buyer_country,
                    notice_type="TED notice",
                    procurement_type="TED notice",
                    publication_date=self._parse_dt(notice.get("publication-date")),
                    close_date=self._parse_dt(_flatten_localized(notice.get("deadline-receipt-tender-date-lot"))),
                    budget_value=None,
                    budget_currency=None,
                    source_url=source_url,
                    response_url=source_url,
                    attachment_urls=list((links.get("pdf") or {}).values()),
                    attachment_metadata=[{"url": value, "title": "ted_pdf"} for value in (links.get("pdf") or {}).values()],
                    cpv_codes=cpv_codes,
                    lot_titles=[_flatten_localized(notice.get("notice-title"))] if notice.get("notice-title") else [],
                    classification_codes=cpv_codes,
                    tags=["ted", "eu_procurement"],
                    procurement_id=notice.get("publication-number"),
                    raw_excerpt=summary,
                    acquisition_method=acquisition_method,
                    source_provenance={"upstream": source_name, "raw_document": raw_document.canonical_url},
                    discovery_query_id=metadata.get("query_id"),
                    discovery_query_text=metadata.get("query_text"),
                    query_family=metadata.get("query_family"),
                    extracted_data={**notice, "alternate_links": alternate_links},
                )
            )
        return evidence
