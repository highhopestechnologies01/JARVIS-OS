import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        jarvis: {
          bg: "#0a0a0f",
          surface: "#13131a",
          border: "#1e1e2e",
          accent: "#6366f1",
          "accent-dim": "#4f46e5",
          green: "#22c55e",
          yellow: "#eab308",
          red: "#ef4444",
          blue: "#3b82f6",
          text: "#e2e8f0",
          muted: "#64748b",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
