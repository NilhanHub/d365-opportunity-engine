import { ApiRecord, fetchJson, toSearchParams } from "@/lib/api";
import { DataGridTable } from "@/components/data-grid-table";
import { MiniBars } from "@/components/mini-chart";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";

export default async function SourcesPage({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = (await searchParams) ?? {};
  const query = toSearchParams({
    state: typeof filters.state === "string" ? filters.state : undefined,
    country: typeof filters.country === "string" ? filters.country : undefined,
    lane: typeof filters.lane === "string" ? filters.lane : undefined,
    enabled: typeof filters.enabled === "string" ? filters.enabled : undefined,
    limit: 200
  });
  const sources = await fetchJson<ApiRecord>(`/api/sources${query}`);
  const rows = sources.items ?? [];
  const countryCounts = Object.entries(
    rows.reduce((acc: Record<string, number>, row: ApiRecord) => {
      const key = row.country ?? "unknown";
      acc[key] = (acc[key] ?? 0) + 1;
      return acc;
    }, {})
  ).map(([country, count]) => ({ country, count }));

  return (
    <>
      <PageHeader title="Source Command Center" subtitle="Every source we know about, its health, yield, quality, and current blockers." />
      <section className="split-grid">
        <Panel title="Source Inventory" description={`${sources.total ?? rows.length} sources loaded into the control plane.`}>
          <DataGridTable
            rows={rows}
            itemLinkBase="/sources"
            columns={[
              { key: "name", label: "Source" },
              { key: "data_mode", label: "Mode", type: "status" },
              { key: "country", label: "Country" },
              { key: "lane", label: "Lane" },
              { key: "acquisition_method", label: "Method" },
              { key: "operational_state", label: "Operational", type: "status" },
              { key: "yield_state", label: "Yield", type: "status" },
              { key: "forthcoming_state", label: "Forthcoming", type: "status" },
              { key: "parser_implemented", label: "Parser", type: "boolean" },
              { key: "backfilled", label: "Backfilled", type: "boolean" },
              { key: "incrementally_syncing", label: "Incremental", type: "boolean" },
              { key: "yielding_d365_records", label: "D365 Yield", type: "boolean" }, // gitleaks:allow - UI field schema, not a credential
              { key: "docs_fetched_7d", label: "Docs 7d", type: "number" },
              { key: "evidence_extracted_7d", label: "Evidence 7d", type: "number" },
              { key: "opportunities_created_7d", label: "Opps 7d", type: "number" },
              { key: "english_acceptance_rate", label: "English Rate", type: "number" },
              { key: "field_completeness_score", label: "Completeness", type: "number" }
            ]}
          />
        </Panel>
        <div className="summary-pair">
          <Panel title="Coverage by Country" description="Active source count per country.">
            <MiniBars items={countryCounts} labelKey="country" valueKey="count" />
          </Panel>
          <Panel title="How To Read It" description="Availability, yield, and quality are separated on purpose.">
            <ul className="list-plain">
              <li>
                <div>
                  <div><strong>Operational state</strong></div>
                  <div className="muted">
                    Reachability and access: healthy, throttled, blocked, auth-required, parser-broken.
                  </div>
                </div>
              </li>
              <li>
                <div>
                  <div><strong>Yield state</strong></div>
                  <div className="muted">
                    Productivity and noise: high-yield, low-yield, noisy, stale, or zero-yield.
                  </div>
                </div>
              </li>
              <li>
                <div>
                  <div><strong>Forthcoming state</strong></div>
                  <div className="muted">
                    Whether a source is active, intentionally disabled, unsupported, or still pending enablement.
                  </div>
                </div>
              </li>
            </ul>
          </Panel>
        </div>
      </section>
    </>
  );
}
