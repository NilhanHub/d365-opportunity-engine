import { DataGridTable } from "@/components/data-grid-table";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { ApiRecord, fetchJson } from "@/lib/api";

export default async function QueriesPage() {
  const queries = await fetchJson<ApiRecord>("/api/queries?limit=200");
  return (
    <>
      <PageHeader title="Queries" subtitle="Compiled queries, yield, and negative-term behavior." />
      <Panel title="Query Execution" description={`${queries.total ?? queries.items?.length ?? 0} recorded query executions.`}>
        <DataGridTable
          rows={queries.items ?? []}
          columns={[
            { key: "query_family", label: "Family" },
            { key: "query_text", label: "Query" },
            { key: "target_field", label: "Target" },
            { key: "docs", label: "Docs", type: "number" },
            { key: "evidence", label: "Evidence", type: "number" },
            { key: "opps", label: "Opps", type: "number" },
            { key: "signals", label: "Signals", type: "number" },
            { key: "yield_ratio", label: "Yield", type: "number" },
            { key: "negatives_applied", label: "Negatives" }
          ]}
        />
      </Panel>
    </>
  );
}
