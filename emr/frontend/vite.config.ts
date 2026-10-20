import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// 개발 서버 5173
// host: true → 도커 컨테이너 안에서도 외부(호스트·다른 PC 브라우저) 접속 허용
// proxy: 브라우저는 같은 주소의 /api/v1을 부르고 Vite가 백엔드로 넘긴다 — 어느 IP로 접속해도 되고 CORS가 필요 없다 (2026-10-19)
//        API_PROXY_TARGET: compose에서는 http://api:8000, 도커 없이 돌리면 기본값 localhost:8000
const API_PROXY_TARGET = process.env.API_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173, host: true, watch: { usePolling: true },
    proxy: { '/api': { target: API_PROXY_TARGET, changeOrigin: true } },
  },
})
