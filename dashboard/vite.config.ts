import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  // Recharts makes one ~600 kB bundle; fine for a static page.
  build: { chunkSizeWarningLimit: 900 },
});
