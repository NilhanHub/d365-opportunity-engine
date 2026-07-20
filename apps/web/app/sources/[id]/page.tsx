import { notFound } from "next/navigation";
import { ApiRecord, fetchJson } from "@/lib/api";
import { DataGridTable } from "@/components/data-grid-table";
import { MiniBars } from "@/components/mini-chart";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";

export default async function SourceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let source: ApiRecord;
  try {
    source = await fetchJson<ApiRecord>(`/api/sources/${id}`);
  } catch {
    notFound();
  }

  return (
    <>
      <PageHeader title={source.name} subtitle={source.description ?? "Source detail and run-level evidence."} />
      <section className="triple-grid">
        <Panel title="Identity" description="Config, access, and provenance.">
          <DataGridTable
            rows={[
              { id: "endpoint", field: "Endpoint", value: source.endpoint },
              { id: "method", field: "Acquisition", value: source.acquisition_method },
              { id: "parsing", field: "Parsing", value: source.parsing_mode },
              { id: "family", field: "Source Family", value: source.source_family },
              { id: "access", field: "Public Access", value: source.public_access_mode },
              { id: "robots", field: "Robots", value: source.robots_status }
            ]}
            columns={[
              { key: "field", label: "Field" },
              { key: "value", label: "Value" }
            ]}
          />
        </Panel>
        <Panel title="Health Timeline" description="Daily operational and yield history.">
          <MiniBars
            items={(source.health_timeline ?? []).map((row: ApiRecord) => ({
              date: row.date,
              count: row.documents_fetched
            }))}
            labelKey="date"
            valueKey="count"
          />
        </Panel>
        <Panel title="Recent Queries" description="Compiled query output observed on this source.">
          <DataGridTable
            rows={source.query_executions ?? []}
            columns={[
              { key: "query_family", label: "Family" },
              { key: "query_text", label: "Query" },
              { key: "docs", label: "Docs", type: "number" },
              { key: "evidence", label: "Evidence", type: "number" },
              { key: "opps", label: "Opps", type: "number" }
            ]}
          />
        </Panel>
      </section>
      <section className="split-grid">
        <Panel title="Run History" description="Most recent crawl runs and job runs for this source.">
          <DataGridTable
            rows={source.runs ?? []}
            itemLinkBase="/runs"
            columns={[
              { key: "started_at", label: "Started" },
              { key: "status", label: "Status", type: "status" },
              { key: "documents_fetched", label: "Docs", type: "number" },
              { key: "evidence_extracted", label: "Evidence", type: "number" },
              { key: "candidates_created", label: "Candidates", type: "number" },
              { key: "errors", label: "Errors", type: "number" }
            ]}
          />
        </Panel>
        <Panel title="Issues" description="Normalized blocker taxonomy for this source.">
          <DataGridTable
            rows={source.issues ?? []}
            columns={[
              { key: "issue_code", label: "Issue" },
              { key: "severity", label: "Severity", type: "status" },
              { key: "state", label: "State", type: "status" },
              { key: "frequency", label: "Frequency", type: "number" },
              { key: "recommended_remediation", label: "Recommended Fix" }
            ]}
          />
        </Panel>
      </section>
      <section className="split-grid">
        <Panel title="Yield Funnel" description="Requests through approved output.">
          <DataGridTable
            rows={Object.entries(source.yield_funnel ?? {}).map(([key, value]) => ({ id: key, stage: key, value }))}
            columns={[
              { key: "stage", label: "Stage" },
              { key: "value", label: "Count", type: "number" }
            ]}
          />
        </Panel>
        <Panel title="Field Completeness" description="How complete extracted evidence is for key fields.">
          <DataGridTable
            rows={Object.entries(source.field_completeness ?? {}).map(([key, value]) => ({ id: key, field: key, value }))}
            columns={[
              { key: "field", label: "Field" },
              { key: "value", label: "Completeness", type: "number" }
            ]}
          />
        </Panel>
      </section>
      <section className="split-grid">
        <Panel title="Recent Evidence" description="Extracted rows with drillable provenance.">
          <DataGridTable
            rows={source.recent_evidence ?? []}
            columns={[
              { key: "title", label: "Title" },
              { key: "buyer", label: "Buyer" },
              { key: "publication_date", label: "Published" },
              { key: "close_date", label: "Close" },
              { key: "retrieval_score", label: "Retrieval", type: "number" }
            ]}
          />
        </Panel>
        <Panel title="Recent Opportunities" description="Output from this source after retrieval, extraction, and classification.">
          <DataGridTable
            rows={source.recent_opportunities ?? []}
            itemLinkBase="/opportunities"
            columns={[
              { key: "title", label: "Title" },
              { key: "recommended_action", label: "Action", type: "status" },
              { key: "signal_lane", label: "Lane", type: "status" },
              { key: "opportunity_score", label: "Score", type: "number" }
            ]}
          />
        </Panel>
      </section>
    </>
  );
}
