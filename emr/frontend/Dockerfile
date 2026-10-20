# =============================================================================
# 파일   : Dockerfile
# 역할   : 프론트엔드 이미지 — dev(Vite 핫리로드) / build / prod(nginx 정적) 3단계
# 작성일 : 2026-10-14
# 사용   : docker compose up dev      → http://localhost:5173 (소스 수정 즉시 반영)
#          docker compose up prod     → http://localhost:8080 (빌드 결과물)
# =============================================================================

# ---------- 공통: 의존성만 설치한 레이어 (소스 바뀌어도 캐시 유지) ----------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci

# ---------- dev: 소스는 볼륨으로 마운트, Vite 개발 서버 ----------
FROM deps AS dev
ENV CHOKIDAR_USEPOLLING=true
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---------- build: 타입 검사 + 번들 ----------
FROM deps AS build
COPY . .
ARG VITE_API_URL=http://localhost:8000/api/v1
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ---------- prod: nginx 가 dist/ 만 서빙 (SPA 라우팅 포함) ----------
FROM nginx:1.27-alpine AS prod
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
