import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The web interface runs on http://localhost:5173 and forwards /api calls
// to the backend on port 8000.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
