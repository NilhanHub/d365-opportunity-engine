from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from d365opps.retrieval import QueryCompiler
from d365opps.schemas import ExtractedEvidence, FetchBatch
from d365opps.sources.base import BaseSourceAdapter


class ContractsFinderSource(BaseSourceAdapter):
    source_name = "contracts_finder"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_compiler = QueryCompiler()

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del budget
        query = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        if cursor and cursor.startswith("http"):
            response = self.client.get(cursor)
            response.raise_for_status()
            payload = response.json()
            document = self._json_document(
                external_id=f"contracts-finder-page-{abs(hash(cursor))}",
                url=str(response.url),
                payload=payload,
                metadata={
                    "cursor": cursor,
                    "count": len(payload.get("releases", [])),
                    "query_id": query.query_id,
                    "query_text": query.rendered_query_text,
                    "abstract_query_text": query.abstract_query_text,
                    "query_family": query.query_family,
                    "phase": query.phase,
                    "target_field": query.target_field,
                    "renderer": query.renderer,
                },
            )
            next_link = payload.get("links", {}).get("next") if isinstance(payload.get("links"), dict) else None
            return FetchBatch(documents=[document], next_cursor=next_link)
        params: dict[str, Any] = {
            "publishedFrom": since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "publishedTo": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": source.config_json.get("limit", 100),
        }
        if cursor:
            params["cursor"] = cursor
        response = self.client.get(source.endpoint, params=params)
        response.raise_for_status()
        payload = response.json()
        document = self._json_document(
            external_id=f"contracts-finder-{params.get('cursor', 'start')}-{params['publishedFrom']}",
            url=str(response.url),
            payload=payload,
            metadata={
                "cursor": cursor,
                "count": len(payload.get("releases", [])),
                "query_id": query.query_id,
                "query_text": query.rendered_query_text,
                "abstract_query_text": query.abstract_query_text,
                "query_family": query.query_family,
                "phase": query.phase,
                "target_field": query.target_field,
                "renderer": query.renderer,
            },
        )
        next_cursor = None
        links = payload.get("links", {})
        if isinstance(links, dict) and links.get("next"):
            next_cursor = links["next"]
        elif isinstance(links, list):
            for link in links:
                if link.get("rel") == "next" and link.get("href"):
                    next_cursor = link["href"]
                    break
        return FetchBatch(documents=[document], next_cursor=next_cursor)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        package = self._load_json(payload)
        acquisition_method = getattr(getattr(source, "acquisition_method", None), "value", None)
        source_name = getattr(source, "name", self.source_name)
        metadata = getattr(raw_document, "metadata_json", {}) or {}
        evidence: list[ExtractedEvidence] = []
        for release in package.get("releases", []):
            tender = release.get("tender", {})
            buyer = release.get("buyer", {})
            parties = {party.get("id"): party for party in release.get("parties", [])}
            buyer_party = parties.get(buyer.get("id")) if buyer.get("id") else None
            buyer_name = buyer.get("name") or (buyer_party or {}).get("name")
            buyer_country = ((buyer_party or {}).get("address", {}) or {}).get("countryName")
            value = tender.get("value") or {}
            cpv_codes = []
            if tender.get("classification", {}).get("id"):
                cpv_codes.append(tender["classification"]["id"])
            lot_titles = []
            for item in tender.get("items", []):
                code = item.get("classification", {}).get("id")
                if code:
                    cpv_codes.append(code)
                if item.get("description"):
                    lot_titles.append(item["description"])
            detail_url = raw_document.canonical_url
            contact_email = None
            contact_name = None
            if buyer_party:
                contact_point = buyer_party.get("contactPoint") or {}
                if isinstance(contact_point, dict):
                    contact_email = contact_point.get("email")
                    contact_name = contact_point.get("name")
            procurement_id = tender.get("id") or release.get("ocid")
            evidence.append(
                ExtractedEvidence(
                    title=tender.get("title") or release.get("id") or "Contracts Finder notice",
                    summary=tender.get("description"),
                    buyer_name=buyer_name,
                    buyer_country=buyer_country,
                    notice_type=(release.get("tag") or ["notice"])[0],
                    procurement_type=tender.get("procurementMethodDetails") or tender.get("procurementMethod"),
                    publication_date=self._parse_dt(release.get("date")),
                    close_date=self._parse_dt((tender.get("tenderPeriod") or {}).get("endDate")),
                    budget_value=Decimal(str(value["amount"])) if value.get("amount") is not None else None,
                    budget_currency=value.get("currency"),
                    source_url=detail_url,
                    response_url=detail_url,
                    attachment_urls=[],
                    attachment_metadata=[],
                    contact_name=contact_name,
                    contact_email=contact_email,
                    cpv_codes=sorted(set(cpv_codes)),
                    lot_titles=lot_titles,
                    classification_codes=sorted(set(cpv_codes)),
                    tags=release.get("tag", []),
                    procurement_id=procurement_id,
                    raw_excerpt=(tender.get("description") or "")[:1500] or None,
                    acquisition_method=acquisition_method,
                    source_provenance={"upstream": source_name, "raw_document": raw_document.canonical_url},
                    discovery_query_id=metadata.get("query_id"),
                    discovery_query_text=metadata.get("query_text"),
                    extracted_data=release,
                )
            )
        return evidence
