"use client";

import { useEffect, useMemo, useState } from "react";
import { Body1, Caption1, Spinner } from "@fluentui/react-components";
import { DataGridTable } from "@/components/data-grid-table";
import { Panel } from "@/components/panel";
import { apiBase, ApiList } from "@/lib/api";

type RunRow = Record<string, unknown>;

export function LiveRunsPanel({ initialRuns }: { initialRuns: ApiList<RunRow> }) {
  const [runs, setRuns] = useState<ApiList<RunRow>>(initialRuns);
  const [connectionState, setConnectionState] = useState<"connecting" | "live" | "offline">("connecting");
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  useEffect(() => {
    const stream = new EventSource(`${apiBase}/api/runs/stream?limit=${runs.limit ?? 200}&interval=3`);
    stream.onopen = () => setConnectionState("live");
    stream.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as ApiList<RunRow>;
        setRuns(payload);
        setLastUpdated(new Date().toLocaleTimeString());
      } catch {
        setConnectionState("offline");
      }
    };
    stream.onerror = () => {
      setConnectionState("offline");
      stream.close();
    };
    return () => stream.close();
  }, [runs.limit]);

  const activeRuns = useMemo(
    () => runs.items.filter((row) => ["running", "started", "queued"].includes(String(row.status ?? "").toLowerCase())).length,
    [runs.items]
  );

  return (
    <Panel
      title="Runs"
      description={`${runs.total ?? runs.items.length} recent runs. ${activeRuns} active. Connection: ${connectionState}.`}
      actions={
        <div className="live-indicator" aria-live="polite">
          {connectionState === "connecting" ? <Spinner size="tiny" /> : null}
          <Body1>{connectionState === "live" ? "Live" : connectionState === "offline" ? "Offline" : "Connecting"}</Body1>
          <Caption1 className="muted">{lastUpdated ? `Updated ${lastUpdated}` : "Waiting for first stream event"}</Caption1>
        </div>
      }
    >
      <DataGridTable
        rows={runs.items ?? []}
        itemLinkBase="/runs"
        columns={[
          { key: "started_at", label: "Started" },
          { key: "run_type", label: "Run Type" },
          { key: "job_type", label: "Job" },
          { key: "status", label: "Status", type: "status" },
          { key: "documents_fetched", label: "Docs", type: "number" },
          { key: "evidence_extracted", label: "Evidence", type: "number" },
          { key: "candidates_created", label: "Candidates", type: "number" },
          { key: "errors", label: "Errors", type: "number" },
          { key: "duration_ms", label: "Duration ms", type: "number" }
        ]}
      />
    </Panel>
  );
}
