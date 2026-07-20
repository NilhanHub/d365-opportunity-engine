from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from d365opps.classifier import OpportunityClassifier
from d365opps.models import AcquisitionMethod, Lane, ParsingMode, SourceRegistry
from d365opps.retrieval import RetrievalScorer
from d365opps.schemas import ExtractedEvidence


@dataclass(slots=True)
class EvaluationReport:
    precision: float
    recall: float
    false_positive_rate: float
    false_negative_examples: list[dict[str, Any]]
    by_lane: dict[str, dict[str, float]]
    by_source: dict[str, dict[str, float]]
    by_workload: dict[str, dict[str, float]]
    totals: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "false_positive_rate": self.false_positive_rate,
            "false_negative_examples": self.false_negative_examples,
            "by_lane": self.by_lane,
            "by_source": self.by_source,
            "by_workload": self.by_workload,
            "totals": self.totals,
        }


class RecallHarness:
    def __init__(
        self,
        *,
        retrieval_scorer: RetrievalScorer | None = None,
        classifier: OpportunityClassifier | None = None,
    ) -> None:
        self.retrieval_scorer = retrieval_scorer or RetrievalScorer()
        self.classifier = classifier or OpportunityClassifier()

    def run_fixture_file(self, path: str | Path) -> EvaluationReport:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return self.run_cases(payload)

    def run_cases(self, cases: list[dict[str, Any]]) -> EvaluationReport:
        tp = fp = tn = fn = 0
        false_negatives: list[dict[str, Any]] = []
        by_lane_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        by_source_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        by_workload_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})

        for case in cases:
            source_name = case.get("source_name", "test_source")
            source = self._source_stub(source_name)
            evidence = ExtractedEvidence.model_validate(case["evidence"])
            assessment = self.retrieval_scorer.assess(evidence, source)
            result = None
            if assessment.passes_signal_threshold:
                enriched = evidence.model_copy(
                    update={
                        "retrieval_score": assessment.retrieval_score,
                        "formal_opportunity_score": assessment.formal_opportunity_score,
                        "pre_position_score": assessment.pre_position_score,
                        "account_intent_score": assessment.account_intent_score,
                        "install_base_trigger_score": assessment.install_base_trigger_score,
                        "service_fit_score": assessment.service_fit_score,
                        "buyer_quality_score": assessment.buyer_quality_score,
                        "corroboration_score": assessment.corroboration_score,
                        "source_trust": assessment.source_trust,
                        "matched_positive_terms": list(assessment.matched_positive_terms),
                        "matched_negative_terms": list(assessment.matched_negative_terms),
                        "language_status": assessment.language_status,
                        "english_evidence_source": assessment.english_evidence_source,
                        "discovery_query_id": assessment.query_id,
                        "discovery_query_text": assessment.query_text,
                        "query_family": assessment.query_family,
                        "source_discovery_confidence": assessment.source_discovery_confidence,
                        "signal_lane": assessment.signal_lane.value if assessment.signal_lane else None,
                        "recommended_action": assessment.recommended_action.value,
                        "route_to_market": assessment.route_to_market.value,
                        "account_heat_score": assessment.account_heat_score,
                        "installed_product_guess": assessment.installed_product_guess,
                        "installed_product_evidence": assessment.installed_product_evidence,
                        "trigger_type": assessment.trigger_type,
                        "trigger_strength": assessment.trigger_strength,
                        "procurement_cycle_stage": assessment.procurement_cycle_stage,
                        "vehicle_type": assessment.vehicle_type,
                        "incumbent_vendor": assessment.incumbent_vendor,
                        "incumbent_expiry_guess": assessment.incumbent_expiry_guess,
                        "buyer_intent_evidence": assessment.buyer_intent_evidence,
                        "legacy_evidence": assessment.legacy_evidence,
                        "portal_fingerprint": assessment.portal_fingerprint,
                        "public_access_mode": assessment.public_access_mode.value,
                        "known_blind_spot_reason": assessment.known_blind_spot_reason,
                        "exclusion_reason": assessment.exclusion_reason,
                    }
                )
                result = self.classifier.classify(enriched, source_lane=source.lane.value, default_region=source.region)
            predicted_positive = bool(
                assessment.passes_opportunity_threshold
                and result
                and result.opportunity is not None
                and result.opportunity.evidence_grade != "C1"
            )
            expected_positive = case["label"] == "positive"
            workload = case.get("workload", "unknown")
            lane = case.get("lane") or (assessment.signal_lane.value if assessment.signal_lane else "unknown")

            if expected_positive and predicted_positive:
                tp += 1
                by_lane_counts[lane]["tp"] += 1
                by_source_counts[source_name]["tp"] += 1
                by_workload_counts[workload]["tp"] += 1
            elif not expected_positive and predicted_positive:
                fp += 1
                by_lane_counts[lane]["fp"] += 1
                by_source_counts[source_name]["fp"] += 1
                by_workload_counts[workload]["fp"] += 1
            elif expected_positive and not predicted_positive:
                fn += 1
                false_negatives.append(
                    {
                        "id": case.get("id"),
                        "title": evidence.title,
                        "source_name": source_name,
                        "reason": assessment.exclusion_reason or "below_threshold",
                        "retrieval_score": assessment.retrieval_score,
                    }
                )
                by_lane_counts[lane]["fn"] += 1
                by_source_counts[source_name]["fn"] += 1
                by_workload_counts[workload]["fn"] += 1
            else:
                tn += 1
                by_lane_counts[lane]["tn"] += 1
                by_source_counts[source_name]["tn"] += 1
                by_workload_counts[workload]["tn"] += 1

        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        false_positive_rate = fp / max(fp + tn, 1)
        return EvaluationReport(
            precision=round(precision, 4),
            recall=round(recall, 4),
            false_positive_rate=round(false_positive_rate, 4),
            false_negative_examples=false_negatives,
            by_lane={name: self._metrics(counts) for name, counts in by_lane_counts.items()},
            by_source={name: self._metrics(counts) for name, counts in by_source_counts.items()},
            by_workload={name: self._metrics(counts) for name, counts in by_workload_counts.items()},
            totals={"tp": tp, "fp": fp, "fn": fn, "tn": tn, "cases": len(cases)},
        )

    def _metrics(self, counts: dict[str, int]) -> dict[str, float]:
        precision = counts["tp"] / max(counts["tp"] + counts["fp"], 1)
        recall = counts["tp"] / max(counts["tp"] + counts["fn"], 1)
        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "tp": counts["tp"],
            "fp": counts["fp"],
            "fn": counts["fn"],
            "tn": counts["tn"],
        }

    def _source_stub(self, source_name: str) -> SourceRegistry:
        return SourceRegistry(
            name=source_name,
            description="fixture source",
            lane=Lane.OPPORTUNITY,
            tier=1,
            region="Global",
            country=None,
            enabled=True,
            is_seed=True,
            cadence="daily",
            acquisition_method=AcquisitionMethod.API,
            parsing_mode=ParsingMode.JSON,
            endpoint=f"https://{source_name}.example.test",
        )
