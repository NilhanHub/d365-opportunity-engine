import { ApiRecord, fetchJson, toSearchParams } from "@/lib/api";
import { DataGridTable } from "@/components/data-grid-table";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";

export default async function OpportunitiesPage({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = (await searchParams) ?? {};
  const query = toSearchParams({
    keyword: typeof filters.keyword === "string" ? filters.keyword : undefined,
    country: typeof filters.country === "string" ? filters.country : undefined,
    signal_lane: typeof filters.signal_lane === "string" ? filters.signal_lane : undefined,
    recommended_action: typeof filters.recommended_action === "string" ? filters.recommended_action : undefined,
    limit: 200
  });
  const opportunities = await fetchJson<ApiRecord>(`/api/opportunities${query}`);
  return (
    <>
      <PageHeader title="Opportunity / Lead Explorer" subtitle="Formal opportunities and pre-positioning leads with explainable retrieval and scoring." />
      <Panel title="Opportunities" description={`${opportunities.total ?? opportunities.items?.length ?? 0} opportunities in the current view.`}>
        <DataGridTable
          rows={opportunities.items ?? []}
          itemLinkBase="/opportunities"
          columns={[
            { key: "title", label: "Title" },
            { key: "data_mode", label: "Mode", type: "status" },
            { key: "buyer", label: "Buyer" },
            { key: "signal_lane", label: "Lane", type: "status" },
            { key: "recommended_action", label: "Action", type: "status" },
            { key: "app_family", label: "App Family" },
            { key: "service_line", label: "Service Line" },
            { key: "retrieval_score", label: "Retrieval", type: "number" },
            { key: "opportunity_score", label: "Opp Score", type: "number" },
            { key: "corroboration_count", label: "Corroboration", type: "number" },
            { key: "close_date", label: "Close Date" }
          ]}
        />
      </Panel>
    </>
  );
}
