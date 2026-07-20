from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from d365opps.config import get_settings
from d365opps.schemas import EnrichmentResult
from d365opps.taxonomy import COUNTRY_TO_REGION


def normalize_name(name: str | None) -> str:
    if not name:
        return "unknown"
    lowered = re.sub(r"\b(ltd|limited|inc|corp|corporation|llc|plc|gmbh|sa|pte)\b", "", name.lower())
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def extract_domain(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        if "@" in value and "://" not in value:
            return value.split("@", 1)[1].lower()
        parsed = urlparse(value)
        if parsed.netloc:
            return parsed.netloc.lower()
    return None


class GleifEnricher:
    endpoint = "https://api.gleif.org/api/v1/fuzzycompletions"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=get_settings().http_timeout_seconds,
            headers={"User-Agent": get_settings().user_agent},
        )

    def search(self, organization_name: str) -> dict | None:
        response = self.client.get(
            self.endpoint,
            params={"field": "entity.legalName", "q": organization_name},
        )
        response.raise_for_status()
        payload = response.json()
        return payload["data"][0] if payload.get("data") else None


class OpportunityEnricher:
    def __init__(self, gleif: GleifEnricher | None = None) -> None:
        self.settings = get_settings()
        self.gleif = gleif or GleifEnricher()

    def enrich(self, *, buyer_name: str | None, source_url: str, contact_email: str | None, country: str | None) -> EnrichmentResult:
        org_name = buyer_name or "Unknown organization"
        normalized = normalize_name(org_name)
        domain = extract_domain(contact_email, source_url)
        provenance: dict[str, object] = {"source": "pipeline", "source_url": source_url}
        registry_payload: dict[str, object] = {}
        confidence = 0.35
        if self.settings.gleif_enabled and buyer_name:
            try:
                result = self.gleif.search(buyer_name)
                if result:
                    registry_payload = result
                    confidence = 0.65
                    provenance["gleif_match"] = result
            except httpx.HTTPError as exc:
                provenance["gleif_error"] = str(exc)
        region = COUNTRY_TO_REGION.get((country or "").upper())
        return EnrichmentResult(
            organization_name=org_name,
            normalized_name=normalized,
            website_domain=domain,
            country=country,
            region=region,
            enrichment_confidence=confidence,
            provenance=provenance,
            public_contacts=[],
        )
