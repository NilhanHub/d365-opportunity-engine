from __future__ import annotations

from datetime import datetime

from prefect import flow

from d365opps.db import session_scope
from d365opps.pipeline import PipelineService


@flow(name="d365-opps-refresh")
def refresh_flow(source_names: list[str] | None = None, region: str | None = None, since: datetime | None = None):
    with session_scope() as session:
        service = PipelineService(session)
        return service.refresh(source_names=source_names, region=region, since=since)


@flow(name="d365-opps-reprocess")
def reprocess_flow(document_id: str):
    with session_scope() as session:
        service = PipelineService(session)
        return service.reprocess(document_id)


@flow(name="d365-opps-export")
def export_flow(fmt: str = "both", filters: dict | None = None):
    with session_scope() as session:
        service = PipelineService(session)
        return service.export(fmt=fmt, filters=filters or {})
