import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the FastAPI backend so the browser stays
// same-origin (HttpOnly session cookie works without CORS gymnastics).
const BACKEND = process.env.VITE_BACKEND_URL ?? "http://localhost:9800";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
});
