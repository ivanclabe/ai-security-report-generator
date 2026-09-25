/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Matches the client's brand green already used in the generated
        // .docx (DARK_GREEN #00532A in docx_builder.py) so the app and the
        // documents it produces share one visual identity.
        brand: {
          50: "#E6F0EA",
          100: "#C2DBCC",
          200: "#8FBCA0",
          400: "#2C7A50",
          500: "#00532A",
          600: "#004423",
          700: "#00351B",
          900: "#001F10",
        },
      },
    },
  },
  plugins: [],
};
