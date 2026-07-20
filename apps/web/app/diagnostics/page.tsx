import Link from "next/link";
import { ApiRecord, fetchJson, apiBase } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { DataGridTable } from "@/components/data-grid-table";
import { MiniBars } from "@/components/mini-chart";

export default async function DiagnosticsPage() {
  const diagnostics = await fetchJson<ApiRecord>("/api/diagnostics");
  const empty = diagnostics.empty_dataset_diagnosis ?? {};
  const blockers = diagnostics.top_blockers ?? [];
  const canaries = diagnostics.canary_board ?? [];
  const runs = diagnostics.latest_run_evidence ?? [];
  const sources = diagnostics.source_health_evidence ?? [];
  const readiness = diagnostics.source_readiness_mix ?? {};

  return (
    <>
      <PageHeader
        title="Diagnostics"
        subtitle="Offline-verifiable system state, causal empty-dataset analysis, canaries, and next actions."
      />

      <section className="split-grid">
        <Panel title="System Mode" description="The verification layer makes live vs demo vs mixed explicit.">
          <div className="dataset-mode-banner">
            <span className={`status-pill status-pill-${String(diagnostics.system_mode ?? "live").toLowerCase()}`}>
              {diagnostics.system_mode ?? "LIVE"}
            </span>
            <span className="muted">
              Live records {empty.live_records ?? 0}  Demo records {empty.demo_records ?? 0}  Backfill{" "}
              {empty.last_successful_backfill ?? "none"}
            </span>
          </div>
          <div style={{ marginTop: 16, display: "flex", gap: 12, flexWrap: "wrap" }}>
            <a href={`${apiBase}/api/verification/latest/download`}>Download latest verification bundle</a>
            <Link href="/runs">Inspect recent runs</Link>
            <Link href="/sources">Inspect sources</Link>
          </div>
        </Panel>
        <Panel title="Readiness Mix" description="Configured vs blocked vs healthy vs candidate sources.">
          <MiniBars
            items={Object.entries(readiness).map(([label, count]) => ({ label, count }))}
            labelKey="label"
            valueKey="count"
          />
        </Panel>
      </section>

      <section className="split-grid">
        <Panel title="Why Is This Empty?" description="Ranked causal chain generated from the recorded evidence.">
          <ul className="list-plain">
            {(empty.top_root_causes ?? []).map((item: ApiRecord) => (
              <li key={item.rank}>
                <div>
                  <div><strong>{item.rank}. {item.cause}</strong></div>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Next Actions" description="Operator actions generated from source health, canaries, and run evidence.">
          <ul className="list-plain">
            {(empty.next_actions ?? []).map((item: ApiRecord, index: number) => (
              <li key={index}>
                <div>
                  <div><strong>{item.action}</strong></div>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </section>

      <section className="overview-grid">
        <Panel title="Canary Board" description="Recent reachability and parser checks for the public baseline.">
          <DataGridTable
            rows={canaries}
            columns={[
              { key: "source_name", label: "Source" },
              { key: "status", label: "Status", type: "status" },
              { key: "issue_code", label: "Issue" },
              { key: "latency_ms", label: "Latency", type: "number" },
              { key: "timestamp", label: "Timestamp", type: "datetime" }
            ]}
          />
        </Panel>
        <Panel title="Top Blockers" description="Current incidents hurting recall, freshness, or trust.">
          <DataGridTable
            rows={blockers}
            columns={[
              { key: "issue_code", label: "Issue" },
              { key: "severity", label: "Severity", type: "status" },
              { key: "state", label: "State", type: "status" },
              { key: "impact_on_yield", label: "Impact" }
            ]}
          />
        </Panel>
      </section>

      <section className="overview-grid">
        <Panel title="Latest Run Evidence" description="Recent runs and the recorded diagnostic bundle path.">
          <DataGridTable
            rows={runs}
            itemLinkBase="/runs"
            columns={[
              { key: "id", label: "Run" },
              { key: "job_type", label: "Type" },
              { key: "status", label: "Status", type: "status" },
              { key: "documents_fetched", label: "Docs", type: "number" },
              { key: "evidence_extracted", label: "Evidence", type: "number" },
              { key: "verification_bundle_path", label: "Bundle" }
            ]}
          />
        </Panel>
        <Panel title="Source Health Evidence" description="Healthy labels are backed by fetches, canaries, and blocker state.">
          <DataGridTable
            rows={sources}
            itemLinkBase="/sources"
            columns={[
              { key: "name", label: "Source" },
              { key: "operational_state", label: "Operational", type: "status" },
              { key: "yield_state", label: "Yield", type: "status" },
              { key: "last_successful_fetch", label: "Last Success", type: "datetime" },
              { key: "last_canary_status", label: "Canary", type: "status" },
              { key: "recommended_fix", label: "Next Fix" }
            ]}
          />
        </Panel>
      </section>
    </>
  );
}
