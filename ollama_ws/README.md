# ollama_ws — 로컬 LLM (Ollama + Gemma 4 E2B)

OMX-F 로봇팔의 VLA 플래너(`robot/src/vla_planner_robot/vla_planner`)가 자연어 명령을 작업 계획(JSON)으로 바꿀 때 쓰는 로컬 LLM입니다.
인터넷이나 외부 API 없이 이 PC의 GPU에서 돕니다.

| 항목 | 값 (2026-10-20 검증) |
|---|---|
| 서버 | Ollama 0.40.1, systemd `ollama.service`, `http://localhost:11434` (이 PC 안에서만) |
| 모델 | `gemma4:e2b` — 4.6B, Q4_K_M, 4.6 GB, ID `b37049369adf` |
| 응답 시간 | 첫 요청 약 20초(모델을 GPU에 올림), 그 뒤 약 1초 |
| 플래너 설정 | `vla_planner/config/planner.yaml`·`planner_dual.yaml`의 `ollama_host`, `model`, `llm_timeout` |

## 준비

```bash
cd ~/dev_ws/ollama_ws
./setup_ollama.sh             # 설치 확인 → 서비스 확인 → 모델이 없으면 받기(4.6 GB) → 플래너 형식 동작 확인
./setup_ollama.sh --install   # Ollama가 없으면 검증 버전 0.40.1을 공식 스크립트로 설치 (sudo 필요)
```

설치 명령을 직접 쓰려면 다음과 같습니다.

```bash
curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=0.40.1 sh
ollama pull gemma4:e2b
python3 check_ollama.py       # 플래너와 같은 요청(stream false, JSON 스키마 format, temperature 0)을 보내 확인
```

정상이면 마지막 줄이 `정상: VLA 플래너가 이 Ollama를 쓸 수 있습니다`입니다.

## 플래너가 Ollama를 쓰는 방식

`llm_plan.ask_ollama`가 `POST /api/chat`에 다음을 보냅니다.

- `stream: false`, `options.temperature: 0`
- `format`: 요청마다 만든 JSON 스키마. 지금 보이는 블록 id와 장소 이름만 `enum`으로 허용하므로, LLM이 좌표나 없는 블록을 지어내지 못합니다.
- 답의 `message.content`를 JSON으로 읽어 계획으로 씁니다. 좌표 계산과 안전 검사는 코드(`resolve_plan`)가 합니다.

## 설정을 바꿀 때

| 하고 싶은 것 | 방법 |
|---|---|
| 다른 모델 | `ollama pull <모델>` 뒤 `planner.yaml`의 `model` 변경, `python3 check_ollama.py --model <모델>`로 확인 |
| 다른 PC·로봇에서 이 Ollama 쓰기 | `sudo systemctl edit ollama` → `[Service]` 아래 `Environment="OLLAMA_HOST=0.0.0.0"` → `sudo systemctl restart ollama`. 인증이 없으므로 신뢰하는 네트워크에서만 |
| 다른 PC의 Ollama 쓰기 | `planner.yaml`의 `ollama_host`를 `http://<그 PC IP>:11434`로 |
| 첫 요청 지연 줄이기 | 모델을 메모리에 오래 두기: `Environment="OLLAMA_KEEP_ALIVE=1h"` (기본 5분) |

메모리 주의: 로봇팔 시뮬레이션(Gazebo·MoveIt)과 함께 돌리면 RAM 15 GB가 빠듯합니다. 모델은 GPU 메모리(약 5 GB)를 씁니다.

## 예정

Ollama에 없는 다른 모델을 **Ollama 호환 API**(`POST /api/chat` + `format` JSON 스키마)로 제공하는 서버를 이 폴더에 만들 계획입니다.
그러면 플래너 코드를 고치지 않고 `planner.yaml`의 `ollama_host`·`model`만 바꿔 쓸 수 있습니다. 같은 `check_ollama.py`로 호환 여부를 확인합니다.
