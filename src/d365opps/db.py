from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from d365opps.config import get_settings


Base = declarative_base()

settings = get_settings()
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


RUNTIME_COLUMN_UPGRADES: dict[str, dict[str, str]] = {
    "source_registry": {
        "is_seed": "BOOLEAN DEFAULT 1",
        "legal_notes": "TEXT",
        "access_notes": "TEXT",
        "source_family": "VARCHAR(64)",
        "rate_limit_per_minute": "INTEGER",
        "health_status": "VARCHAR(32)",
        "public_access_mode": "VARCHAR(32)",
        "last_successful_fetch_at": "DATETIME",
        "last_attempted_fetch_at": "DATETIME",
        "robots_status": "VARCHAR(64)",
        "language_support_json": "JSON",
        "content_types_json": "JSON",
        "supported_lanes_json": "JSON",
        "discovery_provenance_json": "JSON",
        "source_discovery_confidence": "FLOAT",
        "search_capabilities_json": "JSON",
        "source_capability_json": "JSON",
        "rate_limit_policy_json": "JSON",
        "config_json": "JSON",
        "known_blind_spot_reason": "TEXT",
        "source_authenticity_class": "VARCHAR(32)",
        "canonical_allowed": "BOOLEAN DEFAULT 0",
    },
    "job_run": {
        "trace_id": "VARCHAR(64)",
        "request_id": "VARCHAR(64)",
        "mode": "VARCHAR(64)",
        "source_names_json": "JSON",
        "budget_json": "JSON",
        "query_count": "INTEGER",
        "sources_attempted": "INTEGER",
        "sources_succeeded": "INTEGER",
        "sources_failed": "INTEGER",
        "sources_zero_yield": "INTEGER",
        "sources_untested": "INTEGER",
        "run_reason": "VARCHAR(128)",
        "initiated_by": "VARCHAR(128)",
        "verification_bundle_path": "VARCHAR(1024)",
        "verification_bundle_sha256": "VARCHAR(64)",
        "diagnostic_summary_json": "JSON",
        "run_kind": "VARCHAR(64)",
        "evidence_class": "VARCHAR(64)",
        "oracle_admissible": "BOOLEAN",
        "admissibility_fail_reasons_json": "JSON",
    },
    "source_fetch_event": {
        "trace_id": "VARCHAR(64)",
        "span_id": "VARCHAR(64)",
        "request_id": "VARCHAR(64)",
        "query_id": "VARCHAR(64)",
        "query_family": "VARCHAR(64)",
        "page_index": "INTEGER",
        "cursor_in": "VARCHAR(255)",
        "cursor_out": "VARCHAR(255)",
        "parent_url": "VARCHAR(1024)",
        "detail_url": "VARCHAR(1024)",
        "bytes_received": "INTEGER",
        "bytes_stored": "INTEGER",
        "request_headers_redacted_json": "JSON",
        "response_headers_redacted_json": "JSON",
        "rate_limit_headers_json": "JSON",
        "response_body_sha256": "VARCHAR(64)",
        "response_blob_path": "VARCHAR(1024)",
        "adapter_name": "VARCHAR(128)",
        "adapter_version": "VARCHAR(32)",
        "stage": "VARCHAR(64)",
        "list_or_detail": "VARCHAR(32)",
        "attempt_number": "INTEGER",
        "backoff_ms": "INTEGER",
        "network_error_stage": "VARCHAR(64)",
        "http_protocol": "VARCHAR(32)",
        "tls_error_flag": "BOOLEAN",
        "dns_error_flag": "BOOLEAN",
        "transport_error_flag": "BOOLEAN",
    },
    "source_issue": {
        "trace_id": "VARCHAR(64)",
        "request_id": "VARCHAR(64)",
    },
    "query_execution": {
        "renderer": "VARCHAR(64)",
        "abstract_query_text": "TEXT",
        "rendered_query_text": "TEXT",
        "was_executed": "BOOLEAN",
        "skip_reason": "VARCHAR(128)",
        "watermark_in": "VARCHAR(255)",
        "watermark_out": "VARCHAR(255)",
        "cursor_count": "INTEGER",
        "duplicate_fetches_avoided": "INTEGER",
        "browse_only_pass": "BOOLEAN",
        "status": "VARCHAR(64)",
        "trace_id": "VARCHAR(64)",
    },
    "evidence_record": {
        "current_actionability_state": "VARCHAR(64)",
        "english_sufficiency_score": "FLOAT",
        "english_shell_only_flag": "BOOLEAN",
        "seller_readable_summary_en": "TEXT",
        "seller_readable_title_en_flag": "BOOLEAN",
    },
    "opportunity_candidate": {
        "account_cluster_id": "VARCHAR(36)",
        "current_actionability_state": "VARCHAR(64)",
        "english_sufficiency_score": "FLOAT",
        "english_shell_only_flag": "BOOLEAN",
        "seller_readable_summary_en": "TEXT",
        "seller_readable_title_en_flag": "BOOLEAN",
        "sales_handoff_state": "VARCHAR(32) DEFAULT 'reject'",
    },
    "opportunity_cluster": {
        "account_cluster_id": "VARCHAR(36)",
    },
}


def _upgrade_runtime_schema() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table_name, columns in RUNTIME_COLUMN_UPGRADES.items():
            if not inspector.has_table(table_name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, sql_type in columns.items():
                if column_name in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}"))


def init_db() -> None:
    from d365opps import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _upgrade_runtime_schema()


@contextmanager
def session_scope() -> Session:
    _upgrade_runtime_schema()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
