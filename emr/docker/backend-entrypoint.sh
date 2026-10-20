#!/bin/sh
# DB가 받을 준비될 때까지 대기 → 마이그레이션 → (선택) 시드 → 서버
set -e
echo "[api] waiting for db..."
until python -c "import psycopg,os; psycopg.connect(os.environ['DATABASE_URL'].replace('postgresql+psycopg://','postgresql://')).close()" 2>/dev/null; do
  sleep 1
done
echo "[api] alembic upgrade head"
alembic upgrade head
if [ "${SEED:-0}" = "1" ]; then
  echo "[api] seed"
  python -m scripts.seed || echo "[api] seed skipped (already seeded?)"
fi
# --timeout-graceful-shutdown 5: 코드 수정으로 --reload가 재시작할 때 열린 SSE 알림 연결(최대 600초)을 기다리지 않고
# 5초 뒤 끊는다 — 없으면 그동안 API가 응답하지 않았다(2026-10-19). 브라우저는 알림 연결을 자동으로 다시 붙인다
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --timeout-graceful-shutdown 5
