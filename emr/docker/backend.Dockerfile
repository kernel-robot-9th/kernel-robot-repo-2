# =============================================================================
# 파일   : docker/backend.Dockerfile
# 역할   : FastAPI 백엔드 이미지 — backend/ 폴더를 그대로 사용, 코드 수정 없음
# 작성일 : 2026-10-15
# 기동   : alembic upgrade head → (SEED=1이면) scripts.seed → uvicorn :8000
# =============================================================================
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY docker/backend-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8000
CMD ["/entrypoint.sh"]
