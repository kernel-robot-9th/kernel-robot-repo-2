#!/usr/bin/env python3
# =============================================================================
# 파일   : ollama_ws/check_ollama.py
# 역할   : Ollama가 VLA 플래너가 쓰는 방식 그대로 답하는지 확인 (표준 라이브러리만)
# 작성일 : 2026-10-20
# 구성   :
#   - list_models()   GET /api/tags — 모델이 받아져 있는지
#   - ask_plan()      POST /api/chat — stream false, format=JSON 스키마(enum), temperature 0 (vla_planner llm_plan.ask_ollama와 같음)
#   - main()          두 가지를 확인하고 걸린 시간을 보여 준다. 종료 코드 0 정상 · 1 실패
# 사용: python3 check_ollama.py [--host http://localhost:11434] [--model gemma4:e2b]
# =============================================================================
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "gemma4:e2b"   # robot/src/vla_planner_robot/vla_planner/config/planner.yaml 의 model
BLOCK_IDS = ["red_0", "blue_0", "yellow_0"]
REGIONS = ["center", "left", "right", "front", "back"]


def request(host: str, path: str, body: dict | None = None, timeout_s: float = 120.0) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(host.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def list_models(host: str) -> list[str]:
    """[출력] 받아 둔 모델 이름 목록"""
    return [model["name"] for model in request(host, "/api/tags").get("models", [])]


def ask_plan(host: str, model: str, command: str) -> tuple[dict, float]:
    """플래너와 같은 형식의 요청. [출력] (JSON 답, 걸린 초)"""
    schema = {   # 플래너처럼 '고를 수 있는 값'만 enum으로 준다 — LLM이 좌표를 지어내지 못하게
        "type": "object",
        "properties": {"steps": {"type": "array", "items": {
            "type": "object",
            "properties": {"pick": {"type": "string", "enum": BLOCK_IDS},
                           "place": {"type": "string", "enum": REGIONS}},
            "required": ["pick", "place"]}}},
        "required": ["steps"],
    }
    body = {
        "model": model, "stream": False, "format": schema, "options": {"temperature": 0.0},
        "messages": [
            {"role": "system", "content": "You plan pick-and-place for a robot arm. Choose block ids and regions only from the schema."},
            {"role": "user", "content": f"Blocks: {', '.join(BLOCK_IDS)}. Command: {command}"},
        ],
    }
    started = time.monotonic()
    reply = request(host, "/api/chat", body)
    return json.loads(reply["message"]["content"]), time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(description="Ollama가 VLA 플래너 형식으로 답하는지 확인")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    arguments = parser.parse_args()
    try:
        models = list_models(arguments.host)
    except (urllib.error.URLError, OSError) as error:
        print(f"[실패] Ollama에 연결하지 못했습니다 ({arguments.host}): {error}\n  → systemctl status ollama / ollama serve")
        return 1
    if arguments.model not in models:
        print(f"[실패] 모델 {arguments.model}이(가) 없습니다. 받아 둔 모델: {models or '없음'}\n  → ollama pull {arguments.model}")
        return 1
    print(f"[확인] Ollama {arguments.host} · 모델 {arguments.model} 있음")
    for command in ("빨간 블록을 가운데로 옮겨", "put the blue block on the left"):
        try:
            plan, elapsed_s = ask_plan(arguments.host, arguments.model, command)
        except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as error:
            print(f"[실패] '{command}' 요청 실패: {error}")
            return 1
        steps = plan.get("steps") or []
        valid = bool(steps) and all(step.get("pick") in BLOCK_IDS and step.get("place") in REGIONS for step in steps)
        print(f"[{'확인' if valid else '실패'}] '{command}' → {json.dumps(steps, ensure_ascii=False)} ({elapsed_s:.1f}초)")
        if not valid:
            return 1
    print("정상: VLA 플래너가 이 Ollama를 쓸 수 있습니다 (첫 요청은 모델을 GPU에 올리느라 20초 안팎 걸린다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
