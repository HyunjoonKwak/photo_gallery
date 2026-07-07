import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Dev server proxies /api to the FastAPI backend so the browser stays
// same-origin (HttpOnly session cookie works without CORS gymnastics).
const BACKEND = process.env.VITE_BACKEND_URL ?? "http://localhost:9800";

// 빌드 시각(UTC, 분 단위) — 화면에 표식으로 노출해 기기가 어떤 빌드를
// 실행 중인지 즉시 확인(캐시로 옛 코드가 붙었는지 진단).
const BUILD_ID = new Date().toISOString().slice(5, 16).replace("T", " ");

export default defineConfig({
  define: {
    __BUILD_ID__: JSON.stringify(BUILD_ID),
  },
  plugins: [
    react(),
    VitePWA({
      // autoUpdate: 새 버전이 배포되면 새 SW가 skipWaiting으로 즉시 활성화되고
      // 앱이 자동 새로고침해 반영한다. prompt(수동 "새로고침") 방식은 사용자가
      // 토스트를 놓치면 기기가 옛 캐시 JS에 영영 묶여 수정이 도달 못 하던
      // 문제가 있었다.
      registerType: "autoUpdate",
      injectRegister: false, // 등록은 앱(PwaUpdater)에서 직접
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
        // 새 SW가 대기 없이 즉시 활성화·제어 → 배포가 다음 로드에 반영된다.
        skipWaiting: true,
        clientsClaim: true,
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
