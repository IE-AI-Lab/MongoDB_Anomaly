import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

// MongoDB "LeafyGreen" light (Atlas console) palette. Forest green for chrome,
// bright green for primary actions, cool slate neutrals for surfaces/text.
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        mongo: {
          green: {
            base: "#00ED64",
            dark: "#00684A",
            darker: "#023430",
            light: "#C0FAE6",
            tint: "#E3FCF7",
          },
          ink: "#001E2B",
          slate: "#5C6C75",
          mist: "#889397",
          border: "#E8EDEB",
          surface: "#FFFFFF",
          bg: "#F9FBFA",
          header: "#0C1E26",
          purple: "#B45AF2",
        },
        severity: {
          low: "#FFEC9E",
          lowInk: "#944F01",
          medium: "#FFC010",
          mediumInk: "#763101",
          high: "#FFCDC7",
          highInk: "#970606",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(0, 30, 43, 0.06), 0 1px 3px rgba(0, 30, 43, 0.08)",
        pop: "0 8px 24px rgba(0, 30, 43, 0.18)",
      },
    },
  },
  // typography powers the `prose` classes the chat assistant uses to render
  // the LLM's Markdown replies (ChatWidget.tsx).
  plugins: [typography],
};

export default config;
