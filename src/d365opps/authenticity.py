from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


PLACEHOLDER_HOSTS = {
    "example.com",
    "www.example.com",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
}
PLACEHOLDER_NAME_MARKERS = (
    "duplicate",
    "fixture",
    "example",
    "demo",
    "test",
    "sample",
    "verification",
)
THIRD_PARTY_HOST_SUFFIXES = (
    "opentender.eu",
    "data.open-contracting.org",
)
OFFICIAL_HOST_SUFFIXES = (
    "service.gov.uk",
    "api.ted.europa.eu",
    "ted.europa.eu",
    "etenders.gov.ie",
    "hankintailmoitukset.fi",
    "tenderned.nl",
    "gets.govt.nz",
    "canadabuys.canada.ca",
    "worldbank.org",
    "projects.worldbank.org",
    "ungm.org",
    "funding-tenders.ec.europa.eu",
    "gebiz.gov.sg",
    "jamaicaeps.gov.jm",
    "ppip.go.ke",
    "etenders.gov.za",
    "eprocure.gov.in",
)


@dataclass(slots=True)
class SourceAuthenticity:
    authenticity_class: str
    canonical_allowed: bool
    host: str | None
    reasons: list[str]


def normalize_host(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.netloc or parsed.path or "").strip().lower()
    if ":" in host:
        host = host.split(":", 1)[0]
    return host or None


def is_placeholder_host(host: str | None) -> bool:
    if not host:
        return False
    return host in PLACEHOLDER_HOSTS or host.endswith(".example.com")


def contains_placeholder_name(name: str | None) -> bool:
    lowered = (name or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in PLACEHOLDER_NAME_MARKERS)


def classify_domain(host: str | None) -> str:
    if is_placeholder_host(host):
        return "synthetic_fixture"
    if not host:
        return "unknown"
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in OFFICIAL_HOST_SUFFIXES):
        return "official_public"
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in THIRD_PARTY_HOST_SUFFIXES):
        return "third_party_mirror"
    return "unknown"


def classify_source_authenticity(
    *,
    name: str | None,
    endpoint: str | None,
    source_family: str | None,
    public_access_mode: str | None,
    data_mode: str | None = None,
) -> SourceAuthenticity:
    host = normalize_host(endpoint)
    reasons: list[str] = []
    lowered_family = (source_family or "").strip().lower()
    lowered_mode = (data_mode or "").strip().lower()
    if lowered_mode == "demo" or (name or "").strip().lower().startswith("demo_"):
        reasons.append("demo_mode_source")
        return SourceAuthenticity("demo_seed", False, host, reasons)
    if contains_placeholder_name(name):
        reasons.append("placeholder_name_marker")
    if is_placeholder_host(host):
        reasons.append("placeholder_host")
    if reasons and ("placeholder_host" in reasons or "placeholder_name_marker" in reasons):
        return SourceAuthenticity("synthetic_fixture", False, host, reasons)
    domain_class = classify_domain(host)
    if domain_class == "official_public":
        return SourceAuthenticity("official_public", True, host, ["official_host"])
    if lowered_family.startswith("official_") and public_access_mode in {"public", None} and not is_placeholder_host(host):
        reasons.append("official_source_family")
        return SourceAuthenticity("official_public", True, host, reasons)
    if domain_class == "third_party_mirror" or lowered_family in {"registry", "search_api"}:
        reasons.append("registry_or_mirror")
        return SourceAuthenticity("third_party_mirror", False, host, reasons)
    return SourceAuthenticity("unknown", False, host, reasons or ["unclassified_source"])


def classify_row_authenticity(
    *,
    source_name: str | None,
    source_url: str | None,
    endpoint: str | None = None,
    source_family: str | None = None,
    public_access_mode: str | None = None,
    data_mode: str | None = None,
) -> SourceAuthenticity:
    primary = classify_source_authenticity(
        name=source_name,
        endpoint=endpoint or source_url,
        source_family=source_family,
        public_access_mode=public_access_mode,
        data_mode=data_mode,
    )
    if primary.authenticity_class == "official_public":
        return primary
    row_host = normalize_host(source_url)
    row_class = classify_domain(row_host)
    if row_class == "official_public":
        return SourceAuthenticity("official_public", True, row_host, ["official_source_url"])
    if row_class == "synthetic_fixture":
        return SourceAuthenticity("synthetic_fixture", False, row_host, ["placeholder_source_url"])
    return primary


def is_canonical_authentic_row(row: dict[str, Any]) -> bool:
    return (
        row.get("source_authenticity_class") == "official_public"
        and bool(row.get("canonical_allowed"))
        and row.get("row_evidence_class") == "official_public"
    )
