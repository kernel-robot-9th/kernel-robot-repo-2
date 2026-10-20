#!/bin/bash
# =============================================================================
# 파일   : ollama_ws/setup_ollama.sh
# 역할   : 로컬 LLM 준비 — Ollama 설치 확인(필요하면 설치) → 서비스 확인 → gemma4:e2b 받기 → 플래너 형식 동작 확인
# 작성일 : 2026-10-20
# 사용   : ./setup_ollama.sh            확인하고, 모델이 없으면 받는다 (설치는 하지 않음)
#          ./setup_ollama.sh --install  Ollama가 없으면 공식 설치 스크립트로 고정 버전을 설치 (sudo 필요)
# 검증한 조합(2026-10-20): Ollama 0.40.1 + gemma4:e2b (ID b37049369adf, 4.6 GB, Q4_K_M), Ubuntu 24.04, RTX 5080 16 GB
# =============================================================================
set -e
OLLAMA_VERSION="0.40.1"
MODEL="gemma4:e2b"
HOST="${OLLAMA_URL:-http://localhost:11434}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== 1. Ollama 설치 =="
if command -v ollama >/dev/null 2>&1; then
  echo "있음: $(ollama --version 2>&1 | tail -1) (검증 버전 ${OLLAMA_VERSION})"
elif [ "$1" = "--install" ]; then
  echo "Ollama ${OLLAMA_VERSION} 설치 (공식 스크립트, sudo 비밀번호를 물을 수 있음)"
  curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION="${OLLAMA_VERSION}" sh
else
  echo "없음 — 설치하려면: ./setup_ollama.sh --install"
  echo "       (직접: curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=${OLLAMA_VERSION} sh)"
  exit 1
fi

echo "== 2. 서비스 =="
if systemctl is-active --quiet ollama 2>/dev/null; then
  echo "systemd ollama.service 실행 중 (부팅 시 자동 시작)"
elif curl -s --max-time 3 "${HOST}/api/tags" >/dev/null; then
  echo "systemd 서비스는 아니지만 ${HOST}에서 응답함 (ollama serve로 띄운 상태)"
else
  echo "응답 없음 — sudo systemctl enable --now ollama   (또는 다른 터미널에서 ollama serve)"
  exit 1
fi

echo "== 3. 모델 ${MODEL} =="
if ollama list | awk 'NR>1 {print $1}' | grep -qx "${MODEL}"; then
  echo "있음: $(ollama list | awk -v m="${MODEL}" '$1==m {print $2, $3, $4}')"
else
  echo "없음 — 받습니다 (약 4.6 GB)"
  ollama pull "${MODEL}"
fi

echo "== 4. 플래너 형식 동작 확인 =="
python3 "${HERE}/check_ollama.py" --host "${HOST}" --model "${MODEL}"
