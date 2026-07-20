import { notFound } from "next/navigation";
import { DataGridTable } from "@/components/data-grid-table";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { ApiRecord, fetchJson } from "@/lib/api";

export default async function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let run: ApiRecord;
  try {
    run = await fetchJson<ApiRecord>(`/api/runs/${id}`);
  } catch {
    notFound();
  }

  return (
    <>
      <PageHeader title={`Run ${id}`} subtitle="Run timeline, fetch events, query activity, and output details." />
      <section className="split-grid">
        <Panel title="Run Summary" description="Top-level counters and metadata.">
          <DataGridTable
            rows={[
              { id: "type", field: "Run Type", value: run.run_type },
              { id: "job", field: "Job Type", value: run.job_type },
              { id: "status", field: "Status", value: run.status },
              { id: "started", field: "Started", value: run.started_at },
              { id: "finished", field: "Finished", value: run.finished_at },
              { id: "duration", field: "Duration ms", value: run.duration_ms }
            ]}
            columns={[
              { key: "field", label: "Field" },
              { key: "value", label: "Value" }
            ]}
          />
        </Panel>
        <Panel title="Query Execution" description="Observed query traffic within this run.">
          <DataGridTable
            rows={run.query_executions ?? []}
            columns={[
              { key: "query_family", label: "Family" },
              { key: "query_text", label: "Query" },
              { key: "docs", label: "Docs", type: "number" },
              { key: "opps", label: "Opps", type: "number" },
              { key: "signals", label: "Signals", type: "number" }
            ]}
          />
        </Panel>
      </section>
      <Panel title="Fetch Events" description="One row per request attempt where recorded.">
        <DataGridTable
          rows={run.fetch_events ?? []}
          columns={[
            { key: "timestamp", label: "Time" },
            { key: "request_url", label: "Request" },
            { key: "response_status_code", label: "Status", type: "number" },
            { key: "latency_ms", label: "Latency ms", type: "number" },
            { key: "issue_code", label: "Issue", type: "status" },
            { key: "documents_emitted", label: "Docs", type: "number" },
            { key: "evidence_emitted", label: "Evidence", type: "number" }
          ]}
        />
      </Panel>
    </>
  );
}
