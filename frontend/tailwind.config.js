/**
 * Tailwind configuration.
 *
 * `content` lists every file that can contain class names so the JIT compiler
 * keeps the output CSS tiny — that includes the JS modules, which build DOM with
 * className strings.
 *
 * The theme extension defines JobHub's small design language:
 *   - `brand` : the single accent colour (links, primary buttons, active filters)
 *   - `ink`   : text greys
 *   - a slightly larger default border radius for the "soft card" look
 */
module.exports = {
  content: ["./*.html", "./js/**/*.js"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef4ff",
          100: "#d9e6ff",
          200: "#b6ccff",
          300: "#8aa9ff",
          400: "#5c7dfa",
          500: "#3b5bdb", // primary
          600: "#2f49b8",
          700: "#283c96",
          800: "#243377",
          900: "#1f2c5f",
        },
        // Text greys — a warmer, slightly softer scale than pure slate.
        ink: {
          400: "#8a94a6",
          500: "#667085",
          700: "#3f4756",
          800: "#2b313c",
          900: "#1a1f27",
        },
      },
      borderRadius: {
        card: "0.875rem",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.08)",
        "card-hover": "0 4px 12px rgba(16,24,40,0.10)",
      },
    },
  },
  plugins: [],
};
