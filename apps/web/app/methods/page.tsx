import { DataGridTable } from "@/components/data-grid-table";
import { MiniBars } from "@/components/mini-chart";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { ApiRecord, fetchJson } from "@/lib/api";

export default async function MethodsPage() {
  const sources = await fetchJson<ApiRecord>("/api/sources?limit=200");
  const queries = await fetchJson<ApiRecord>("/api/queries?limit=200");
  const methodRows = (sources.items ?? []).map((row: ApiRecord) => ({
    id: row.id,
    source: row.name,
    acquisition_method: row.acquisition_method,
    parsing_mode: row.parsing_mode,
    operational_state: row.operational_state,
    docs_fetched_7d: row.docs_fetched_7d,
    opportunities_created_7d: row.opportunities_created_7d,
    english_acceptance_rate: row.english_acceptance_rate
  }));

  const queryFamilyCounts = Object.entries(
    (queries.items ?? []).reduce((acc: Record<string, number>, row: ApiRecord) => {
      const family = row.query_family ?? "unclassified";
      acc[family] = (acc[family] ?? 0) + Number(row.opps ?? 0) + Number(row.signals ?? 0);
      return acc;
    }, {})
  ).map(([family, count]) => ({ family, count }));

  return (
    <>
      <PageHeader title="Query + Method Lab" subtitle="Which acquisition approaches and query families are producing useful D365 leads." />
      <section className="split-grid">
        <Panel title="Source x Method Yield" description="Operational behavior by acquisition and parsing mode.">
          <DataGridTable
            rows={methodRows}
            columns={[
              { key: "source", label: "Source" },
              { key: "acquisition_method", label: "Acquisition" },
              { key: "parsing_mode", label: "Parsing" },
              { key: "operational_state", label: "State", type: "status" },
              { key: "docs_fetched_7d", label: "Docs 7d", type: "number" },
              { key: "opportunities_created_7d", label: "Opps 7d", type: "number" },
              { key: "english_acceptance_rate", label: "English Rate", type: "number" }
            ]}
          />
        </Panel>
        <Panel title="Query Family Yield" description="Net useful rows created by each query family.">
          <MiniBars items={queryFamilyCounts} labelKey="family" valueKey="count" />
        </Panel>
      </section>
    </>
  );
}
