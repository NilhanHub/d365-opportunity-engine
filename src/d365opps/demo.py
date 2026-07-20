from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from d365opps.bootstrap import seed_sources
from d365opps.config import get_settings
from d365opps.models import (
    AccountCluster,
    AcquisitionMethod,
    CandidateStatus,
    Contact,
    CrawlRun,
    CrawlStatus,
    DiscoveryStatus,
    EvidenceRecord,
    IssueSeverity,
    JobRun,
    JobType,
    Lane,
    MarketSignal,
    OperationalState,
    OpportunityCandidate,
    OpportunityCluster,
    Organization,
    ParsingMode,
    PublicAccessMode,
    QueryExecution,
    RadarLane,
    RawDocument,
    RecommendedAction,
    RouteToMarket,
    SourceDailyMetric,
    SourceDiscoveryCandidate,
    SourceFetchEvent,
    SourceHealthStatus,
    SourceIssue,
    SourceRegistry,
    UiSavedView,
    YieldState,
)


def ensure_demo_data(session: Session) -> None:
    settings = get_settings()
    seed_sources(session)
    has_demo_records = any(
        (
            session.execute(select(OpportunityCandidate.id).limit(1)).first(),
            session.execute(select(MarketSignal.id).limit(1)).first(),
            session.execute(select(SourceDailyMetric.id).limit(1)).first(),
        )
    )
    if has_demo_records:
        return

    now = datetime.now(UTC).replace(tzinfo=None)
    blob_root = settings.blob_root / "demo"
    blob_root.mkdir(parents=True, exist_ok=True)

    sources = _prepare_sources(session, now)
    accounts = _prepare_accounts(session, now)
    opp_cluster = OpportunityCluster(
        cluster_key="demo-global-d365-transformation",
        canonical_title="Global D365 transformation workstream",
        canonical_buyer="Northbridge Health Authority",
        country="GB",
        first_seen_at=now - timedelta(days=14),
        latest_seen_at=now - timedelta(hours=4),
        evidence_grade="A1",
        aggregate_score=89,
        corroboration_count=2,
        corroborating_sources_json=["contracts_finder", "canada_buys_tenders"],
    )
    session.add(opp_cluster)
    session.flush()

    _seed_source_metrics(session, sources, now)
    _seed_runs_and_events(session, sources, now)
    _seed_issues(session, sources, now)
    _seed_discovery_candidates(session, sources, now)
    _seed_queries(session, sources)
    _seed_saved_views(session)
    _seed_records(session, sources, accounts, opp_cluster, blob_root, now)


def purge_demo_data(session: Session) -> dict[str, int]:
    demo_buyer_names = ["Northbridge Health Authority", "Harbour Transit Agency", "Lighthouse Municipal Services"]
    demo_source_ids = [
        source.id
        for source in session.execute(select(SourceRegistry).where(SourceRegistry.name.like("demo_%"))).scalars()
    ]
    raw_document_statement = select(RawDocument).where(
        RawDocument.canonical_url.like("%example%") | RawDocument.document_url.like("%example%")
    )
    if demo_source_ids:
        raw_document_statement = select(RawDocument).where(
            RawDocument.source_id.in_(demo_source_ids)
            | RawDocument.canonical_url.like("%example%")
            | RawDocument.document_url.like("%example%")
        )
    raw_document_ids = [row.id for row in session.execute(raw_document_statement).scalars()]
    evidence_statement = select(EvidenceRecord).where(
        EvidenceRecord.source_url.like("%example%")
        | EvidenceRecord.response_url.like("%example%")
        | EvidenceRecord.buyer_name.in_(demo_buyer_names)
    )
    if raw_document_ids:
        evidence_statement = select(EvidenceRecord).where(
            EvidenceRecord.raw_document_id.in_(raw_document_ids)
            | EvidenceRecord.source_url.like("%example%")
            | EvidenceRecord.response_url.like("%example%")
            | EvidenceRecord.buyer_name.in_(demo_buyer_names)
        )
    evidence_ids = [row.id for row in session.execute(evidence_statement).scalars()]
    org_ids = [
        row.id
        for row in session.execute(
            select(Organization).where(
                Organization.website_domain.like("%.example%") | Organization.source_name.in_(
                    demo_buyer_names
                )
            )
        ).scalars()
    ]
    account_ids = [
        row.id
        for row in session.execute(select(AccountCluster).where(AccountCluster.website_domain.like("%.example%"))).scalars()
    ]

    counts = {
        "opportunities": 0,
        "signals": 0,
        "evidence": 0,
        "raw_documents": 0,
        "sources": 0,
        "organizations": 0,
        "contacts": 0,
        "accounts": 0,
        "issues": 0,
        "fetch_events": 0,
        "query_executions": 0,
        "daily_metrics": 0,
        "crawl_runs": 0,
        "job_runs": 0,
        "discovery_candidates": 0,
        "saved_views": 0,
    }

    if evidence_ids:
        for row in session.execute(select(OpportunityCandidate).where(OpportunityCandidate.evidence_record_id.in_(evidence_ids))).scalars():
            session.delete(row)
            counts["opportunities"] += 1
        for row in session.execute(select(MarketSignal).where(MarketSignal.evidence_record_id.in_(evidence_ids))).scalars():
            session.delete(row)
            counts["signals"] += 1
        for row in session.execute(select(EvidenceRecord).where(EvidenceRecord.id.in_(evidence_ids))).scalars():
            session.delete(row)
            counts["evidence"] += 1
    if raw_document_ids:
        for row in session.execute(select(RawDocument).where(RawDocument.id.in_(raw_document_ids))).scalars():
            session.delete(row)
            counts["raw_documents"] += 1

    for row in session.execute(select(SourceIssue)).scalars():
        if (row.metadata_json or {}).get("demo"):
            session.delete(row)
            counts["issues"] += 1
    for row in session.execute(select(SourceFetchEvent)).scalars():
        if (row.metadata_json or {}).get("demo"):
            session.delete(row)
            counts["fetch_events"] += 1
    for row in session.execute(select(QueryExecution)).scalars():
        if (row.metadata_json or {}).get("demo"):
            session.delete(row)
            counts["query_executions"] += 1

    if demo_source_ids:
        for row in session.execute(select(SourceDailyMetric).where(SourceDailyMetric.source_id.in_(demo_source_ids))).scalars():
            session.delete(row)
            counts["daily_metrics"] += 1
        for row in session.execute(select(SourceDiscoveryCandidate).where(SourceDiscoveryCandidate.upstream_source_id.in_(demo_source_ids))).scalars():
            session.delete(row)
            counts["discovery_candidates"] += 1
        for row in session.execute(select(CrawlRun).where(CrawlRun.source_id.in_(demo_source_ids))).scalars():
            session.delete(row)
            counts["crawl_runs"] += 1
        for row in session.execute(select(JobRun).where(JobRun.source_id.in_(demo_source_ids))).scalars():
            session.delete(row)
            counts["job_runs"] += 1
        for row in session.execute(select(SourceRegistry).where(SourceRegistry.id.in_(demo_source_ids))).scalars():
            session.delete(row)
            counts["sources"] += 1

    if org_ids:
        for row in session.execute(select(Contact).where(Contact.organization_id.in_(org_ids))).scalars():
            session.delete(row)
            counts["contacts"] += 1
        for row in session.execute(select(Organization).where(Organization.id.in_(org_ids))).scalars():
            session.delete(row)
            counts["organizations"] += 1
    if account_ids:
        for row in session.execute(select(AccountCluster).where(AccountCluster.id.in_(account_ids))).scalars():
            session.delete(row)
            counts["accounts"] += 1
    for row in session.execute(select(UiSavedView).where(UiSavedView.name.in_(["Blocked Sources", "Bid Now This Week"]))).scalars():
        session.delete(row)
        counts["saved_views"] += 1

    session.flush()
    return counts


def _prepare_sources(session: Session, now: datetime) -> dict[str, SourceRegistry]:
    sources = {row.name: row for row in session.execute(select(SourceRegistry)).scalars()}

    for name in ("contracts_finder", "find_a_tender", "ted", "sam_gov", "canada_buys_tenders", "canada_buys_awards"):
        source = sources[name]
        source.enabled = True
        source.last_attempted_fetch_at = now - timedelta(hours=2)
        source.robots_status = "allowed"

    sources["contracts_finder"].last_successful_fetch_at = now - timedelta(minutes=40)
    sources["contracts_finder"].health_status = SourceHealthStatus.HEALTHY

    sources["find_a_tender"].last_successful_fetch_at = now - timedelta(hours=3)
    sources["find_a_tender"].health_status = SourceHealthStatus.DEGRADED

    sources["ted"].last_successful_fetch_at = now - timedelta(hours=8)
    sources["ted"].health_status = SourceHealthStatus.FAILING

    sources["sam_gov"].last_attempted_fetch_at = now - timedelta(minutes=30)
    sources["sam_gov"].public_access_mode = PublicAccessMode.ACCOUNT_REQUIRED
    sources["sam_gov"].health_status = SourceHealthStatus.DEGRADED

    sources["canada_buys_tenders"].last_successful_fetch_at = now - timedelta(hours=6)
    sources["canada_buys_tenders"].health_status = SourceHealthStatus.HEALTHY

    sources["canada_buys_awards"].lane = Lane.SIGNAL
    sources["canada_buys_awards"].enabled = True
    sources["canada_buys_awards"].last_successful_fetch_at = now - timedelta(hours=5)
    sources["canada_buys_awards"].health_status = SourceHealthStatus.HEALTHY

    for spec in (
        {
            "name": "demo_buyer_portal",
            "description": "Direct buyer procurement and strategy pages.",
            "lane": Lane.SIGNAL,
            "tier": 2,
            "region": "Global",
            "country": "SG",
            "enabled": True,
            "is_seed": False,
            "cadence": "daily",
            "acquisition_method": AcquisitionMethod.SITEMAP,
            "parsing_mode": ParsingMode.HTML,
            "endpoint": "https://procurement.example.sg/",
            "source_family": "buyer_portal",
            "public_access_mode": PublicAccessMode.PUBLIC,
            "source_discovery_confidence": 0.83,
            "supported_lanes_json": ["direct_outreach", "install_base_trigger"],
            "language_support_json": ["en"],
            "content_types_json": ["text/html", "application/pdf"],
            "search_capabilities_json": {"supports_query": False},
            "source_capability_json": {"supports_sitemaps": True, "supports_attachments": True},
            "rate_limit_policy_json": {"per_minute": 8},
            "config_json": {"query_profile": "buyer_portal"},
            "health_status": SourceHealthStatus.HEALTHY,
            "robots_status": "allowed",
            "last_successful_fetch_at": now - timedelta(hours=2),
            "last_attempted_fetch_at": now - timedelta(hours=1),
        },
        {
            "name": "demo_blocked_portal",
            "description": "Hosted sourcing surface that is publicly referenced but currently blocking access.",
            "lane": Lane.OPPORTUNITY,
            "tier": 3,
            "region": "Europe",
            "country": "IE",
            "enabled": True,
            "is_seed": False,
            "cadence": "daily",
            "acquisition_method": AcquisitionMethod.HTML,
            "parsing_mode": ParsingMode.HTML,
            "endpoint": "https://blocked.example.ie/sourcing",
            "source_family": "hosted_portal",
            "public_access_mode": PublicAccessMode.PUBLIC,
            "source_discovery_confidence": 0.71,
            "supported_lanes_json": ["formal_procurement"],
            "language_support_json": ["en"],
            "content_types_json": ["text/html"],
            "search_capabilities_json": {"supports_query": False},
            "source_capability_json": {"portal_fingerprint": "jaggaer"},
            "rate_limit_policy_json": {"per_minute": 2},
            "config_json": {"portal_fingerprint": "jaggaer"},
            "health_status": SourceHealthStatus.FAILING,
            "robots_status": "allowed",
            "last_attempted_fetch_at": now - timedelta(minutes=45),
        },
        {
            "name": "demo_unsupported_portal",
            "description": "Known major portal with invitation-only access.",
            "lane": Lane.SIGNAL,
            "tier": 4,
            "region": "North America",
            "country": "US",
            "enabled": False,
            "is_seed": False,
            "cadence": "manual",
            "acquisition_method": AcquisitionMethod.HTML,
            "parsing_mode": ParsingMode.HTML,
            "endpoint": "https://invite-only.example.com",
            "source_family": "hosted_portal",
            "public_access_mode": PublicAccessMode.UNSUPPORTED,
            "source_discovery_confidence": 0.64,
            "supported_lanes_json": ["pre_positioning"],
            "language_support_json": ["en"],
            "content_types_json": ["text/html"],
            "search_capabilities_json": {"supports_query": False},
            "source_capability_json": {"portal_fingerprint": "oracle_procurement"},
            "rate_limit_policy_json": {"per_minute": 1},
            "config_json": {},
            "health_status": SourceHealthStatus.UNKNOWN,
            "robots_status": "unknown",
        },
    ):
        existing = session.execute(select(SourceRegistry).where(SourceRegistry.name == spec["name"])).scalar_one_or_none()
        if existing:
            for key, value in spec.items():
                setattr(existing, key, value)
            sources[existing.name] = existing
        else:
            created = SourceRegistry(**spec)
            session.add(created)
            session.flush()
            sources[created.name] = created
    return sources


def _prepare_accounts(session: Session, now: datetime) -> dict[str, AccountCluster]:
    accounts: dict[str, AccountCluster] = {}
    organizations: list[tuple[str, str, str, str, str]] = [
        ("northbridge", "Northbridge Health Authority", "northbridgehealth.example", "GB", "Healthcare"),
        ("harbour", "Harbour Transit Agency", "harbourtransit.example", "CA", "Transport"),
        ("lighthouse", "Lighthouse Municipal Services", "lighthouse.example.sg", "SG", "Public sector"),
    ]
    for key, name, domain, country, industry in organizations:
        organization = Organization(
            source_name=name,
            normalized_name=name.lower(),
            website_domain=domain,
            country=country,
            region=country,
            industry=industry,
            size_band="enterprise",
            registry_payload_json={"demo": True},
            enrichment_confidence=0.82,
            provenance_json={"demo": True},
        )
        session.add(organization)
        session.flush()
        contact = Contact(
            organization_id=organization.id,
            full_name=f"{name.split()[0]} Procurement",
            email=f"procurement@{domain}",
            phone="+1-555-0100",
            role="Procurement lead",
            public_source_url=f"https://{domain}/procurement",
            enrichment_payload_json={"demo": True},
            enrichment_confidence=0.55,
            provenance_json={"demo": True},
        )
        account = AccountCluster(
            cluster_key=domain,
            canonical_name=name,
            website_domain=domain,
            country=country,
            first_seen_at=now - timedelta(days=30),
            latest_seen_at=now - timedelta(hours=4),
            heat_score=78.0 if key == "northbridge" else 64.0 if key == "harbour" else 59.0,
            buyer_quality_score=76.0,
            installed_product_guess="Dynamics NAV" if key == "lighthouse" else None,
            installed_product_evidence="Legacy support page references NAV 2018." if key == "lighthouse" else None,
            trigger_strength=72.0 if key == "lighthouse" else 28.0,
            corroboration_count=2,
        )
        session.add(contact)
        session.add(account)
        session.flush()
        accounts[key] = account
    return accounts


def _seed_source_metrics(session: Session, sources: dict[str, SourceRegistry], now: datetime) -> None:
    profiles = {
        "contracts_finder": (OperationalState.HEALTHY, YieldState.HIGH_YIELD, 18, 14, 3, 4, 0.98, 420, 0.0, 0.0, 0.0, 0.94, 0.92, 9),
        "find_a_tender": (OperationalState.THROTTLED, YieldState.NORMAL_YIELD, 12, 9, 1, 2, 0.72, 930, 0.22, 0.0, 0.0, 0.9, 0.84, 6),
        "ted": (OperationalState.PARSER_BROKEN, YieldState.NOISY, 21, 7, 0, 0, 0.61, 860, 0.0, 0.0, 0.18, 0.66, 0.31, 7),
        "sam_gov": (OperationalState.AUTH_REQUIRED, YieldState.ZERO_YIELD, 0, 0, 0, 0, 0.0, 1100, 0.0, 0.25, 0.0, 0.0, 0.0, 0),
        "canada_buys_tenders": (OperationalState.HEALTHY, YieldState.NORMAL_YIELD, 9, 7, 1, 1, 0.95, 510, 0.0, 0.0, 0.0, 0.96, 0.88, 4),
        "canada_buys_awards": (OperationalState.HEALTHY, YieldState.NORMAL_YIELD, 8, 5, 2, 0, 0.96, 470, 0.0, 0.0, 0.0, 0.92, 0.8, 4),
        "demo_buyer_portal": (OperationalState.HEALTHY, YieldState.LOW_YIELD, 5, 4, 2, 0, 0.97, 390, 0.0, 0.0, 0.0, 0.98, 0.82, 2),
        "demo_blocked_portal": (OperationalState.BLOCKED, YieldState.ZERO_YIELD, 0, 0, 0, 0, 0.0, 700, 0.0, 1.0, 0.0, 0.0, 0.0, 0),
    }
    for source_name, profile in profiles.items():
        source = sources[source_name]
        for days_ago in range(0, 7):
            multiplier = 1.0 if days_ago < 2 else 0.7 if days_ago < 5 else 0.5
            metric = SourceDailyMetric(
                source_id=source.id,
                metric_date=(now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0),
                documents_fetched=int(profile[2] * multiplier),
                evidence_extracted=int(profile[3] * multiplier),
                market_signals_created=int(profile[4] * multiplier),
                opportunities_created=int(profile[5] * multiplier),
                approved_opportunities=int(max(profile[5] - 1, 0) * multiplier),
                success_rate=profile[6],
                avg_latency_ms=profile[7],
                rate_429=profile[8],
                rate_403=profile[9],
                timeout_rate=0.0,
                parser_failure_rate=profile[10],
                english_acceptance_rate=profile[11],
                field_completeness_score=profile[12],
                unique_buyers_found=profile[13],
                operational_state=profile[0],
                yield_state=profile[1],
            )
            session.add(metric)
    session.flush()


def _seed_runs_and_events(session: Session, sources: dict[str, SourceRegistry], now: datetime) -> None:
    scenarios = {
        "contracts_finder": {"status": CrawlStatus.SUCCEEDED, "docs": 18, "evidence": 14, "candidates": 4, "events": [(200, 420, None), (200, 390, None)]},
        "find_a_tender": {"status": CrawlStatus.SUCCEEDED, "docs": 12, "evidence": 9, "candidates": 2, "events": [(429, 920, "throttled_429"), (200, 880, None)]},
        "ted": {"status": CrawlStatus.FAILED, "docs": 4, "evidence": 1, "candidates": 0, "events": [(200, 810, "parser_drift")]},
        "sam_gov": {"status": CrawlStatus.FAILED, "docs": 0, "evidence": 0, "candidates": 0, "events": [(401, 640, "api_key_missing")]},
        "demo_blocked_portal": {"status": CrawlStatus.FAILED, "docs": 0, "evidence": 0, "candidates": 0, "events": [(403, 510, "blocked_403")]},
        "demo_buyer_portal": {"status": CrawlStatus.SUCCEEDED, "docs": 5, "evidence": 4, "candidates": 2, "events": [(200, 380, None)]},
    }
    for source_name, scenario in scenarios.items():
        source = sources[source_name]
        crawl = CrawlRun(
            source_id=source.id,
            started_at=now - timedelta(hours=6),
            finished_at=now - timedelta(hours=5, minutes=45),
            status=scenario["status"],
            cursor=None,
            documents_fetched=scenario["docs"],
            evidence_extracted=scenario["evidence"],
            candidates_created=scenario["candidates"],
            errors_json=[] if scenario["status"] == CrawlStatus.SUCCEEDED else [{"message": "Demo failure", "source": source_name}],
        )
        session.add(crawl)
        session.flush()
        job = JobRun(
            source_id=source.id,
            crawl_run_id=crawl.id,
            job_type=JobType.REFRESH,
            started_at=crawl.started_at,
            finished_at=crawl.finished_at,
            duration_ms=90000,
            status=scenario["status"],
            documents_fetched=scenario["docs"],
            evidence_extracted=scenario["evidence"],
            candidates_created=scenario["candidates"],
            opportunities_created=scenario["candidates"],
            retries=1 if any(item[0] in {401, 403, 429} for item in scenario["events"]) else 0,
            bytes_fetched=scenario["docs"] * 2048,
            errors_json=crawl.errors_json,
            metadata_json={"source_name": source.name},
        )
        session.add(job)
        session.flush()
        for index, (status_code, latency, issue_code) in enumerate(scenario["events"], start=1):
            session.add(
                SourceFetchEvent(
                    source_id=source.id,
                    crawl_run_id=crawl.id,
                    timestamp=now - timedelta(hours=6) + timedelta(minutes=index * 5),
                    request_url=f"{source.endpoint}?page={index}",
                    request_method="GET",
                    response_status_code=status_code,
                    latency_ms=latency,
                    bytes=2048,
                    content_type="application/json" if source.parsing_mode == ParsingMode.JSON else "text/html",
                    was_retry=index > 1,
                    retry_count=1 if index > 1 else 0,
                    robots_status=source.robots_status,
                    parser_used=source.parsing_mode.value,
                    success_flag=status_code == 200 and issue_code is None,
                    issue_code=issue_code,
                    error_class="HTTPError" if status_code >= 400 else None,
                    error_message=f"HTTP {status_code}" if status_code >= 400 else None,
                    english_detected=True if status_code == 200 else None,
                    documents_emitted=max(scenario["docs"] // len(scenario["events"]), 0),
                    evidence_emitted=max(scenario["evidence"] // len(scenario["events"]), 0),
                    metadata_json={"demo": True},
                )
            )
    session.add(
        JobRun(
            job_type=JobType.DISCOVER_SOURCES,
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=2, minutes=-5),
            duration_ms=300000,
            status=CrawlStatus.SUCCEEDED,
            candidates_created=3,
            metadata_json={"mode": "registry+sitemap"},
        )
    )
    session.add(
        JobRun(
            job_type=JobType.EXPORT,
            started_at=now - timedelta(hours=1),
            finished_at=now - timedelta(minutes=55),
            duration_ms=240000,
            status=CrawlStatus.SUCCEEDED,
            opportunities_created=3,
            metadata_json={"directory": "var/exports/demo-20260412"},
        )
    )
    session.flush()


def _seed_issues(session: Session, sources: dict[str, SourceRegistry], now: datetime) -> None:
    issues = [
        ("find_a_tender", "throttled_429", IssueSeverity.HIGH, "Rate limiting is suppressing recall.", "Reduce request burst and prioritize exact-phrase queries."),
        ("ted", "parser_drift", IssueSeverity.HIGH, "Structured payload changed and field mapping is drifting.", "Review latest raw payloads and update notice parser."),
        ("sam_gov", "api_key_missing", IssueSeverity.MEDIUM, "Source is configured but missing credential material.", "Provide a lawful API key or disable the source."),
        ("demo_blocked_portal", "blocked_403", IssueSeverity.HIGH, "Portal is publicly linked but denies crawl access.", "Keep as blocked and search for official mirror or feed."),
        ("canada_buys_awards", "low_yield_suspected", IssueSeverity.LOW, "Awards are visible but D365-specific yield remains modest.", "Keep monitoring for renewal patterns and incumbent clues."),
    ]
    for source_name, issue_code, severity, impact, remediation in issues:
        source = sources[source_name]
        session.add(
            SourceIssue(
                source_id=source.id,
                issue_code=issue_code,
                severity=severity,
                state="open",
                first_seen_at=now - timedelta(days=2),
                last_seen_at=now - timedelta(hours=1),
                frequency=3,
                example_url=source.endpoint,
                example_status_code=429 if issue_code == "throttled_429" else 403 if issue_code == "blocked_403" else 401 if issue_code == "api_key_missing" else 200,
                error_class="DemoIssue",
                error_message=issue_code,
                impact_on_yield=impact,
                recommended_remediation=remediation,
                metadata_json={"demo": True},
            )
        )
    session.flush()


def _seed_discovery_candidates(session: Session, sources: dict[str, SourceRegistry], now: datetime) -> None:
    candidates = [
        {
            "candidate_name": "Coupa Health Procurement Hub",
            "endpoint": "https://northbridgehealth.coupahost.com/suppliers/public_events",
            "acquisition_method": AcquisitionMethod.HTML,
            "parsing_mode": ParsingMode.HTML,
            "region": "UK",
            "country": "GB",
            "source_family": "hosted_portal",
            "signal_lane": RadarLane.FORMAL_PROCUREMENT,
            "discovery_mode": "portal_fingerprint",
            "portal_fingerprint": "coupa",
            "public_access_mode": PublicAccessMode.PUBLIC,
            "language_support_json": ["en"],
            "content_types_json": ["text/html"],
            "robots_status": "allowed",
            "access_notes": "Public events listing appears visible without login.",
            "discovery_status": DiscoveryStatus.PENDING_REVIEW,
            "confidence": 0.87,
            "auto_enable_eligible": False,
            "provenance_json": {"upstream_source": "contracts_finder", "referrer": "https://northbridgehealth.example/procurement"},
        },
        {
            "candidate_name": "Lighthouse Bonfire Sourcing",
            "endpoint": "https://lighthouse.bonfirehub.com/opportunities",
            "acquisition_method": AcquisitionMethod.HTML,
            "parsing_mode": ParsingMode.HTML,
            "region": "Asia Pacific",
            "country": "SG",
            "source_family": "hosted_portal",
            "signal_lane": RadarLane.PRE_POSITIONING,
            "discovery_mode": "sitemap",
            "portal_fingerprint": "bonfire",
            "public_access_mode": PublicAccessMode.PUBLIC,
            "language_support_json": ["en"],
            "content_types_json": ["text/html"],
            "robots_status": "allowed",
            "access_notes": "Discovered in sitemap but not yet reviewed.",
            "discovery_status": DiscoveryStatus.PENDING_REVIEW,
            "confidence": 0.79,
            "auto_enable_eligible": False,
            "provenance_json": {"upstream_source": "demo_buyer_portal", "referrer": "https://procurement.example.sg/sitemap.xml"},
        },
    ]
    for candidate in candidates:
        session.add(
            SourceDiscoveryCandidate(
                upstream_source_id=sources[candidate["provenance_json"]["upstream_source"]].id,
                last_seen_at=now - timedelta(hours=2),
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(hours=2),
                known_blind_spot_reason=None,
                **candidate,
            )
        )
    session.flush()


def _seed_queries(session: Session, sources: dict[str, SourceRegistry]) -> None:
    rows = [
        ("contracts_finder", "formal_anchor", "\"Dynamics 365\" implementation tender", "title", 8, 8, 6, 3, 1),
        ("contracts_finder", "bc_support", "\"Business Central\" managed support", "description", 6, 5, 4, 1, 0),
        ("find_a_tender", "field_service", "\"Dynamics 365 Field Service\" support", "title", 4, 3, 2, 1, 0),
        ("ted", "legacy_modernize", "\"Dynamics AX\" modernisation", "attachment", 7, 5, 2, 0, 0),
        ("demo_buyer_portal", "trigger_hunt", "\"Dynamics NAV\" support OR migration", "page_text", 3, 2, 2, 0, 2),
        ("canada_buys_awards", "award_watch", "\"Dynamics 365\" award notice", "title", 3, 2, 2, 0, 1),
    ]
    for source_name, family, text, target, requests, docs, evidence, opps, signals in rows:
        session.add(
            QueryExecution(
                source_id=sources[source_name].id,
                query_id=f"{family}:demo",
                query_text=text,
                query_family=family,
                phase="runtime",
                target_field=target,
                negatives_applied_json=["sap", "salesforce", "generic crm"],
                requests=requests,
                hits=docs,
                docs=docs,
                evidence=evidence,
                opps=opps,
                signals=signals,
                metadata_json={"demo": True},
            )
        )
    session.flush()


def _seed_saved_views(session: Session) -> None:
    session.add_all(
        [
            UiSavedView(
                name="Blocked Sources",
                route="/sources",
                description="Sources with current blocking or access issues.",
                filters_json={"state": "blocked"},
                columns_json=["name", "country", "operational_state", "recommended_fix"],
                density="compact",
            ),
            UiSavedView(
                name="Bid Now This Week",
                route="/opportunities",
                description="High-scoring formal opportunities closing soon.",
                filters_json={"recommended_action": "bid_now"},
                columns_json=["title", "buyer", "country", "opportunity_score", "close_date"],
                density="compact",
            ),
        ]
    )
    session.flush()


def _seed_records(
    session: Session,
    sources: dict[str, SourceRegistry],
    accounts: dict[str, AccountCluster],
    opp_cluster: OpportunityCluster,
    blob_root: Path,
    now: datetime,
) -> None:
    records = [
        {
            "source": "contracts_finder",
            "account": "northbridge",
            "title": "Dynamics 365 Customer Service and Contact Center implementation",
            "summary": "Buyer is procuring a partner for D365 Customer Service, Contact Center, and telephony integration.",
            "lane": RadarLane.FORMAL_PROCUREMENT,
            "action": RecommendedAction.BID_NOW,
            "route": RouteToMarket.FORMAL_BID,
            "app_family": "Customer Engagement",
            "business_process": "Service to resolution",
            "service_type": "implementation",
            "evidence_grade": "A1",
            "record_type": "tender_notice",
            "country": "GB",
            "buyer": "Northbridge Health Authority",
            "query_family": "formal_anchor",
            "retrieval_score": 91.0,
            "opportunity_score": 88,
            "close_days": 9,
            "budget": 850000,
            "english_source": "title",
            "product_mentions": ["Dynamics 365", "Dynamics 365 Customer Service", "Dynamics 365 Contact Center"],
            "service_mentions": ["implementation", "integration", "training"],
            "signal": False,
        },
        {
            "source": "canada_buys_tenders",
            "account": "harbour",
            "title": "Business Central AMS and integration services",
            "summary": "Transit agency requires Business Central managed support, optimization, and Azure integration work.",
            "lane": RadarLane.FORMAL_PROCUREMENT,
            "action": RecommendedAction.BID_NOW,
            "route": RouteToMarket.FORMAL_BID,
            "app_family": "Business Central",
            "business_process": "Record to report",
            "service_type": "managed support",
            "evidence_grade": "A2",
            "record_type": "rfp",
            "country": "CA",
            "buyer": "Harbour Transit Agency",
            "query_family": "bc_support",
            "retrieval_score": 82.0,
            "opportunity_score": 79,
            "close_days": 14,
            "budget": 420000,
            "english_source": "attachment",
            "product_mentions": ["Business Central", "Power Platform"],
            "service_mentions": ["managed support", "integration", "enhancement"],
            "signal": False,
        },
        {
            "source": "canada_buys_awards",
            "account": "harbour",
            "title": "Award notice for D365 Finance optimization and rollout support",
            "summary": "Recent award indicates incumbent Microsoft-focused ERP optimization work and likely downstream enhancement demand.",
            "lane": RadarLane.PRE_POSITIONING,
            "action": RecommendedAction.PRE_POSITION,
            "route": RouteToMarket.RENEWAL_WATCH,
            "app_family": "Finance",
            "business_process": "Plan to deliver",
            "service_type": "optimization",
            "evidence_grade": "B1",
            "record_type": "award_notice",
            "country": "CA",
            "buyer": "Harbour Transit Agency",
            "query_family": "award_watch",
            "retrieval_score": 71.0,
            "opportunity_score": 65,
            "close_days": 45,
            "budget": 250000,
            "english_source": "summary",
            "product_mentions": ["Dynamics 365 Finance"],
            "service_mentions": ["optimization", "rollout"],
            "signal": False,
        },
        {
            "source": "demo_buyer_portal",
            "account": "northbridge",
            "title": "Northbridge transformation programme seeks implementation partner",
            "summary": "Board papers and strategy pages indicate upcoming partner selection for D365 service transformation.",
            "lane": RadarLane.DIRECT_OUTREACH,
            "action": RecommendedAction.OUTREACH_NOW,
            "route": RouteToMarket.DIRECT_OUTREACH,
            "app_family": "Customer Engagement",
            "business_process": "Service to resolution",
            "service_type": "consulting",
            "evidence_grade": "B1",
            "record_type": "board_paper",
            "country": "GB",
            "buyer": "Northbridge Health Authority",
            "query_family": "trigger_hunt",
            "retrieval_score": 67.0,
            "opportunity_score": 0,
            "close_days": 30,
            "budget": None,
            "english_source": "page",
            "product_mentions": ["Dynamics 365", "Power Platform"],
            "service_mentions": ["roadmap", "partner", "consulting"],
            "signal": True,
            "signal_type": "buyer_intent",
        },
        {
            "source": "demo_buyer_portal",
            "account": "lighthouse",
            "title": "Legacy Dynamics NAV estate indicates migration and AMS demand",
            "summary": "Public support materials and hiring pages reference NAV 2018, integrations, and managed support needs.",
            "lane": RadarLane.INSTALL_BASE_TRIGGER,
            "action": RecommendedAction.OUTREACH_NOW,
            "route": RouteToMarket.DIRECT_OUTREACH,
            "app_family": "Business Central",
            "business_process": "Order to cash",
            "service_type": "migration",
            "evidence_grade": "C1",
            "record_type": "job_posting",
            "country": "SG",
            "buyer": "Lighthouse Municipal Services",
            "query_family": "trigger_hunt",
            "retrieval_score": 63.0,
            "opportunity_score": 0,
            "close_days": 60,
            "budget": None,
            "english_source": "page",
            "product_mentions": ["Dynamics NAV", "Business Central"],
            "service_mentions": ["migration", "managed support", "integration"],
            "signal": True,
            "signal_type": "install_base_trigger",
        },
    ]

    for index, record in enumerate(records, start=1):
        source = sources[record["source"]]
        account = accounts[record["account"]]
        organization = session.execute(
            select(Organization).where(Organization.website_domain == account.website_domain)
        ).scalar_one()
        raw_path = blob_root / f"demo-{index}.txt"
        raw_path.write_text(f"{record['title']}\n\n{record['summary']}", encoding="utf-8")
        raw_document = RawDocument(
            source_id=source.id,
            external_id=f"demo-{index}",
            canonical_url=f"{source.endpoint}/demo/{index}",
            document_url=f"{source.endpoint}/demo/{index}",
            content_type="text/html",
            fetched_at=now - timedelta(hours=index),
            published_at=now - timedelta(days=index),
            checksum=f"demo-{index}",
            blob_path=str(raw_path),
            metadata_json={"demo": True, "query_id": f"{record['query_family']}:demo", "query_text": record["title"]},
        )
        session.add(raw_document)
        session.flush()
        evidence = EvidenceRecord(
            raw_document_id=raw_document.id,
            source_id=source.id,
            record_type=record["record_type"],
            title=record["title"],
            summary=record["summary"],
            buyer_name=record["buyer"],
            buyer_country=record["country"],
            buyer_region=source.region,
            notice_type=record["record_type"],
            procurement_type="RFP" if not record["signal"] else "Signal",
            publication_date=now - timedelta(days=index),
            close_date=now + timedelta(days=record["close_days"]),
            budget_value=record["budget"],
            budget_currency="GBP" if record["country"] == "GB" else "CAD" if record["country"] == "CA" else None,
            source_url=raw_document.canonical_url,
            response_url=f"{raw_document.canonical_url}/respond" if not record["signal"] else raw_document.canonical_url,
            contact_name="Demo Contact",
            contact_email=f"procurement@{account.website_domain}",
            contact_phone="+1-555-0100",
            cpv_codes_json=["72000000"],
            attachment_urls_json=[f"{raw_document.canonical_url}/scope.pdf"],
            attachment_metadata_json=[{"name": "scope.pdf", "content_type": "application/pdf"}],
            lot_titles_json=["Core services"],
            product_mentions_json=record["product_mentions"],
            service_mentions_json=record["service_mentions"],
            classification_codes_json=["crm", "erp"],
            tags_json=["demo", record["lane"].value],
            procurement_id=f"DEMO-{index}",
            raw_excerpt=record["summary"],
            acquisition_method=source.acquisition_method.value,
            source_provenance_json={"source_name": source.name, "demo": True},
            language_status="english",
            language_details_json={"confidence": 0.99},
            english_evidence_source=record["english_source"],
            retrieval_score=record["retrieval_score"],
            formal_opportunity_score=84.0 if record["lane"] == RadarLane.FORMAL_PROCUREMENT else 42.0,
            pre_position_score=73.0 if record["lane"] == RadarLane.PRE_POSITIONING else 18.0,
            account_intent_score=75.0 if record["lane"] == RadarLane.DIRECT_OUTREACH else 24.0,
            install_base_trigger_score=79.0 if record["lane"] == RadarLane.INSTALL_BASE_TRIGGER else 12.0,
            service_fit_score=77.0,
            buyer_quality_score=74.0,
            corroboration_score=68.0,
            source_trust=0.87,
            matched_positive_terms_json=record["product_mentions"] + record["service_mentions"][:2],
            matched_negative_terms_json=[],
            discovery_query_id=f"{record['query_family']}:demo",
            discovery_query_text=record["title"],
            query_family=record["query_family"],
            source_discovery_confidence=source.source_discovery_confidence,
            signal_lane=record["lane"],
            recommended_action=record["action"],
            route_to_market=record["route"],
            account_heat_score=account.heat_score,
            installed_product_guess=account.installed_product_guess,
            installed_product_evidence=account.installed_product_evidence,
            trigger_type="legacy_stack" if record["lane"] == RadarLane.INSTALL_BASE_TRIGGER else "buyer_intent" if record["signal"] else None,
            trigger_strength=account.trigger_strength,
            procurement_cycle_stage="active_solicitation" if record["lane"] == RadarLane.FORMAL_PROCUREMENT else "market_signal",
            vehicle_type="framework" if record["lane"] == RadarLane.PRE_POSITIONING else None,
            incumbent_vendor="Contoso Consulting" if record["lane"] == RadarLane.PRE_POSITIONING else None,
            incumbent_expiry_guess="2027-03" if record["lane"] == RadarLane.PRE_POSITIONING else None,
            buyer_intent_evidence_json={"summary": record["summary"]},
            legacy_evidence_json={"installed_product": account.installed_product_guess} if account.installed_product_guess else {},
            portal_fingerprint="coupa" if source.name == "demo_buyer_portal" else None,
            public_access_mode=source.public_access_mode,
            known_blind_spot_reason=None,
            extracted_json={"demo": True},
        )
        session.add(evidence)
        session.flush()

        if record["signal"]:
            session.add(
                MarketSignal(
                    evidence_record_id=evidence.id,
                    organization_id=organization.id,
                    account_cluster_id=account.id,
                    signal_type=record["signal_type"],
                    signal_lane=record["lane"],
                    recommended_action=record["action"],
                    route_to_market=record["route"],
                    title=record["title"],
                    summary=record["summary"],
                    source_url=evidence.source_url,
                    region=source.region,
                    country=record["country"],
                    confidence=0.79,
                    retrieval_score=record["retrieval_score"],
                    source_trust=0.81,
                    account_heat_score=account.heat_score,
                    trigger_type=evidence.trigger_type,
                    trigger_strength=evidence.trigger_strength,
                    public_access_mode=source.public_access_mode,
                    english_evidence_source=record["english_source"],
                    buyer_intent_evidence_json=evidence.buyer_intent_evidence_json,
                    legacy_evidence_json=evidence.legacy_evidence_json,
                    query_family=record["query_family"],
                    discovery_query_id=evidence.discovery_query_id,
                    discovery_query_text=evidence.discovery_query_text,
                    portal_fingerprint=evidence.portal_fingerprint,
                    known_blind_spot_reason=None,
                    corroboration_count=2,
                    tags_json=["demo", record["lane"].value],
                    raw_excerpt=record["summary"],
                    created_at=now - timedelta(hours=index),
                )
            )
        else:
            session.add(
                OpportunityCandidate(
                    evidence_record_id=evidence.id,
                    organization_id=organization.id,
                    account_cluster_id=account.id,
                    cluster_id=opp_cluster.id if record["lane"] == RadarLane.FORMAL_PROCUREMENT else None,
                    title=record["title"],
                    summary=record["summary"],
                    app_family=record["app_family"],
                    business_process=record["business_process"],
                    service_type=record["service_type"],
                    evidence_grade=record["evidence_grade"],
                    signal_lane=record["lane"],
                    recommended_action=record["action"],
                    route_to_market=record["route"],
                    d365_confidence=0.92,
                    country=record["country"],
                    procurement_type=evidence.procurement_type,
                    publication_date=evidence.publication_date,
                    close_date=evidence.close_date,
                    budget_value=evidence.budget_value,
                    budget_currency=evidence.budget_currency,
                    source_url=evidence.source_url,
                    response_url=evidence.response_url,
                    procurement_id=evidence.procurement_id,
                    raw_excerpt=evidence.raw_excerpt,
                    retrieval_score=evidence.retrieval_score,
                    formal_opportunity_score=evidence.formal_opportunity_score,
                    pre_position_score=evidence.pre_position_score,
                    account_intent_score=evidence.account_intent_score,
                    install_base_trigger_score=evidence.install_base_trigger_score,
                    service_fit_score=evidence.service_fit_score,
                    buyer_quality_score=evidence.buyer_quality_score,
                    corroboration_score=evidence.corroboration_score,
                    opportunity_score=record["opportunity_score"],
                    source_trust=evidence.source_trust,
                    matched_positive_terms_json=evidence.matched_positive_terms_json,
                    matched_negative_terms_json=evidence.matched_negative_terms_json,
                    language_status=evidence.language_status,
                    english_evidence_source=evidence.english_evidence_source,
                    corroboration_count=2 if record["lane"] == RadarLane.FORMAL_PROCUREMENT else 1,
                    discovery_query_id=evidence.discovery_query_id,
                    discovery_query_text=evidence.discovery_query_text,
                    query_family=evidence.query_family,
                    source_discovery_confidence=evidence.source_discovery_confidence,
                    public_access_mode=evidence.public_access_mode,
                    account_heat_score=evidence.account_heat_score,
                    installed_product_guess=evidence.installed_product_guess,
                    installed_product_evidence=evidence.installed_product_evidence,
                    trigger_type=evidence.trigger_type,
                    trigger_strength=evidence.trigger_strength,
                    procurement_cycle_stage=evidence.procurement_cycle_stage,
                    vehicle_type=evidence.vehicle_type,
                    incumbent_vendor=evidence.incumbent_vendor,
                    incumbent_expiry_guess=evidence.incumbent_expiry_guess,
                    buyer_intent_evidence_json=evidence.buyer_intent_evidence_json,
                    legacy_evidence_json=evidence.legacy_evidence_json,
                    portal_fingerprint=evidence.portal_fingerprint,
                    known_blind_spot_reason=None,
                    exclusion_reason=None,
                    score_breakdown_json={"retrieval": record["retrieval_score"], "opportunity": record["opportunity_score"]},
                    total_score=record["opportunity_score"],
                    pursuit_recommendation=record["action"].value,
                    next_action="Review scope and decide pursuit team.",
                    dedupe_fingerprint=f"{record['country']}::{record['title'].lower()}",
                    tags_json=["demo", record["app_family"].lower().replace(" ", "_")],
                    status=CandidateStatus.APPROVED if record["action"] == RecommendedAction.BID_NOW else CandidateStatus.PENDING_REVIEW,
                    created_at=now - timedelta(hours=index),
                    updated_at=now - timedelta(minutes=index * 7),
                )
            )
    session.flush()
