import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Dev server proxies /api to the FastAPI backend so the browser stays
// same-origin (HttpOnly session cookie works without CORS gymnastics).
const BACKEND = process.env.VITE_BACKEND_URL ?? "http://localhost:9800";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon-64.png", "apple-touch-icon.png"],
      manifest: {
        name: "NAS 사진 정리",
        short_name: "NAS 사진",
        description: "Synology NAS 가족 사진 감상·정리 앱",
        lang: "ko",
        theme_color: "#2563eb",
        background_color: "#ffffff",
        display: "standalone",
        orientation: "any",
        start_url: "/",
        scope: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "icon-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // 앱 셸(빌드 산출물)만 프리캐시 → 오프라인에서도 껍데기는 뜬다.
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff2}"],
        // SPA 라우팅: 내비게이션은 index.html로. 단 /api는 절대 가로채지 않음
        // (인증/동적 응답을 SW가 캐시/대체하면 안 됨).
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api/],
        cleanupOutdatedCaches: true,
      },
      // 개발 중엔 SW 비활성(캐시 혼란 방지). 배포 빌드에서만 동작.
      devOptions: { enabled: false },
    }),
  ],
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
