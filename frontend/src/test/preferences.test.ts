import { describe, expect, it } from "vitest";
import { DEFAULT_PREFERENCES, applyPreferences } from "../store/usePreferencesStore";

describe("theme and preferences", () => {
  it("applies dark and light themes to the whole document", () => {
    applyPreferences("dark", DEFAULT_PREFERENCES);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    applyPreferences("light", DEFAULT_PREFERENCES);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("applies density and reduced motion", () => {
    applyPreferences("light", { ...DEFAULT_PREFERENCES, density: "compact", reduce_motion: true });
    expect(document.documentElement.dataset.density).toBe("compact");
    expect(document.documentElement.classList.contains("reduce-motion")).toBe(true);
    applyPreferences("light", DEFAULT_PREFERENCES);
    expect(document.documentElement.dataset.density).toBeUndefined();
  });
});
