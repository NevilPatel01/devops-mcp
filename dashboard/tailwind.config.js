/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        surface: {
          DEFAULT: "#09090b",
          raised: "#0f0f12",
          overlay: "#18181b",
          border: "rgba(255,255,255,0.08)",
        },
        accent: {
          DEFAULT: "#6366f1",
          muted: "#4f46e5",
          glow: "#818cf8",
        },
        mint: { DEFAULT: "#10b981" },
      },
      boxShadow: {
        panel: "0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px rgba(0,0,0,0.35)",
        modal: "0 24px 48px rgba(0,0,0,0.5)",
      },
    },
  },
  plugins: [],
};
