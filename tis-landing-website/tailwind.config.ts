import type { Config } from "tailwindcss";
import forms from "@tailwindcss/forms";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: "#12202f",
        ocean: "#0f5f76",
        teal: "#168a88",
        mint: "#dff6ee",
        skysoft: "#e9f5fb",
        line: "#d7e2ea"
      },
      boxShadow: {
        soft: "0 18px 50px rgba(18, 32, 47, 0.10)",
        card: "0 14px 34px rgba(18, 32, 47, 0.08)"
      }
    }
  },
  plugins: [forms]
};

export default config;
