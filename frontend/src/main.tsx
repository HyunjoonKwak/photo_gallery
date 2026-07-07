import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

// 뒤로가기 트랩 센티넬을 가능한 가장 이른 시점(React 렌더/로그인 게이팅 전)에
// 깔아, 앱을 열자마자 누른 첫 뒤로가기도 종료 확인이 걸리게 한다.
if (!(history.state as { __nav?: boolean } | null)?.__nav) {
  history.pushState({ __nav: true }, "");
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, staleTime: 30_000 },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
