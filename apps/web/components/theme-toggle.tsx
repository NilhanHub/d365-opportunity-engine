"use client";

import { Button } from "@fluentui/react-components";
import { WeatherMoonRegular, WeatherSunnyRegular } from "@fluentui/react-icons";
import { useThemeMode } from "@/components/providers";

export function ThemeToggle() {
  const { mode, setMode } = useThemeMode();
  const isDark = mode === "dark";
  return (
    <Button
      appearance="subtle"
      icon={isDark ? <WeatherSunnyRegular /> : <WeatherMoonRegular />}
      onClick={() => setMode(isDark ? "light" : "dark")}
    >
      {isDark ? "Light" : "Dark"}
    </Button>
  );
}
