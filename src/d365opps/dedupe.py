from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import datetime

from d365opps.schemas import OpportunityDraft


def normalize_key(value: str | None) -> str:
    if not value:
        return ""
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())


@dataclass(slots=True)
class ClusterDecision:
    cluster_key: str
    canonical_title: str
    canonical_buyer: str | None
    score: int
    country: str | None
    latest_seen_at: datetime | None


class OpportunityClusterer:
    def cluster_key(self, draft: OpportunityDraft) -> str:
        if draft.procurement_id:
            return f"procurement:{draft.procurement_id.lower()}"
        buyer = normalize_key(draft.buyer_name)
        title = normalize_key(draft.title)
        return f"{draft.country or 'XX'}:{buyer}:{title[:120]}"

    def is_same_cluster(self, left: OpportunityDraft, right_title: str, right_buyer: str | None) -> bool:
        title_ratio = difflib.SequenceMatcher(a=left.title.lower(), b=(right_title or "").lower()).ratio()
        buyer_ratio = difflib.SequenceMatcher(a=(left.buyer_name or "").lower(), b=(right_buyer or "").lower()).ratio()
        return title_ratio >= 0.82 and buyer_ratio >= 0.75

    def decide(self, draft: OpportunityDraft) -> ClusterDecision:
        return ClusterDecision(
            cluster_key=self.cluster_key(draft),
            canonical_title=draft.title,
            canonical_buyer=draft.buyer_name,
            score=draft.scorecard.total_score,
            country=draft.country,
            latest_seen_at=draft.publication_date or draft.close_date,
        )
