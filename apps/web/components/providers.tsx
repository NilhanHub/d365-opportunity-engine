"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  FluentProvider,
  teamsDarkTheme,
  teamsLightTheme,
  webDarkTheme,
  webLightTheme
} from "@fluentui/react-components";

type ThemeMode = "light" | "dark";

type ThemeContextValue = {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  mode: "light",
  setMode: () => undefined
});

export function useThemeMode(): ThemeContextValue {
  return useContext(ThemeContext);
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>("light");

  useEffect(() => {
    const stored = window.localStorage.getItem("d365-opps-theme");
    if (stored === "dark" || stored === "light") {
      // Hydration starts from a deterministic light theme; apply the user's
      // persisted client-only preference after the component mounts.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMode(stored);
      return;
    }
    if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
      setMode("dark");
    }
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    window.localStorage.setItem("d365-opps-theme", mode);
  }, [mode]);

  const value = useMemo(() => ({ mode, setMode }), [mode]);
  const theme = mode === "dark" ? { ...webDarkTheme, ...teamsDarkTheme } : { ...webLightTheme, ...teamsLightTheme };

  return (
    <ThemeContext.Provider value={value}>
      <FluentProvider theme={theme}>{children}</FluentProvider>
    </ThemeContext.Provider>
  );
}
