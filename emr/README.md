# EMR 비품·배송 — 통합 폴더

```
emr/
├─ docker-compose.yml          db + api + web 한 번에
├─ .env.example                JWT_SECRET · SEED · VITE_API_URL
├─ docker/
│  ├─ backend.Dockerfile       python:3.12-slim, requirements.txt 설치
│  └─ backend-entrypoint.sh    db 대기 → alembic upgrade head → seed → uvicorn
├─ backend/                    FastAPI 백엔드 (emr_backend, 2026-10-15 기준 포함)
└─ frontend/                   React 19 + Vite 8 + TS (Dockerfile 포함)
```

## 처음 한 번
```bash
cp .env.example .env            # JWT_SECRET 아무 긴 문자열로
docker compose up --build
```
- web  http://localhost:5173  (N001 관리자 · N002 일반 간호사 / 비밀번호 nurse1234)
- api  http://localhost:8000/docs
- 첫 기동 후 `.env`의 `SEED=0`으로 바꿔 둔다 (시드 중복 방지)

## 운영 배포 전에 (개발 환경과 다른 점)
- **JWT_SECRET**: `.env.example` 값은 개발용이다. 운영 키는 32바이트 이상 무작위 값으로 만들어 운영 `.env`에만 둔다(저장소에 올리지 않는다). 키를 바꾸면 이미 로그인한 사람은 다시 로그인해야 한다.
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # 또는 openssl rand -base64 48
  ```
- **HTTPS 필수**: 로그인·비밀번호 변경은 비밀번호를 요청 본문에 평문으로 보낸다(서버는 bcrypt 해시로만 저장). 지금 compose는 `http://`라 네트워크 구간이 암호화되지 않는다 — 운영에서는 리버스 프록시(nginx 등) 뒤에서 TLS로만 연다.
- **첫 관리자**: 마이그레이션 0002가 사번 `N001`을 관리자로 바꾼다. 운영 DB에 N001이 없으면 관리자가 없으니, 지정 방법을 따로 정한다(열린 항목).
- **마이그레이션**: 2026-10-15에 0001~0014를 `0001_baseline` 하나로 합쳤다. 그 전에 만든 DB는 `docker compose down -v`로 다시 만든다.

## 평소
```bash
docker compose up          # 빌드 캐시 사용
docker compose down        # 중지 (DB 데이터는 pgdata 볼륨에 유지)
docker compose down -v     # DB까지 초기화
```
`backend/`·`frontend/` 소스를 고치면 둘 다 `--reload`라 재시작 없이 반영된다. `requirements.txt`나 `package.json`을 바꿨을 때만 `--build`.

## 백엔드 가정 (backend-entrypoint.sh)
- `requirements.txt`에 `psycopg[binary]` 포함 (DB 대기 체크에 사용)
- `alembic.ini`가 `backend/` 바로 아래
- `scripts/seed.py`가 두 번 실행돼도 죽지만 않으면 됨 (실패해도 서버는 뜸)
- 설정은 환경변수 `DATABASE_URL` `JWT_SECRET` `JWT_EXPIRE_MINUTES` `CORS_ORIGINS` `NURSE_RECEIPT_METHOD`(button|marker, 2026-10-22)로 읽음 (pydantic-settings)

## 프론트 타입 재생성
```bash
docker compose exec -e OPENAPI_URL=http://api:8000/openapi.json web npm run gen   # api 컨테이너의 /openapi.json → frontend/src/api/schema.d.ts
```
`gen`의 기본 주소는 `localhost:8000`이라 컨테이너 안에서는 닿지 않는다 — 위처럼 `OPENAPI_URL`로 컨테이너 내부 주소를 넘긴다.

## 다른 PC에서 접속
브라우저는 같은 주소의 `/api/v1`을 부르고 Vite 개발 서버가 api 컨테이너로 넘긴다(`frontend/vite.config.ts` proxy). 그래서 `http://<이 PC의 IP>:5173`으로 접속하면 된다. `.env`의 `VITE_API_URL`은 `/api/v1`로 둔다 — `http://localhost:8000/...`이면 다른 PC의 브라우저가 자기 자신을 불러 '서버에 연결할 수 없습니다'가 뜬다.
