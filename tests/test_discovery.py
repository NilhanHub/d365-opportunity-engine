from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import httpx

from d365opps.db import Base
from d365opps.discovery import SourceDiscoveryService
from d365opps.models import AcquisitionMethod, Lane, ParsingMode, SourceRegistry


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return SessionLocal()


def test_discovery_finds_feed_and_sitemap_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == "/procurement":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <link rel="alternate" type="application/rss+xml" href="/feed.xml" />
                  </head>
                  <body>
                    <a href="/supplier-portal">Supplier Portal</a>
                    <a href="/procurement/tenders">Tender opportunities</a>
                  </body>
                </html>
                """,
            )
        if request.url.path == "/sitemap.xml":
            return httpx.Response(
                200,
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://buyer.example/procurement/tenders</loc></url>
                </urlset>
                """,
                headers={"content-type": "application/xml"},
            )
        return httpx.Response(200, text="<html><body>ok</body></html>")

    session = make_session()
    source = SourceRegistry(
        name="generic_web",
        description="discovery seed",
        lane=Lane.SIGNAL,
        tier=2,
        region="Global",
        country="GB",
        enabled=True,
        is_seed=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.HTML,
        parsing_mode=ParsingMode.HTML,
        endpoint="https://buyer.example/procurement",
    )
    session.add(source)
    session.commit()

    service = SourceDiscoveryService(session, client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    candidates = service.discover_sources(source_names=["generic_web"], limit=10)

    endpoints = {item.endpoint for item in candidates}
    assert "https://buyer.example/feed.xml" in endpoints
    assert "https://buyer.example/sitemap.xml" in endpoints
    assert any(item.provenance_json.get("upstream_source") == "generic_web" for item in candidates)
    assert any(item.discovery_mode in {"rss_autodiscovery", "link_graph"} for item in candidates)


def test_discovery_detects_hosted_portal_fingerprint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(
            200,
            text="""
            <html>
              <body>
                <a href="https://supplier.coupa.com/sourcing-events">Public sourcing event</a>
              </body>
            </html>
            """,
        )

    session = make_session()
    source = SourceRegistry(
        name="generic_web",
        description="discovery seed",
        lane=Lane.SIGNAL,
        tier=2,
        region="Global",
        country="GB",
        enabled=True,
        is_seed=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.HTML,
        parsing_mode=ParsingMode.HTML,
        endpoint="https://buyer.example/procurement",
    )
    session.add(source)
    session.commit()

    service = SourceDiscoveryService(session, client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    candidates = service.discover_sources(source_names=["generic_web"], limit=10)

    coupa = next(item for item in candidates if "coupa.com" in item.endpoint)
    assert coupa.portal_fingerprint == "coupa"
    assert coupa.public_access_mode.value == "public"
