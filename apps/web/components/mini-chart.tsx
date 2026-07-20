import React from "react";

export function MiniBars({
  items,
  valueKey,
  labelKey
}: {
  items: Record<string, unknown>[];
  valueKey: string;
  labelKey: string;
}) {
  const values = items.map((item) => Number(item[valueKey] ?? 0));
  const max = Math.max(...values, 1);
  return (
    <div className="mini-bars" role="img" aria-label="Bar chart">
      {items.map((item) => {
        const value = Number(item[valueKey] ?? 0);
        const label = String(item[labelKey] ?? "unknown");
        return (
          <div key={`${label}-${value}`} className="mini-bar-row">
            <span className="mini-bar-label">{label}</span>
            <div className="mini-bar-track">
              <div className="mini-bar-fill" style={{ width: `${Math.max((value / max) * 100, 4)}%` }} />
            </div>
            <span className="mini-bar-value">{value}</span>
          </div>
        );
      })}
    </div>
  );
}
