# EMR 배송 프론트엔드 (간호사 웹)

백엔드 "EMR 비품·배송 백엔드 현황"(7 테이블, 다른 부서·로봇 연동 보류) 기반. React 19 + Vite 8 + TypeScript + TanStack Query 5 + react-router 8 + Tailwind 4.

## 실행
통합 실행(db + api + web)은 상위 폴더 `emr/README.md`의 `docker compose up` 을 쓴다. 아래는 이 폴더만 단독으로 띄울 때.

## 실행 — 로컬 Node
```bash
node -v                      # 20.19+ 또는 22.12+
npm install                  # .npmrc 의 legacy-peer-deps 가 자동 적용
cp .env.example .env
npm run dev                  # http://localhost:5173
```
시드 계정 N001 / nurse1234.

## 스크립트
| 명령 | 역할 |
|---|---|
| `npm run dev` | 개발 서버 |
| `npm run typecheck` | strict 타입 검사 |
| `npm run build` | 타입 검사 + 번들 (`dist/`) |
| `npm run gen` | `OPENAPI_URL`(기본 `http://localhost:8000/openapi.json`) → `src/api/schema.d.ts` |

## 구조
```
Dockerfile          deps → dev(Vite) / build → prod(nginx) 다단계
docker-compose.yml  dev(5173, 볼륨 마운트) · prod(8080) 프로필
docker/nginx.conf   SPA 라우팅(try_files) + assets 캐시
.npmrc              legacy-peer-deps (openapi-typescript ↔ TS 6 peer 충돌 회피)
src/
├─ api/
│  ├─ types.ts     백엔드 7테이블 타입 (손으로 옮김 — gen 결과와 대조 필요 [검토 필요])
│  ├─ client.ts    fetch 래퍼: JWT 자동 첨부, {code,detail} → ApiRequestError
│  └─ hooks.ts     TanStack Query 훅 (리소스별 조회·변경)
├─ components/     ui.tsx(버튼·테이블·배지), Layout.tsx(메뉴)
├─ features/deliveries/DeliveryForm.tsx   예약 생성 폼
├─ pages/          Login · Deliveries · MapView · Supplies · Nurses · Sites(장소·맵·로봇)
├─ router.tsx      로그인 가드 + 경로
└─ main.tsx
```

## 화면 ↔ API
| 화면 | API |
|---|---|
| 로그인 | `POST /auth/login`, `GET /auth/me` |
| 배송 예약 | `GET·POST /deliveries`, `PATCH /deliveries/{id}`, `POST /deliveries/{id}/cancel` — 상태는 reserved·cancelled뿐, 변경·취소는 reserved에서만 |
| 맵 | `GET /maps`, `GET /locations`, `GET /robots` — 장소 마커를 평면도 위에 표시 |
| 비품 | `GET·POST /supplies`, `PATCH·DELETE /supplies/{id}` |
| 간호사 | `GET·POST /nurses`, `PATCH·DELETE /nurses/{id}` |
| 장소·맵·로봇 | `/locations`, `/maps`(조회만), `/robots` CRUD |

## 평면도 이미지
`public/maps/<file_name 확장자 제외>.png` (예: `public/maps/ward3.png`)를 두면 맵 화면 격자 위에 표시된다. 없으면 격자만 보인다.

## [검토 필요]
- `src/api/types.ts` 필드명 — `npm run gen` 후 `schema.d.ts`와 대조
- 로봇 실시간 위치 — 백엔드 "관제" 결정 후 `Robot`에 x·y 추가, `MapView`에 마커 1개 추가
- 다른 부서 연동이 들어오면 `useDeliveries`에 `refetchInterval` 추가 (지금은 상태를 바꾸는 주체가 본인뿐이라 폴링 없음)
