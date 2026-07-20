import Link from "next/link";
import { ApiRecord, fetchJson, apiBase } from "@/lib/api";
import { KpiCard } from "@/components/kpi-card";
import { MiniBars } from "@/components/mini-chart";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { DataGridTable } from "@/components/data-grid-table";

export default async function OverviewPage() {
  const overview = await fetchJson<ApiRecord>("/api/overview");
  const kpis = overview.kpis ?? {};
  const leads = overview.best_leads_right_now ?? [];
  const problems = overview.top_problems_now ?? [];
  const gaps = overview.coverage_gaps ?? [];
  const recallSanity = overview.recall_sanity ?? [];
  const trends = overview.trends ?? {};
  const dataMode = overview.data_mode ?? "LIVE";

  return (
    <>
      <PageHeader
        title="Executive Overview"
        subtitle="Current source health, intake velocity, best leads, and blind spots."
      />
      <Panel title="Dataset Mode" description="The operator view now distinguishes live and synthetic rows explicitly.">
        <div className="dataset-mode-banner">
          <span className={`status-pill status-pill-${dataMode.toLowerCase()}`}>{dataMode}</span>
          <span className="muted">
            Live records {kpis.live_records ?? 0}  Demo records {kpis.demo_records ?? 0}  Last live refresh{" "}
            {kpis.last_live_refresh ?? "n/a"}  Last backfill {kpis.last_successful_backfill ?? "n/a"}
          </span>
        </div>
        <div style={{ marginTop: 16, display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Link href="/diagnostics">Open diagnostics</Link>
          <a href={`${apiBase}/api/verification/latest/download`}>Download verification bundle</a>
        </div>
      </Panel>
      {(kpis.live_records ?? 0) === 0 ? (
        <Panel title="Why Is This Empty?" description="Use the diagnostics route and verification bundle instead of guessing from the UI.">
          <div className="dataset-mode-banner">
            <span className="status-pill status-pill-blocked">Attention</span>
            <span className="muted">
              The live dataset is empty or near-empty. Open diagnostics for the recorded causal chain and next actions.
            </span>
          </div>
        </Panel>
      ) : null}
      <section className="kpi-grid">
        <KpiCard label="Seller-Ready Bid Now" value={kpis.seller_ready_bid_now_total ?? 0} href="/opportunities" hint="Current open bids a seller can act on now." />
        <KpiCard label="Seller-Ready Pre-Position" value={kpis.seller_ready_pre_position_total ?? 0} href="/opportunities" hint="Current consultations or shaping exercises with enough evidence to act." />
        <KpiCard label="Current Actionable" value={kpis.current_actionable_total ?? 0} href="/opportunities" hint="Commercially live D365 records, whether seller-ready or still analyst-gated." />
        <KpiCard label="Retained D365" value={kpis.retained_d365_records ?? 0} href="/opportunities" hint="Live D365-anchored retained universe." />
        <KpiCard label="Monitor" value={kpis.monitor_total ?? 0} href="/signals" hint="Retained intelligence for monitoring, not direct seller handoff." />
        <KpiCard label="Stale / Awarded" value={kpis.stale_or_awarded_total ?? 0} href="/opportunities" hint="Demoted because commercially stale, closed, or awarded." />
        <KpiCard label="English Insufficient" value={kpis.english_insufficient_total ?? 0} href="/opportunities" hint="Demoted because seller-usable English evidence is not sufficient." />
        <KpiCard label="Yielding Seller-Ready Sources" value={kpis.sources_yielding_seller_ready_records ?? 0} href="/sources" hint="Sources contributing seller-ready leads in the current corpus." />
        <KpiCard label="Prod-Ready Public No-Auth" value={kpis.production_ready_public_no_auth_sources ?? 0} href="/sources" hint="Public sources that are actually production-ready, not just configured." />
        <KpiCard label="Healthy Sources" value={kpis.healthy_sources ?? 0} href="/sources?state=healthy" />
        <KpiCard label="Blocked Sources" value={kpis.blocked_sources ?? 0} href="/issues" />
        <KpiCard label="Pending Candidates" value={kpis.candidate_sources_pending_review ?? 0} href="/discovery" />
      </section>

      <Panel title="Acquisition volume (not lead counts)" description="These are upper-funnel operational counters. They are not seller pipeline totals.">
        <section className="kpi-grid">
          <KpiCard label="Successful Fetches" value={kpis.successful_fetches ?? 0} href="/runs" hint="Acquisition volume only, not final leads." />
          <KpiCard label="Fetched Documents" value={kpis.fetched_documents ?? 0} href="/runs" hint="Acquisition volume only, not final leads." />
          <KpiCard label="Detail Pages" value={kpis.fetched_detail_pages ?? 0} href="/runs" hint="Acquisition volume only, not final leads." />
          <KpiCard label="Attachments" value={kpis.fetched_attachments ?? 0} href="/runs" hint="Acquisition volume only, not final leads." />
          <KpiCard label="Evidence Rows" value={kpis.evidence_rows ?? 0} href="/sources" hint="Extraction volume only, not final leads." />
          <KpiCard label="Parsed Documents" value={kpis.parsed_documents ?? 0} href="/sources" hint="Extraction volume only, not final leads." />
          <KpiCard label="Classified Documents" value={kpis.classified_documents ?? 0} href="/opportunities" hint="Extraction volume only, not final leads." />
          <KpiCard label="Raw Records" value={kpis.raw_records_ingested ?? 0} href="/runs" hint="Raw intake only, not final leads." />
          <KpiCard label="Signals" value={kpis.market_signals_created ?? 0} href="/signals" />
          <KpiCard label="Candidates" value={kpis.opportunity_candidates_created ?? 0} href="/opportunities" />
          <KpiCard label="Excluded" value={kpis.excluded_items ?? 0} href="/runs" />
          <KpiCard label="Accounts" value={kpis.unique_buyers_accounts ?? 0} href="/accounts" />
        </section>
      </Panel>

      <section className="overview-grid">
        <Panel title="Best Leads Right Now" description="Top current opportunities, drillable to evidence.">
          <DataGridTable
            rows={leads}
            itemLinkBase="/opportunities"
            columns={[
              { key: "title", label: "Title" },
              { key: "buyer", label: "Buyer" },
              { key: "country", label: "Country" },
              { key: "recommended_action", label: "Action", type: "status" },
              { key: "retrieval_score", label: "Retrieval", type: "number" },
              { key: "opportunity_score", label: "Opp Score", type: "number" },
              { key: "close_date", label: "Close Date", type: "datetime" }
            ]}
          />
        </Panel>
        <div className="summary-pair">
          <Panel title="Top Problems Now" description="Current blockers and degradations affecting yield.">
            <ul className="list-plain">
              {problems.map((problem: ApiRecord) => (
                <li key={problem.id}>
                  <div>
                    <div><strong>{problem.issue_code}</strong></div>
                    <div className="muted">{problem.impact_on_yield}</div>
                  </div>
                  <Link href="/issues">Open</Link>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title="Coverage Gaps" description="Countries, source families, and review bottlenecks needing attention.">
            <ul className="list-plain">
              {gaps.map((gap: ApiRecord, index: number) => (
                <li key={`${gap.type}-${index}`}>
                  <div>
                    <div><strong>{gap.type?.replaceAll("_", " ")}</strong></div>
                    <div className="muted">{gap.detail}</div>
                  </div>
                  <Link href={gap.candidate_id ? "/discovery" : "/coverage"}>Inspect</Link>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </section>

      <section className="split-grid">
        <Panel title="Recall Sanity" description="The app now calls out when healthy coverage and observed yield do not match.">
          <ul className="list-plain">
            {recallSanity.length ? (
              recallSanity.map((alert: ApiRecord, index: number) => (
                <li key={`${alert.type}-${index}`}>
                  <div>
                    <div><strong>{alert.type?.replaceAll("_", " ")}</strong></div>
                    <div className="muted">{alert.detail}</div>
                  </div>
                  <Link href="/sources">Inspect</Link>
                </li>
              ))
            ) : (
              <li>
                <div>
                  <div><strong>No active recall alerts</strong></div>
                  <div className="muted">Current healthy-source coverage and retained yield are in a plausible range.</div>
                </div>
              </li>
            )}
          </ul>
        </Panel>
        <Panel title="30 / 90 Day Throughput" description="Rolling live opportunity flow, separated from the current open book.">
          <MiniBars
            items={[
              { label: "30d", count: kpis.rolling_30d_opportunities ?? 0 },
              { label: "90d", count: kpis.rolling_90d_opportunities ?? 0 },
              { label: "Open", count: kpis.live_open_opportunities ?? 0 },
              { label: "Pre-position", count: kpis.live_pre_positioning_items ?? 0 }
            ]}
            labelKey="label"
            valueKey="count"
          />
        </Panel>
      </section>

      <section className="split-grid">
        <Panel title="Opportunities by Country" description="Where formal and pre-positioning demand is surfacing.">
          <MiniBars items={trends.opportunities_by_country ?? []} labelKey="country" valueKey="count" />
        </Panel>
        <Panel title="Opportunities by Lane" description="Formal bids, pre-positioning, outreach, and trigger-based leads.">
          <MiniBars items={trends.opportunities_by_lane ?? []} labelKey="lane" valueKey="count" />
        </Panel>
      </section>

      <section className="split-grid">
        <Panel title="Documents, Evidence, and Opportunities Over Time" description="Daily throughput across the pipeline.">
          <MiniBars items={trends.records_by_day ?? []} labelKey="date" valueKey="documents" />
        </Panel>
        <Panel title="Source Health Over Time" description="Operational state counts by day.">
          <MiniBars
            items={(trends.source_health_over_time ?? []).map((row: ApiRecord) => ({
              date: row.date,
              count: Object.values(row.states ?? {}).reduce<number>((sum, value) => sum + Number(value), 0)
            }))}
            labelKey="date"
            valueKey="count"
          />
        </Panel>
      </section>
    </>
  );
}
