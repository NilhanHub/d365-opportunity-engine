"use client";

import { useState } from "react";
import { Button } from "@fluentui/react-components";
import { postJson } from "@/lib/api";

export function CandidateReviewList({
  items
}: {
  items: Array<{ id: string; candidate_name: string; country?: string; confidence?: number }>;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function handle(path: string, candidateId: string) {
    setPending(candidateId);
    setMessage(null);
    try {
      await postJson(path, { candidate_id: candidateId });
      setMessage("Candidate source updated. Refresh the page to see the new state.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Action failed.");
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="summary-pair">
      {items.map((item) => (
        <div key={item.id} className="review-row">
          <div>
            <div><strong>{item.candidate_name}</strong></div>
            <div className="muted">
              {item.country ?? "unknown"} · confidence {item.confidence ?? 0}
            </div>
          </div>
          <div className="page-header-actions">
            <Button disabled={pending === item.id} onClick={() => handle("/api/actions/approve-source", item.id)}>
              Approve
            </Button>
            <Button appearance="secondary" disabled={pending === item.id} onClick={() => handle("/api/actions/reject-source", item.id)}>
              Reject
            </Button>
          </div>
        </div>
      ))}
      {message ? <div className="muted">{message}</div> : null}
    </div>
  );
}
