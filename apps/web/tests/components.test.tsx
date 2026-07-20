import React from "react";
import { render, screen } from "@testing-library/react";
import { MiniBars } from "@/components/mini-chart";
import { StatusBadge } from "@/components/status-badge";

describe("ui primitives", () => {
  it("renders status text without relying on color alone", () => {
    render(<StatusBadge value="throttled" />);
    expect(screen.getByText("throttled")).toBeInTheDocument();
  });

  it("renders mini chart labels and values", () => {
    render(<MiniBars items={[{ lane: "formal_procurement", count: 4 }]} labelKey="lane" valueKey="count" />);
    expect(screen.getByText("formal_procurement")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });
});
