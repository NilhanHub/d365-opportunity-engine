import { DataGridTable } from "@/components/data-grid-table";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { ApiRecord, fetchJson } from "@/lib/api";

export default async function AccountsPage() {
  const accounts = await fetchJson<ApiRecord>("/api/accounts?limit=200");
  return (
    <>
      <PageHeader title="Accounts / Buyers" subtitle="Organizations surfacing across multiple sources, opportunities, and signals." />
      <Panel title="Accounts" description={`${accounts.total ?? accounts.items?.length ?? 0} account clusters.`}>
        <DataGridTable
          rows={accounts.items ?? []}
          columns={[
            { key: "canonical_name", label: "Account" },
            { key: "country", label: "Country" },
            { key: "heat_score", label: "Heat", type: "number" },
            { key: "buyer_quality_score", label: "Quality", type: "number" },
            { key: "installed_product_guess", label: "Installed Product" },
            { key: "trigger_strength", label: "Trigger", type: "number" },
            { key: "opportunity_count", label: "Opps", type: "number" },
            { key: "signal_count", label: "Signals", type: "number" }
          ]}
        />
      </Panel>
    </>
  );
}
