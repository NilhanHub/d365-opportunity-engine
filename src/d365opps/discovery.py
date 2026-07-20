from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from d365opps.config import get_settings
from d365opps.models import (
    AcquisitionMethod,
    CrawlRun,
    DiscoveryStatus,
    EvidenceRecord,
    Lane,
    ParsingMode,
    PublicAccessMode,
    RadarLane,
    SourceDiscoveryCandidate,
    SourceRegistry,
)


PROCUREMENT_HINTS = (
    "procurement",
    "tender",
    "tenders",
    "contract",
    "contracts",
    "supplier",
    "vendors",
    "rfp",
    "rfq",
    "opportunity",
    "business-opportunity",
)

PRE_POSITION_HINTS = (
    "framework",
    "vendor registration",
    "supplier onboarding",
    "standing offer",
    "supply arrangement",
    "procurement plan",
    "award",
    "renewal",
    "incumbent",
    "prior information",
)

DIRECT_OUTREACH_HINTS = (
    "careers",
    "job",
    "digital transformation",
    "strategy",
    "budget",
    "board",
    "minutes",
    "press release",
    "market engagement",
    "rfi",
)

PORTAL_FINGERPRINTS = {
    "coupa": ("coupa.com", "supplier.coupa", "sourcing event"),
    "ariba": ("ariba.com", "sap business network discovery", "discovery.ariba"),
    "jaggaer": ("jaggaer",),
    "ivalua": ("ivalua",),
    "mercell": ("mercell",),
    "delta_esourcing": ("delta-esourcing",),
    "in_tend": ("in-tend", "in-tendhost"),
    "bonfire": ("bonfirehub", "gobonfire"),
    "proactis": ("proactis",),
    "bidsandtenders": ("bidsandtenders",),
    "eu_supply": ("eu-supply",),
    "oracle_procurement": ("oracle procurement", "oraclecloud"),
    "epps": ("epps",),
}


class SourceDiscoveryService:
    def __init__(self, session: Session, client: httpx.Client | None = None) -> None:
        settings = get_settings()
        self.session = session
        self.client = client or httpx.Client(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        )
        self.settings = settings

    def discover_sources(
        self,
        *,
        source_names: list[str] | None = None,
        limit: int | None = None,
        auto_enable_threshold: float = 0.95,
    ) -> list[SourceDiscoveryCandidate]:
        limit = limit or self.settings.source_discovery_limit
        statement = select(SourceRegistry).order_by(SourceRegistry.tier, SourceRegistry.name)
        if source_names:
            statement = statement.where(SourceRegistry.name.in_(source_names))
        sources = list(self.session.execute(statement).scalars())
        discovered: list[SourceDiscoveryCandidate] = []
        for source in sources:
            candidates = self._discover_from_url(source, source.endpoint)
            for candidate in candidates:
                record = self._upsert_candidate(source, candidate, auto_enable_threshold=auto_enable_threshold)
                discovered.append(record)
                if len(discovered) >= limit:
                    return discovered
        for source_url in self._existing_buyer_pages(limit=max(10, limit // 2)):
            synthetic = SourceRegistry(
                name=f"buyer-seed-{_safe_name(source_url)}",
                description="Existing buyer page seed",
                lane=Lane.SIGNAL,
                tier=2,
                region="Global",
                country=None,
                enabled=False,
                is_seed=False,
                cadence="manual",
                acquisition_method=AcquisitionMethod.HTML,
                parsing_mode=ParsingMode.HTML,
                endpoint=source_url,
            )
            for candidate in self._discover_from_url(synthetic, source_url):
                record = self._upsert_candidate(None, candidate, auto_enable_threshold=auto_enable_threshold)
                discovered.append(record)
                if len(discovered) >= limit:
                    return discovered
        return discovered

    def source_health(self, *, enabled_only: bool = False) -> list[dict[str, object]]:
        statement = select(SourceRegistry).order_by(SourceRegistry.tier, SourceRegistry.name)
        if enabled_only:
            statement = statement.where(SourceRegistry.enabled.is_(True))
        rows = list(self.session.execute(statement).scalars())
        health: list[dict[str, object]] = []
        for source in rows:
            latest_run = self.session.execute(
                select(CrawlRun).where(CrawlRun.source_id == source.id).order_by(CrawlRun.started_at.desc()).limit(1)
            ).scalar_one_or_none()
            error_count = len((latest_run.errors_json if latest_run else []) or [])
            health.append(
                {
                    "name": source.name,
                    "enabled": source.enabled,
                    "health_status": source.health_status.value,
                    "last_successful_fetch_at": source.last_successful_fetch_at,
                    "last_attempted_fetch_at": source.last_attempted_fetch_at,
                    "robots_status": source.robots_status,
                    "rate_limit_per_minute": source.rate_limit_per_minute,
                    "latest_run_status": latest_run.status.value if latest_run else None,
                    "latest_run_errors": error_count,
                    "source_discovery_confidence": source.source_discovery_confidence,
                }
            )
        return health

    def _discover_from_url(self, source: SourceRegistry, url: str) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        robots_status = self._robots_status(url)
        if robots_status == "blocked":
            return []
        try:
            response = self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return []
        content_type = response.headers.get("content-type", "")
        body = response.text
        parsed_candidates = []
        if "xml" in content_type.lower() or url.lower().endswith(".xml") or "<urlset" in body or "<rss" in body:
            parsed_candidates.extend(self._discover_from_xml(source, url, body, content_type))
        else:
            parsed_candidates.extend(self._discover_from_html(source, url, body))
            sitemap_url = urljoin(f"{urlparse(url).scheme}://{urlparse(url).netloc}", "/sitemap.xml")
            if sitemap_url != url:
                parsed_candidates.append(
                    {
                        "candidate_name": _safe_name(sitemap_url),
                        "endpoint": sitemap_url,
                        "acquisition_method": AcquisitionMethod.SITEMAP,
                        "parsing_mode": ParsingMode.XML,
                        "region": source.region,
                        "country": source.country,
                        "language_support": ["en"],
                        "content_types": ["application/xml"],
                        "robots_status": self._robots_status(sitemap_url),
                        "access_notes": "Default sitemap probe derived from procurement surface.",
                        "confidence": 0.62,
                        "auto_enable_eligible": False,
                        "provenance": {"upstream_source": source.name, "discovered_from": url, "method": "default_sitemap"},
                    }
                )
        for candidate in parsed_candidates:
            candidate["robots_status"] = candidate.get("robots_status") or robots_status
            candidates.append(candidate)
        return candidates

    def _discover_from_html(self, source: SourceRegistry, url: str, body: str) -> list[dict[str, object]]:
        soup = BeautifulSoup(body, "html.parser")
        candidates: list[dict[str, object]] = []
        seen: set[str] = set()
        candidates.extend(self._discover_structured_data(source, url, soup))
        for tag in soup.find_all(["a", "link"], href=True):
            href = urljoin(url, tag["href"])
            if href in seen or not href.startswith(("http://", "https://")):
                continue
            seen.add(href)
            label = tag.get_text(" ", strip=True) if hasattr(tag, "get_text") else ""
            rel = " ".join(tag.get("rel", [])).lower() if tag.name == "link" else ""
            content_type = tag.get("type", "")
            if "rss" in rel or "atom" in rel or "rss" in content_type.lower() or "atom" in content_type.lower():
                candidates.append(
                    self._candidate(
                        source,
                        href,
                        label or "rss_feed",
                        AcquisitionMethod.RSS,
                        ParsingMode.RSS,
                        url,
                        discovery_mode="rss_autodiscovery",
                    )
                )
                continue
            if self._is_procurement_surface(href, label):
                method, parsing = self._mode_for_url(href)
                candidates.append(
                    self._candidate(
                        source,
                        href,
                        label or href,
                        method,
                        parsing,
                        url,
                        discovery_mode=self._discovery_mode_for_link(href, label),
                    )
                )
        return candidates

    def _discover_from_xml(
        self,
        source: SourceRegistry,
        url: str,
        body: str,
        content_type: str,
    ) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return candidates
        if root.tag.endswith("rss") or root.tag.endswith("feed") or "<rss" in body:
            candidates.append(
                self._candidate(
                    source,
                    url,
                    "rss_feed",
                    AcquisitionMethod.RSS,
                    ParsingMode.RSS,
                    url,
                    confidence=0.86,
                    discovery_mode="rss_autodiscovery",
                )
            )
            return candidates
        for loc in root.findall(".//{*}loc"):
            if not loc.text:
                continue
            href = loc.text.strip()
            if not self._is_procurement_surface(href, href):
                continue
            method, parsing = self._mode_for_url(href)
            confidence = 0.72 if "sitemap" in content_type.lower() or "urlset" in body else 0.65
            candidates.append(
                self._candidate(
                    source,
                    href,
                    href,
                    method,
                    parsing,
                    url,
                    confidence=confidence,
                    discovery_mode="sitemap",
                )
            )
        return candidates

    def _candidate(
        self,
        source: SourceRegistry,
        href: str,
        label: str,
        acquisition_method: AcquisitionMethod,
        parsing_mode: ParsingMode,
        discovered_from: str,
        *,
        confidence: float | None = None,
        discovery_mode: str | None = None,
    ) -> dict[str, object]:
        score = confidence if confidence is not None else self._confidence_for_candidate(href, label)
        signal_lane = self._signal_lane_for_link(href, label)
        portal_fingerprint = self._portal_fingerprint(href, label)
        return {
            "candidate_name": _safe_name(href),
            "endpoint": href,
            "acquisition_method": acquisition_method,
            "parsing_mode": parsing_mode,
            "region": source.region,
            "country": source.country,
            "source_family": portal_fingerprint or source.source_family or "public_web",
            "signal_lane": signal_lane.value if signal_lane else None,
            "discovery_mode": discovery_mode or "link_graph",
            "portal_fingerprint": portal_fingerprint,
            "public_access_mode": self._public_access_mode(portal_fingerprint),
            "language_support": ["en"] if "/en" in href.lower() or "english" in label.lower() else [],
            "content_types": self._content_types_for_mode(parsing_mode),
            "robots_status": self._robots_status(href),
            "access_notes": f"Discovered from {discovered_from}",
            "confidence": round(score, 3),
            "auto_enable_eligible": score >= 0.93,
            "known_blind_spot_reason": None if portal_fingerprint is None else "Hosted sourcing portal may expose only public or free-account surfaces.",
            "provenance": {
                "upstream_source": source.name,
                "discovered_from": discovered_from,
                "label": label,
                "portal_fingerprint": portal_fingerprint,
            },
        }

    def _upsert_candidate(
        self,
        upstream_source: SourceRegistry | None,
        candidate: dict[str, object],
        *,
        auto_enable_threshold: float,
    ) -> SourceDiscoveryCandidate:
        existing = self.session.execute(
            select(SourceDiscoveryCandidate).where(SourceDiscoveryCandidate.endpoint == candidate["endpoint"])
        ).scalar_one_or_none()
        if existing:
            existing.confidence = max(existing.confidence, float(candidate["confidence"]))
            existing.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
            existing.provenance_json = _merge_json(existing.provenance_json, candidate["provenance"])
            existing.robots_status = candidate.get("robots_status") or existing.robots_status
            existing.source_family = candidate.get("source_family") or existing.source_family
            if candidate.get("signal_lane"):
                existing.signal_lane = RadarLane(candidate["signal_lane"])
            existing.discovery_mode = candidate.get("discovery_mode") or existing.discovery_mode
            existing.portal_fingerprint = candidate.get("portal_fingerprint") or existing.portal_fingerprint
            existing.public_access_mode = PublicAccessMode(candidate.get("public_access_mode", existing.public_access_mode.value))
            existing.known_blind_spot_reason = candidate.get("known_blind_spot_reason") or existing.known_blind_spot_reason
            return existing
        record = SourceDiscoveryCandidate(
            upstream_source_id=upstream_source.id if upstream_source else None,
            candidate_name=str(candidate["candidate_name"]),
            endpoint=str(candidate["endpoint"]),
            acquisition_method=candidate["acquisition_method"],
            parsing_mode=candidate["parsing_mode"],
            region=candidate.get("region"),
            country=candidate.get("country"),
            source_family=candidate.get("source_family"),
            signal_lane=RadarLane(candidate["signal_lane"]) if candidate.get("signal_lane") else None,
            discovery_mode=candidate.get("discovery_mode"),
            portal_fingerprint=candidate.get("portal_fingerprint"),
            public_access_mode=PublicAccessMode(candidate.get("public_access_mode", "public")),
            language_support_json=list(candidate.get("language_support", [])),
            content_types_json=list(candidate.get("content_types", [])),
            robots_status=candidate.get("robots_status"),
            access_notes=candidate.get("access_notes"),
            confidence=float(candidate["confidence"]),
            auto_enable_eligible=bool(candidate.get("auto_enable_eligible")),
            known_blind_spot_reason=candidate.get("known_blind_spot_reason"),
            provenance_json=dict(candidate.get("provenance", {})),
        )
        if record.auto_enable_eligible and record.confidence >= auto_enable_threshold:
            self._auto_enable(record)
        self.session.add(record)
        self.session.flush()
        return record

    def _auto_enable(self, candidate: SourceDiscoveryCandidate) -> None:
        existing = self.session.execute(select(SourceRegistry).where(SourceRegistry.endpoint == candidate.endpoint)).scalar_one_or_none()
        if existing:
            candidate.discovery_status = DiscoveryStatus.ENABLED
            return
        source = SourceRegistry(
            name=candidate.candidate_name,
            description=f"Auto-discovered source from {candidate.provenance_json.get('discovered_from', 'discovery')}",
            lane=Lane.SIGNAL,
            tier=2,
            region=candidate.region,
            country=candidate.country,
            enabled=False,
            is_seed=False,
            cadence="manual",
            acquisition_method=candidate.acquisition_method,
            parsing_mode=candidate.parsing_mode,
            endpoint=candidate.endpoint,
            legal_notes="Auto-discovered public source. Review before enabling.",
            access_notes=candidate.access_notes,
            source_family=candidate.source_family,
            robots_status=candidate.robots_status,
            public_access_mode=candidate.public_access_mode,
            language_support_json=candidate.language_support_json,
            content_types_json=candidate.content_types_json,
            supported_lanes_json=[candidate.signal_lane.value] if candidate.signal_lane else [],
            discovery_provenance_json=candidate.provenance_json,
            source_discovery_confidence=candidate.confidence,
            rate_limit_per_minute=4,
            rate_limit_policy_json={"burst": 1, "per_minute": 4},
            source_capability_json={"discovery_mode": candidate.discovery_mode, "portal_fingerprint": candidate.portal_fingerprint},
            config_json={},
            known_blind_spot_reason=candidate.known_blind_spot_reason,
        )
        self.session.add(source)
        candidate.discovery_status = DiscoveryStatus.ENABLED

    def _robots_status(self, url: str) -> str:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = self.client.get(robots_url)
            if response.status_code >= 400:
                return "unknown"
            parser = robotparser.RobotFileParser()
            parser.parse(response.text.splitlines())
            return "allowed" if parser.can_fetch(self.settings.user_agent, url) else "blocked"
        except httpx.HTTPError:
            return "unknown"

    def _existing_buyer_pages(self, *, limit: int) -> list[str]:
        statement = (
            select(EvidenceRecord.source_url)
            .group_by(EvidenceRecord.source_url)
            .order_by(func.max(EvidenceRecord.publication_date).desc().nullslast())
            .limit(limit)
        )
        return [row[0] for row in self.session.execute(statement).all()]

    def _discover_structured_data(self, source: SourceRegistry, url: str, soup: BeautifulSoup) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                payload = json.loads(script.string or "")
            except (TypeError, ValueError):
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                schema_type = str(item.get("@type", "")).lower() if isinstance(item, dict) else ""
                if schema_type == "jobposting":
                    candidates.append(
                        self._candidate(
                            source,
                            url,
                            str(item.get("title") or item.get("name") or "job_posting"),
                            AcquisitionMethod.HTML,
                            ParsingMode.HTML,
                            url,
                            confidence=0.74,
                            discovery_mode="structured_data",
                        )
                    )
                if schema_type == "dataset":
                    candidates.append(
                        self._candidate(
                            source,
                            url,
                            str(item.get("name") or "dataset"),
                            AcquisitionMethod.DATASET,
                            ParsingMode.JSON,
                            url,
                            confidence=0.76,
                            discovery_mode="structured_data",
                        )
                    )
        return candidates

    def _mode_for_url(self, url: str) -> tuple[AcquisitionMethod, ParsingMode]:
        lowered = url.lower()
        if lowered.endswith(".xml") or "sitemap" in lowered:
            return AcquisitionMethod.SITEMAP, ParsingMode.XML
        if lowered.endswith(".rss") or lowered.endswith(".atom") or "feed" in lowered:
            return AcquisitionMethod.RSS, ParsingMode.RSS
        if lowered.endswith(".json") or "/api/" in lowered:
            return AcquisitionMethod.API, ParsingMode.JSON
        return AcquisitionMethod.HTML, ParsingMode.HTML

    def _content_types_for_mode(self, parsing_mode: ParsingMode) -> list[str]:
        if parsing_mode == ParsingMode.XML:
            return ["application/xml"]
        if parsing_mode == ParsingMode.RSS:
            return ["application/rss+xml", "application/atom+xml", "application/xml"]
        if parsing_mode == ParsingMode.JSON:
            return ["application/json"]
        return ["text/html"]

    def _confidence_for_candidate(self, href: str, label: str) -> float:
        host = urlparse(href).hostname or ""
        score = 0.35
        if host.endswith((".gov", ".gov.uk", ".gc.ca", ".gov.au")):
            score += 0.3
        elif host.endswith(".int"):
            score += 0.25
        elif host.endswith(".org"):
            score += 0.15
        hint_hits = sum(1 for token in PROCUREMENT_HINTS if token in href.lower() or token in label.lower())
        score += min(0.25, hint_hits * 0.05)
        if "/en" in href.lower() or "english" in label.lower():
            score += 0.05
        if "feed" in href.lower() or "rss" in href.lower() or "atom" in href.lower():
            score += 0.08
        if "sitemap" in href.lower():
            score += 0.04
        return min(0.99, score)

    def _is_procurement_surface(self, href: str, label: str) -> bool:
        text = f"{href} {label}".lower()
        return any(token in text for token in (*PROCUREMENT_HINTS, *PRE_POSITION_HINTS, *DIRECT_OUTREACH_HINTS))

    def _signal_lane_for_link(self, href: str, label: str) -> RadarLane | None:
        text = f"{href} {label}".lower()
        if any(token in text for token in PROCUREMENT_HINTS):
            return RadarLane.FORMAL_PROCUREMENT
        if any(token in text for token in PRE_POSITION_HINTS):
            return RadarLane.PRE_POSITIONING
        if any(token in text for token in DIRECT_OUTREACH_HINTS):
            return RadarLane.DIRECT_OUTREACH
        if any(token in text for token in ("navision", "dynamics ax", "dynamics crm", "great plains", "on-premises")):
            return RadarLane.INSTALL_BASE_TRIGGER
        return None

    def _discovery_mode_for_link(self, href: str, label: str) -> str:
        text = f"{href} {label}".lower()
        if any(token in text for token in ("sitemap",)):
            return "sitemap"
        if any(token in text for token in ("rss", "atom", "feed")):
            return "rss_autodiscovery"
        if any(token in text for token in DIRECT_OUTREACH_HINTS):
            return "lane_specific"
        return "link_graph"

    def _portal_fingerprint(self, href: str, label: str) -> str | None:
        text = f"{href} {label}".lower()
        for name, markers in PORTAL_FINGERPRINTS.items():
            if any(marker in text for marker in markers):
                return name
        return None

    def _public_access_mode(self, portal_fingerprint: str | None) -> str:
        if portal_fingerprint in {"ariba", "jaggaer", "oracle_procurement"}:
            return PublicAccessMode.ACCOUNT_OPTIONAL.value
        if portal_fingerprint in {"unsupported"}:
            return PublicAccessMode.UNSUPPORTED.value
        return PublicAccessMode.PUBLIC.value


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned[:100] or "discovered_source"


def _merge_json(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    merged = dict(left or {})
    for key, value in right.items():
        if key not in merged:
            merged[key] = value
            continue
        if merged[key] == value:
            continue
        merged[key] = [merged[key], value] if not isinstance(merged[key], list) else [*merged[key], value]
    return json.loads(json.dumps(merged))
