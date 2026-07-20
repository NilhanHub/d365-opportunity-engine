"use client";

import Link from "next/link";
import { StatusBadge } from "@/components/status-badge";

export type DataColumn = {
  key: string;
  label: string;
  type?: "status" | "number" | "datetime" | "json" | "text" | "boolean";
};

export function DataGridTable({
  rows,
  columns,
  itemLinkBase,
  itemLinkKey = "id"
}: {
  rows: Record<string, unknown>[];
  columns: DataColumn[];
  itemLinkBase?: string;
  itemLinkKey?: string;
}) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length ? (
            rows.map((row, index) => (
              <tr key={String(row[itemLinkKey] ?? index)}>
                {columns.map((column, columnIndex) => (
                  <td key={column.key} data-label={column.label}>
                    {renderCell({
                      row,
                      column,
                      itemLinkBase,
                      itemLinkKey,
                      isPrimaryColumn: columnIndex === 0
                    })}
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={columns.length} className="table-empty">
                No rows in the current view.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function renderCell({
  row,
  column,
  itemLinkBase,
  itemLinkKey,
  isPrimaryColumn
}: {
  row: Record<string, unknown>;
  column: DataColumn;
  itemLinkBase?: string;
  itemLinkKey: string;
  isPrimaryColumn: boolean;
}) {
  const value = row[column.key];
  if (column.type === "status") {
    return <StatusBadge value={String(value ?? "unknown")} />;
  }
  if (column.type === "boolean") {
    return value ? "Yes" : "No";
  }

  const content = stringifyValue(value);
  if (itemLinkBase && isPrimaryColumn && row[itemLinkKey]) {
    return <Link href={`${itemLinkBase}/${String(row[itemLinkKey])}`}>{content}</Link>;
  }
  return content;
}

function stringifyValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (Array.isArray(value)) {
    return value.map((item) => stringifyValue(item)).join(", ");
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}
