/** @type {import('tailwindcss').Config} */
// Semantic design tokens. Components use these names (bg-surface, text-fg-muted,
// border-line, bg-primary...) instead of raw palette colors, so light and dark
// themes are two definitions of the same variables in src/index.css -- tuned per
// theme for contrast, not an inversion of one palette.
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        canvas: token("canvas"),
        surface: {
          DEFAULT: token("surface"),
          2: token("surface-2"),
          3: token("surface-3"),
        },
        nav: {
          DEFAULT: token("nav"),
          fg: token("nav-fg"),
          muted: token("nav-muted"),
          active: token("nav-active"),
          "active-fg": token("nav-active-fg"),
          hover: token("nav-hover"),
        },
        line: {
          DEFAULT: token("line"),
          strong: token("line-strong"),
        },
        fg: {
          DEFAULT: token("fg"),
          muted: token("fg-muted"),
          subtle: token("fg-subtle"),
          inverse: token("fg-inverse"),
        },
        primary: {
          DEFAULT: token("primary"),
          hover: token("primary-hover"),
          fg: token("primary-fg"),
          subtle: token("primary-subtle"),
          "subtle-fg": token("primary-subtle-fg"),
        },
        danger: { DEFAULT: token("danger"), subtle: token("danger-subtle"), fg: token("danger-fg") },
        warning: { DEFAULT: token("warning"), subtle: token("warning-subtle"), fg: token("warning-fg") },
        success: { DEFAULT: token("success"), subtle: token("success-subtle"), fg: token("success-fg") },
        info: { DEFAULT: token("info"), subtle: token("info-subtle"), fg: token("info-fg") },
        // Brand green of the generated .docx (DARK_GREEN #00532A in docx_builder.py).
        brand: { 500: "#00532A" },
      },
      ringColor: { DEFAULT: token("ring") },
      boxShadow: {
        card: "0 1px 2px 0 rgb(var(--shadow) / 0.06), 0 1px 3px 0 rgb(var(--shadow) / 0.08)",
        pop: "0 10px 30px -10px rgb(var(--shadow) / 0.35), 0 4px 10px -6px rgb(var(--shadow) / 0.2)",
      },
      fontFamily: {
        sans: ['"Inter"', "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
