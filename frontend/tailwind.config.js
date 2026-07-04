/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx}", "./lib/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ['"Plus Jakarta Sans"', "system-ui", "sans-serif"] },
      colors: {
        ink: "#1b2230",
        muted: "#8b91a1",
        line: "#edeff3",
        accent: "#2f7ff0",
        accentink: "#2a5fb8",
        accentsoft: "#d8e6fb",
      },
      boxShadow: { soft: "0 8px 30px rgba(24,39,75,.10)" },
    },
  },
  plugins: [],
};
