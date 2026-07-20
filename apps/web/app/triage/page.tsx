import Link from "next/link";
import { fetchJson } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { DataGridTable } from "@/components/data-grid-table";

type TriagePayload = {
  artifact_path: string;
  generated_at?: string;
  headline: Record<string, number>;
  funnel: Array<{ key: string; label: string; count: number; tone: string }>;
  family_heatmap: Array<Record<string, string | number>>;
  country_heatmap: Array<Record<string, string | number>>;
  blockers: Array<{ bucket: string; reason: string; count: number }>;
  detail_follow_summary: {
    final_state_counts: Record<string, number>;
    final_reason_counts: Record<string, number>;
    manual_review_rows: Record<string, unknown>[];
    watch_only_rows: Record<string, unknown>[];
  };
  queues: {
    near_miss: Record<string, unknown>[];
    detail_follow: Record<string, unknown>[];
    award_history: Record<string, unknown>[];
  };
};

const heatKeys = [
  "promising_near_miss",
  "promising_surface_needs_detail_follow",
  "award_or_history_surface",
  "non_d365_or_too_generic",
  "false_friend_or_competitor_noise",
] as const;

const heatLabels: Record<(typeof heatKeys)[number], string> = {
  promising_near_miss: "Near miss",
  promising_surface_needs_detail_follow: "Needs follow",
  award_or_history_surface: "Award/watch",
  non_d365_or_too_generic: "Too generic",
  false_friend_or_competitor_noise: "Noise",
};

const toneColors: Record<string, string> = {
  input: "#0f6cbd",
  review: "#038387",
  detail: "#2563eb",
  watch: "#bc8c00",
  reject: "#a4262c",
  promote: "#107c10",
};

function formatNumber(value: number | undefined) {
  return new Intl.NumberFormat("en-US").format(value ?? 0);
}

function heatColor(value: number, maxValue: number, base: string) {
  const pct = maxValue > 0 ? Math.max(10, Math.round((value / maxValue) * 72)) : 8;
  return `color-mix(in srgb, ${base} ${pct}%, var(--panel))`;
}

function Heatmap({
  rows,
  rowKey,
  titleLabel,
}: {
  rows: Array<Record<string, string | number>>;
  rowKey: string;
  titleLabel: string;
}) {
  const maxValue = Math.max(
    1,
    ...rows.flatMap((row) => heatKeys.map((key) => Number(row[key] ?? 0))),
  );

  return (
    <div className="triage-heatmap-wrap">
      <table className="triage-heatmap">
        <thead>
          <tr>
            <th>{titleLabel}</th>
            {heatKeys.map((key) => (
              <th key={key}>{heatLabels[key]}</th>
            ))}
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${String(row[rowKey] ?? "unknown")}`}>
              <th scope="row">{String(row[rowKey] ?? "unknown")}</th>
              {heatKeys.map((key) => {
                const value = Number(row[key] ?? 0);
                return (
                  <td
                    key={key}
                    style={{ background: heatColor(value, maxValue, toneColors[key.includes("generic") || key.includes("noise") ? "reject" : key.includes("award") ? "watch" : key.includes("detail") ? "detail" : "review"]) }}
                  >
                    {formatNumber(value)}
                  </td>
                );
              })}
              <td>{formatNumber(Number(row.total ?? 0))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FlowRail({ items }: { items: TriagePayload["funnel"] }) {
  const maxValue = Math.max(1, ...items.map((item) => item.count));
  return (
    <div className="triage-flow-grid">
      {items.map((item) => (
        <article key={item.key} className="triage-flow-node" data-tone={item.tone}>
          <div className="triage-flow-label">{item.label}</div>
          <div className="triage-flow-value">{formatNumber(item.count)}</div>
          <div className="triage-flow-track" aria-hidden="true">
            <div
              className="triage-flow-fill"
              style={{
                width: `${Math.max(6, Math.round((item.count / maxValue) * 100))}%`,
                background: toneColors[item.tone] ?? toneColors.review,
              }}
            />
          </div>
        </article>
      ))}
    </div>
  );
}

function OutcomeStack({ counts }: { counts: Record<string, number> }) {
  const order = [
    { key: "still_needs_manual_review", label: "Manual review", tone: "detail" },
    { key: "watch_only", label: "Watch only", tone: "watch" },
    { key: "no_upgrade", label: "No upgrade", tone: "reject" },
    { key: "promoted_seller_ready", label: "Seller-ready", tone: "promote" },
    { key: "promoted_research_ready", label: "Research-ready", tone: "review" },
  ];
  const total = Math.max(
    1,
    order.reduce((sum, item) => sum + Number(counts[item.key] ?? 0), 0),
  );
  return (
    <div className="triage-stack-wrap">
      <div className="triage-stack" aria-label="Detail follow outcomes">
        {order.map((item) => {
          const value = Number(counts[item.key] ?? 0);
          if (!value) return null;
          return (
            <div
              key={item.key}
              className="triage-stack-segment"
              style={{
                width: `${Math.max((value / total) * 100, 4)}%`,
                background: toneColors[item.tone] ?? toneColors.review,
              }}
              title={`${item.label}: ${formatNumber(value)}`}
            />
          );
        })}
      </div>
      <div className="triage-stack-legend">
        {order.map((item) => (
          <div key={item.key} className="triage-stack-legend-item">
            <span
              className="triage-stack-dot"
              style={{ background: toneColors[item.tone] ?? toneColors.review }}
              aria-hidden="true"
            />
            <span>{item.label}</span>
            <strong>{formatNumber(Number(counts[item.key] ?? 0))}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

export default async function TriagePage() {
  const triage = await fetchJson<TriagePayload>("/api/triage");
  const headline = triage.headline ?? {};
  const metrics = [
    { label: "Reviewed", value: headline.reviewed, note: "Full-document second pass" },
    { label: "Interesting", value: headline.interesting_total, note: "Near miss + follow + watch" },
    { label: "Near Miss", value: headline.near_miss_total, note: "Strong enough to inspect now" },
    { label: "Needs Follow", value: headline.detail_follow_total, note: "Best queue for widening coverage" },
    { label: "Detail Reviewed", value: headline.detail_follow_reviewed, note: "Rows followed to notice/detail pages" },
    { label: "Manual Review", value: headline.detail_manual_review, note: "Strengthened but not yet promotable" },
    { label: "Watch Only", value: headline.detail_watch_only, note: "Useful context, not clean active pursuit" },
    { label: "Promoted", value: headline.detail_promoted, note: "Upgraded by deeper follow" },
  ];

  return (
    <>
      <PageHeader
        title="Triage Workbench"
        subtitle="A calm review surface for the 1,057 non-prime records: where signal concentrated, why the strict gate rejected rows, and which queues deserve operator time first."
        actions={
          <div className="page-header-actions">
            <Link href="/diagnostics">Diagnostics</Link>
            <Link href="/sources">Sources</Link>
          </div>
        }
      />

      <section className="panel">
        <div className="triage-metric-grid">
          {metrics.map((item) => (
            <article key={item.label} className="triage-metric-card">
              <div className="triage-metric-label">{item.label}</div>
              <div className="triage-metric-value">{formatNumber(item.value)}</div>
              <div className="triage-metric-note">{item.note}</div>
            </article>
          ))}
        </div>
      </section>

      <section className="overview-grid">
        <Panel
          title="Bucket Flow"
          description="This tells the story without forcing you through a wall of tables: what the reviewer found, then what deeper follow-up did to the 250-row queue."
        >
          <FlowRail items={triage.funnel ?? []} />
        </Panel>
        <Panel
          title="Detail Follow Outcome"
          description="The 250-row detail-follow queue produced watch material and manual-review candidates, but no clean promotions under the current strict anchor and authenticity gate."
        >
          <OutcomeStack counts={triage.detail_follow_summary?.final_state_counts ?? {}} />
          <ul className="list-plain">
            {(triage.blockers ?? []).slice(0, 5).map((item) => (
              <li key={`${item.bucket}-${item.reason}`}>
                <div>
                  <div>
                    <strong>{item.reason}</strong>
                  </div>
                  <div className="muted">{item.bucket.replaceAll("_", " ")}</div>
                </div>
                <strong>{formatNumber(item.count)}</strong>
              </li>
            ))}
          </ul>
        </Panel>
      </section>

      <section className="split-grid">
        <Panel
          title="Family Concentration"
          description="Use this first. It shows where the interesting misses are clustering by source family so you can decide whether to harden buyer-direct follow, install-base triggers, or portal adapters."
        >
          <Heatmap rows={triage.family_heatmap ?? []} rowKey="family" titleLabel="Source family" />
        </Panel>
        <Panel
          title="Country Concentration"
          description="This separates real opportunity density from simple crawl volume. If a country is hot in the follow bucket, it usually wants deeper detail extraction rather than looser scoring."
        >
          <Heatmap rows={triage.country_heatmap ?? []} rowKey="country" titleLabel="Country" />
        </Panel>
      </section>

      <section className="split-grid">
        <Panel
          title="Near Miss Queue"
          description="These rows were close enough to stay interesting without needing another crawl step. They are usually missing a strict Microsoft anchor or explicit currentness proof."
        >
          <DataGridTable
            rows={triage.queues?.near_miss ?? []}
            columns={[
              { key: "source_name", label: "Source" },
              { key: "country", label: "Country" },
              { key: "family", label: "Family" },
              { key: "promising_score", label: "Score", type: "number" },
              { key: "why_not_promoted", label: "Why Not" },
            ]}
          />
        </Panel>
        <Panel
          title="Needs Detail Follow Queue"
          description="This is the highest-value worklist. The rows here often look commercially relevant, but the captured page was too shallow to prove Microsoft specificity or currentness."
        >
          <DataGridTable
            rows={triage.queues?.detail_follow ?? []}
            columns={[
              { key: "source_name", label: "Source" },
              { key: "country", label: "Country" },
              { key: "family", label: "Family" },
              { key: "promising_score", label: "Score", type: "number" },
              { key: "why_not_promoted", label: "Why Not" },
            ]}
          />
        </Panel>
      </section>

      <section className="split-grid">
        <Panel
          title="Manual Review After Detail Follow"
          description="These are the best strengthened cases. They still failed deterministic promotion, but they deserve human judgment because the deeper page added service, procurement, or soft ERP signal."
        >
          <DataGridTable
            rows={triage.detail_follow_summary?.manual_review_rows ?? []}
            columns={[
              { key: "source_name", label: "Source" },
              { key: "country", label: "Country" },
              { key: "family", label: "Family" },
              { key: "best_detail_score", label: "Detail Score", type: "number" },
              { key: "final_reason", label: "Final Reason" },
              { key: "best_detail_soft_anchor_terms", label: "Soft Anchor" },
            ]}
          />
        </Panel>
        <Panel
          title="Watch Material"
          description="These rows became useful context rather than active pursuit. Most are award, framework, history, or contract-detail surfaces that help with account intelligence more than immediate bidding."
        >
          <DataGridTable
            rows={triage.detail_follow_summary?.watch_only_rows ?? []}
            columns={[
              { key: "source_name", label: "Source" },
              { key: "country", label: "Country" },
              { key: "family", label: "Family" },
              { key: "best_detail_score", label: "Detail Score", type: "number" },
              { key: "final_reason", label: "Final Reason" },
              { key: "best_detail_award_terms", label: "Award Terms" },
            ]}
          />
        </Panel>
      </section>

      <section className="panel">
        <div className="triage-footnote">
          <div>
            <strong>Artifact path</strong>
            <div className="muted">{triage.artifact_path}</div>
          </div>
          <div>
            <strong>Generated</strong>
            <div className="muted">{triage.generated_at ?? "unknown"}</div>
          </div>
          <div>
            <strong>Why this shape works</strong>
            <div className="muted">
              Ranked flow first, matrices second, action queues last. It keeps volume visible without turning the page into a spreadsheet explosion.
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
