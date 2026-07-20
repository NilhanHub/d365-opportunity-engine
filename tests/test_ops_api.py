from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from d365opps import api
from d365opps.db import Base
from d365opps.demo import ensure_demo_data
from d365opps.ops import OpsService


def make_session(tmp_path: Path) -> Session:
    db_path = tmp_path / "ops-api.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    ensure_demo_data(session)
    session.commit()
    session.close()
    return SessionLocal()


def test_ops_service_exposes_expected_states(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    ops = OpsService(session)

    overview = ops.overview()
    sources = ops.list_sources(limit=200, offset=0)["items"]

    assert overview["kpis"]["opportunity_candidates_created"] >= 3
    assert overview["kpis"]["market_signals_created"] >= 2
    assert overview["data_mode"] == "DEMO"
    assert overview["kpis"]["demo_records"] > 0
    states = {row["operational_state"] for row in sources}
    assert {"healthy", "throttled", "blocked", "auth_required", "unsupported"} <= states


def test_api_endpoints_return_demo_data(tmp_path: Path, monkeypatch) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'api.db'}", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        ensure_demo_data(session)
        session.commit()

    monkeypatch.setattr(api, "SessionLocal", SessionLocal)
    monkeypatch.setattr(api, "init_db", lambda: Base.metadata.create_all(engine))

    with TestClient(api.app) as client:
        overview = client.get("/api/overview")
        assert overview.status_code == 200
        assert overview.json()["kpis"]["documents_fetched_7d"] > 0

        status = client.get("/api/status")
        assert status.status_code == 200
        assert status.json()["data_mode"] == "DEMO"

        sources = client.get("/api/sources?limit=20")
        assert sources.status_code == 200
        assert sources.json()["total"] >= 6

        discovery = client.get("/api/discovery/candidates?limit=20")
        assert discovery.status_code == 200
        candidate_id = discovery.json()["items"][0]["id"]

        approve = client.post("/api/actions/approve-source", json={"candidate_id": candidate_id, "enable_source": False})
        assert approve.status_code == 200
        assert approve.json()["status"] == "enabled"

        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "d365_sources_total" in metrics.text
        assert "d365_demo_records" in metrics.text

        diagnostics = client.get("/api/diagnostics")
        assert diagnostics.status_code == 200
        assert "empty_dataset_diagnosis" in diagnostics.json()

        verify = client.get("/api/verification/latest")
        assert verify.status_code == 200
        assert "bundle_path" in verify.json()

        purge = client.post("/api/actions/purge-demo")
        assert purge.status_code == 200
        assert purge.json()["opportunities"] >= 1

        class DummyRequest:
            async def is_disconnected(self) -> bool:
                return False

        stream = asyncio.run(api.stream_runs(DummyRequest(), limit=5, interval=1))
        assert stream.media_type == "text/event-stream"
        first_chunk = asyncio.run(stream.body_iterator.__anext__())
        assert first_chunk.startswith("data: ")
