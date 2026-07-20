"use client";

import Link from "next/link";
import { Badge, Button, Text } from "@fluentui/react-components";
import { navItems } from "@/lib/nav";
import { CommandPalette } from "@/components/command-palette";
import { EnvironmentBadge } from "@/components/environment-badge";
import { GlobalSearch } from "@/components/global-search";
import { ThemeToggle } from "@/components/theme-toggle";

export function AppShell({
  children,
  title = "D365 Opportunity Engine",
  subtitle = "Internal intelligence and operations cockpit"
}: {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
}) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-header">
          <Text size={500} weight="semibold">
            {title}
          </Text>
          <Text size={200} className="muted">
            {subtitle}
          </Text>
          <Badge appearance="tint" color="informative">
            Evidence-backed
          </Badge>
        </div>
        <nav className="nav-list" aria-label="Primary">
          {navItems.map((item) => (
            <Link key={item.href} href={item.href} className="nav-item">
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <div>
            <Text size={600} weight="semibold">
              Operator Cockpit
            </Text>
            <Text size={200} className="muted">
              Source ops, discovery coverage, crawl health, evidence, and export readiness.
            </Text>
            <div className="live-indicator">
              <EnvironmentBadge />
            </div>
          </div>
          <div className="topbar-actions">
            <GlobalSearch />
            <CommandPalette />
            <ThemeToggle />
            <Button as="a" href="/opportunities" appearance="primary">
              Best Leads
            </Button>
          </div>
        </header>
        <main className="page-content">{children}</main>
      </div>
    </div>
  );
}
