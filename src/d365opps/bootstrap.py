from __future__ import annotations

import json
from collections.abc import Iterable
from importlib import resources
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from d365opps.authenticity import classify_source_authenticity
from d365opps.models import AcquisitionMethod, Lane, ParsingMode, PublicAccessMode, SourceRegistry


def load_source_specs() -> tuple[dict[str, Any], ...]:
    payload = json.loads(resources.files("d365opps.data").joinpath("source_pack.json").read_text(encoding="utf-8"))
    return tuple(_coerce_source_spec(spec) for spec in payload)

def _coerce_source_spec(spec: dict[str, Any]) -> dict[str, Any]:
    cooked = dict(spec)
    cooked["lane"] = Lane(cooked["lane"])
    cooked["acquisition_method"] = AcquisitionMethod(cooked["acquisition_method"])
    cooked["parsing_mode"] = ParsingMode(cooked["parsing_mode"])
    if cooked.get("public_access_mode"):
        cooked["public_access_mode"] = PublicAccessMode(cooked["public_access_mode"])
    return cooked


DEFAULT_SOURCES = load_source_specs()


def seed_sources(session: Session, specs: Iterable[dict[str, Any]] | None = None) -> list[SourceRegistry]:
    created: list[SourceRegistry] = []
    for spec in specs or DEFAULT_SOURCES:
        authenticity = classify_source_authenticity(
            name=spec.get("name"),
            endpoint=spec.get("endpoint"),
            source_family=spec.get("source_family"),
            public_access_mode=(spec.get("public_access_mode").value if hasattr(spec.get("public_access_mode"), "value") else spec.get("public_access_mode")),
            data_mode="demo" if str(spec.get("name", "")).startswith("demo_") else "live",
        )
        spec = {
            **spec,
            "source_authenticity_class": authenticity.authenticity_class,
            "canonical_allowed": authenticity.canonical_allowed,
        }
        existing = session.execute(select(SourceRegistry).where(SourceRegistry.name == spec["name"])).scalar_one_or_none()
        if existing:
            for key, value in spec.items():
                setattr(existing, key, value)
            created.append(existing)
            continue
        source = SourceRegistry(**spec)
        session.add(source)
        created.append(source)
    session.flush()
    return created
