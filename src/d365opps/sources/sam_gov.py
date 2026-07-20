from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from d365opps.config import get_settings
from d365opps.retrieval import QueryCompiler
from d365opps.schemas import ExtractedEvidence, FetchBatch
from d365opps.sources.base import BaseSourceAdapter


class SamGovSource(BaseSourceAdapter):
    source_name = "sam_gov"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_compiler = QueryCompiler()

    def fetch(self, source, since: datetime, cursor: str | None = None, query=None, budget=None) -> FetchBatch:
        del query, budget
        settings = get_settings()
        if not settings.sam_gov_api_key:
            raise RuntimeError("D365_OPPS_SAM_GOV_API_KEY is required for sam_gov refresh.")
        offset = int(cursor or "0")
        previews = self.query_compiler.compile_for_source(source)
        query_terms = source.config_json.get("query_terms") or [
            term.strip('"')
            for preview in previews[:2]
            for term in preview.required_anchors
        ]
        title_filter = source.config_json.get("title_filter") or " OR ".join(query_terms[:3])
        params: dict[str, Any] = {
            "api_key": settings.sam_gov_api_key,
            "postedFrom": since.astimezone(UTC).strftime("%m/%d/%Y"),
            "postedTo": datetime.now(UTC).strftime("%m/%d/%Y"),
            "limit": source.config_json.get("limit", 100),
            "offset": offset,
            "title": title_filter,
        }
        response = self.client.get(source.endpoint, params=params)
        response.raise_for_status()
        payload = response.json()
        document = self._json_document(
            external_id=f"sam-gov-{offset}-{params['postedFrom']}",
            url=str(response.url),
            payload=payload,
            metadata={"offset": offset, "count": len(payload.get("opportunitiesData", [])), "query_id": previews[0].query_id, "query_text": previews[0].query_text},
        )
        next_offset = None
        if payload.get("totalRecords", 0) > offset + params["limit"]:
            next_offset = str(offset + params["limit"])
        return FetchBatch(documents=[document], next_cursor=next_offset)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        body = self._load_json(payload)
        evidence: list[ExtractedEvidence] = []
        for item in body.get("opportunitiesData", []):
            point = (item.get("pointOfContact") or [{}])[0]
            award = item.get("award") or {}
            amount = award.get("amount")
            resource_links = item.get("resourceLinks") or []
            evidence.append(
                ExtractedEvidence(
                    title=item.get("title") or item.get("solicitationNumber") or "SAM opportunity",
                    summary=item.get("description"),
                    buyer_name=item.get("fullParentPathName") or item.get("department"),
                    buyer_country=(item.get("officeAddress") or {}).get("countryCode"),
                    notice_type=item.get("type"),
                    procurement_type=item.get("type") or item.get("baseType"),
                    publication_date=self._parse_dt(item.get("postedDate")),
                    close_date=self._parse_dt(item.get("responseDeadLine")),
                    budget_value=Decimal(str(amount)) if amount is not None else None,
                    budget_currency="USD" if amount is not None else None,
                    source_url=item.get("uiLink") or raw_document.canonical_url,
                    response_url=item.get("description") or item.get("uiLink"),
                    attachment_urls=resource_links,
                    attachment_metadata=[{"url": link, "title": "resource_link"} for link in resource_links],
                    contact_name=point.get("fullName"),
                    contact_email=point.get("email"),
                    contact_phone=point.get("phone"),
                    cpv_codes=[item["classificationCode"]] if item.get("classificationCode") else [],
                    classification_codes=[item["classificationCode"]] if item.get("classificationCode") else [],
                    tags=["sam_gov", item.get("type", "").lower().replace(" ", "_")],
                    procurement_id=item.get("solicitationNumber") or item.get("noticeId"),
                    raw_excerpt=item.get("description"),
                    acquisition_method=source.acquisition_method.value,
                    source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                    discovery_query_id=raw_document.metadata_json.get("query_id"),
                    discovery_query_text=raw_document.metadata_json.get("query_text"),
                    extracted_data=item,
                )
            )
        return evidence
