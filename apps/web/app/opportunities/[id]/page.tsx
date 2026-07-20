import { notFound } from "next/navigation";
import { DataGridTable } from "@/components/data-grid-table";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { ApiRecord, fetchJson } from "@/lib/api";

export default async function OpportunityDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let opportunity: ApiRecord;
  try {
    opportunity = await fetchJson<ApiRecord>(`/api/opportunities/${id}`);
  } catch {
    notFound();
  }

  return (
    <>
      <PageHeader title={opportunity.title} subtitle="Structured fields, retrieval evidence, and raw-source lineage." />
      <section className="split-grid">
        <Panel title="Summary" description="Core opportunity attributes.">
          <DataGridTable
            rows={[
              { id: "buyer", field: "Buyer", value: opportunity.buyer },
              { id: "country", field: "Country", value: opportunity.country },
              { id: "lane", field: "Lane", value: opportunity.signal_lane },
              { id: "action", field: "Action", value: opportunity.recommended_action },
              { id: "app", field: "App Family", value: opportunity.app_family },
              { id: "service", field: "Service", value: opportunity.service_type }
            ]}
            columns={[
              { key: "field", label: "Field" },
              { key: "value", label: "Value" }
            ]}
          />
        </Panel>
        <Panel title="Scores" description="Retrieval and downstream scoring explanation.">
          <DataGridTable
            rows={[
              { id: "retrieval", metric: "Retrieval", value: opportunity.retrieval_score },
              { id: "opportunity", metric: "Opportunity", value: opportunity.opportunity_score },
              { id: "formal", metric: "Formal opportunity", value: opportunity.formal_opportunity_score },
              { id: "pre", metric: "Pre-position", value: opportunity.pre_position_score },
              { id: "intent", metric: "Account intent", value: opportunity.account_intent_score },
              { id: "trigger", metric: "Install-base trigger", value: opportunity.install_base_trigger_score }
            ]}
            columns={[
              { key: "metric", label: "Metric" },
              { key: "value", label: "Value", type: "number" }
            ]}
          />
        </Panel>
      </section>
      <section className="split-grid">
        <Panel title="Evidence" description="Normalized evidence row behind the opportunity.">
          <pre className="json-block">{JSON.stringify(opportunity.evidence ?? {}, null, 2)}</pre>
        </Panel>
        <Panel title="Scoring Explanation" description="Matched terms and score breakdown.">
          <pre className="json-block">{JSON.stringify(opportunity.scoring_explanation ?? {}, null, 2)}</pre>
        </Panel>
      </section>
      <section className="split-grid">
        <Panel title="Contacts" description="Linked buyer contacts and public contact paths.">
          <DataGridTable
            rows={opportunity.contacts ?? []}
            columns={[
              { key: "full_name", label: "Name" },
              { key: "email", label: "Email" },
              { key: "phone", label: "Phone" },
              { key: "role", label: "Role" }
            ]}
          />
        </Panel>
        <Panel title="Related Opportunities" description="Cluster corroboration and near-duplicates.">
          <DataGridTable
            rows={opportunity.related_opportunities ?? []}
            itemLinkBase="/opportunities"
            columns={[
              { key: "title", label: "Title" },
              { key: "recommended_action", label: "Action", type: "status" },
              { key: "opportunity_score", label: "Score", type: "number" }
            ]}
          />
        </Panel>
      </section>
    </>
  );
}
