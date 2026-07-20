"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input
} from "@fluentui/react-components";
import { SearchRegular } from "@fluentui/react-icons";
import { navItems } from "@/lib/nav";

const quickActions = [
  { label: "Refresh Sources", href: "/runs" },
  { label: "Review Candidates", href: "/discovery" },
  { label: "Inspect Issues", href: "/issues" },
  { label: "See Best Leads", href: "/opportunities" }
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const router = useRouter();

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const items = useMemo(() => {
    const allItems = [...navItems, ...quickActions];
    const lowered = query.trim().toLowerCase();
    if (!lowered) {
      return allItems;
    }
    return allItems.filter((item) => item.label.toLowerCase().includes(lowered));
  }, [query]);

  return (
    <>
      <Button appearance="subtle" icon={<SearchRegular />} onClick={() => setOpen(true)}>
        Command
      </Button>
      <Dialog open={open} onOpenChange={(_, data) => setOpen(data.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Command Palette</DialogTitle>
            <DialogContent>
              <Field label="Jump to route or operator view">
                <Input value={query} onChange={(_, data) => setQuery(data.value)} placeholder="Search views" />
              </Field>
              <div className="command-list" role="listbox" aria-label="Command palette results">
                {items.map((item) => (
                  <button
                    key={`${item.label}-${item.href}`}
                    className="command-item"
                    onClick={() => {
                      setOpen(false);
                      router.push(item.href);
                    }}
                  >
                    <span>{item.label}</span>
                    <span>{item.href}</span>
                  </button>
                ))}
              </div>
              <div className="command-shortcut-hint">
                <Link href="/settings">Settings</Link>
                <span>Ctrl/Cmd + K</span>
              </div>
            </DialogContent>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}
