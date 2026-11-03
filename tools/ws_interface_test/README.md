# WebSocket·MQTT 인터페이스 시험 (2026-10-22)

블록도(Lv.1)의 두 통신 구간을 팀이 미리 맞춰 보는 **독립 시험 도구**다. EMR과 로봇 코드는 건드리지 않는다.

| 구간 (블록도) | 이 도구에서 | 누가 쓰나 |
|---|---|---|
| GUI ↔ 서버: REST + **WebSocket** (실시간 상태·알림 push) | WebSocket 시험 서버 `:8765` + 브라우저 시험 페이지 | 웹 팀 |
| 서버 ↔ 로봇: rosbridge / **MQTT** (작업 지시, 상태·위치 보고, 이벤트) | MQTT 브로커(Mosquitto) `:1883` + 토픽 규칙 + 감시기 | 로봇 팀 |
| 둘을 잇기 | 시험 서버의 **WebSocket ↔ MQTT 다리**(`--mqtt`) | 웹 팀 ↔ 로봇 팀 |

**두 방식 모두 메시지 모양(봉투·종류·필드)이 같다.** WebSocket은 서버 하나로, MQTT는 토픽으로 보낼 곳을 정한다는 점만 다르다.
인증·암호화가 없으니 **시험망에서만** 쓴다.

## 지금 이 서버(192.168.129.135)에 떠 있는 것

| 무엇 | 주소 |
|---|---|
| 브라우저 시험 페이지 (WebSocket GUI) | **http://192.168.129.135:8765/** |
| WebSocket | `ws://192.168.129.135:8765/?role=<gui\|robot>&name=<이름>` |
| MQTT 브로커 | `192.168.129.135:1883` (TCP) · `ws://192.168.129.135:9001` (브라우저용 MQTT over WebSocket) |
| 로봇 흉내 | WebSocket `pinky_sim`, MQTT `pinky_mqtt` — 작업을 받으면 단계 보고를 자동으로 보냄 |
| 규격 감시기 | MQTT `hospital/#` 전체를 검사해 OK/ERR 기록 (`logs/mqtt_<날짜>.jsonl`) |

## 1. 빠르게 해 보기

### 웹 팀 — 브라우저만 있으면 된다
1. http://192.168.129.135:8765/ 를 연다.
2. 역할 `gui`, 이름(예: `web-kim`)으로 **접속**한다. 접속 목록에 `pinky_sim · robot`, `pinky_mqtt · robot (mqtt)`가 보인다.
3. 메시지 종류 `task_assign`, 받는 쪽 `pinky_mqtt`(MQTT 로봇) 또는 `pinky_sim`(WebSocket 로봇)으로 **보내기**를 누른다.
4. 오른쪽에 `ack` → `task_progress`(accepted) → `robot_status` 3번 → `arrived` → `done`이 차례로 쌓인다.

### 로봇 팀 — MQTT로 붙기
브로커 `192.168.129.135:1883`에 붙어서 아래 **토픽 규칙**대로 주고받는다. 가장 작은 파이썬 예(`pip install paho-mqtt==2.1.0`):

```python
import json, time, uuid, datetime
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

NAME = "pinky_kim"                                   # 내 로봇 이름 (토픽에 들어감)
def envelope(type_, payload, to="*"):
    return json.dumps({"id": uuid.uuid4().hex[:12], "type": type_, "from": NAME, "to": to,
                       "ts": datetime.datetime.now(datetime.UTC).isoformat(), "payload": payload})

client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"robot-{NAME}")
client.will_set(f"hospital/robot/{NAME}/online", "0", qos=1, retain=True)       # 끊기면 브로커가 0을 대신 보냄
client.on_connect = lambda c, u, f, rc, p: (c.subscribe(f"hospital/robot/{NAME}/cmd", 1),
                                            c.publish(f"hospital/robot/{NAME}/online", "1", qos=1, retain=True))
def on_message(c, u, msg):
    cmd = json.loads(msg.payload)                                                   # task_assign · task_cancel
    print("받음", cmd["type"], cmd["payload"])
    if cmd["type"] == "task_assign":
        c.publish(f"hospital/robot/{NAME}/progress",
                  envelope("task_progress", {"task_id": cmd["payload"]["task_id"], "stage": "accepted"}, cmd["from"]), qos=1)
client.on_message = on_message
client.connect("192.168.129.135", 1883)
client.loop_start()
while True:                                                                         # 1초마다 상태·위치 보고
    client.publish(f"hospital/robot/{NAME}/status", envelope("robot_status",
        {"mode": "idle", "battery_percent": 90, "x_m": 0.0, "y_m": 0.0, "yaw_rad": 0.0}), qos=0, retain=True)
    time.sleep(1)
```

- 붙고 나면 브라우저 시험 페이지의 접속 목록에 `pinky_kim · robot (mqtt)`가 생기고, 웹 팀이 보낸 `task_assign`이 `hospital/robot/pinky_kim/cmd`로 온다.
- 규격에 맞는지는 감시기 출력(아래 3절)으로 바로 본다.

### 명령줄만으로 (설치 없이, 이 서버에서)
브로커 컨테이너에 들어 있는 `mosquitto_sub`·`mosquitto_pub`를 쓴다.
```bash
docker exec interface-test-mosquitto mosquitto_sub -t 'hospital/#' -v          # 오가는 것 전부 보기
docker exec interface-test-mosquitto mosquitto_pub -t hospital/robot/pinky_mqtt/cmd -q 1 -m \
  '{"id":"cli1","type":"task_assign","from":"cli","to":"pinky_mqtt","ts":"2026-10-22T00:00:00Z",
    "payload":{"task_id":"T-9","delivery_id":9,"destination":{"name":"301호","x_m":0.26,"y_m":-0.92,"yaw_rad":0.0}}}'
```

## 2. 메시지 규격 (WebSocket·MQTT 공통)

### 봉투
```json
{"id": "a9ba27c95a45", "type": "task_assign", "from": "nurse-ui", "to": "pinky_1",
 "ts": "2026-10-22T07:44:10Z", "payload": { ... }}
```
| 필드 | 뜻 |
|---|---|
| `id` | 메시지 id. WebSocket에선 `ack`·`error`의 `message_id`가 이 값 |
| `type` | 메시지 종류 (아래 표) |
| `from` | 보낸 쪽 이름. WebSocket은 **서버가 접속 이름으로 다시 찍는다**. MQTT 로봇 토픽은 **토픽의 로봇 이름과 같아야 한다**(감시기가 검사) |
| `to` | 받는 쪽 이름, 또는 `*` = 그 메시지를 받는 역할 전체 |
| `ts` | UTC ISO 8601 |
| `payload` | 종류별 내용. 단위는 이름에 붙인다(`x_m`, `yaw_rad`, `battery_percent`) |

### 메시지 종류
| type | 보내는 쪽 → 받는 쪽 | payload 필수 | 뜻 |
|---|---|---|---|
| `task_assign` | gui → robot | `task_id`, `delivery_id`, `destination{name, x_m, y_m, yaw_rad}` | 배송 작업 지시 |
| `task_cancel` | gui → robot | `task_id`, `reason` | 작업 취소 |
| `robot_status` | robot → gui | `mode`(idle·moving·waiting·charging·error), `battery_percent`(0–100), `x_m`, `y_m`, `yaw_rad` | 상태·위치 보고 |
| `task_progress` | robot → gui | `task_id`, `stage`(accepted·arrived·done·failed) — failed면 `failure_reason` | 작업 단계 |
| `robot_event` | robot → gui | `level`(info·warning·critical), `code`, `message` | 이벤트 업링크 |
| `alert` | gui·robot → gui | `level`, `code`, `message` | 알림 push |
| `ping` → `pong` | → 서버 | — | (WebSocket만) 연결 확인 |
| `hello` · `presence` · `ack` · `error` | 서버 → 클라이언트 | — | (WebSocket만) 접속 안내 · 접속/끊김 · 전달 완료(`delivered_to`) · 거부(`code`) |

### MQTT 토픽 규칙 (`mqtt_topics.py`)
| 토픽 | 실리는 메시지 | 방향 | QoS | retain |
|---|---|---|---|---|
| `hospital/robot/<로봇>/cmd` | `task_assign`, `task_cancel` | gui → 그 로봇 | 1 | 아니오 |
| `hospital/robot/<로봇>/status` | `robot_status` | 로봇 → gui | 0 | **예** (새로 붙은 쪽도 최신 상태를 바로 받음) |
| `hospital/robot/<로봇>/progress` | `task_progress` | 로봇 → gui | 1 | 아니오 |
| `hospital/robot/<로봇>/event` | `robot_event` | 로봇 → gui | 1 | 아니오 |
| `hospital/robot/<로봇>/online` | 문자열 `"1"` / `"0"` (JSON 아님) | 로봇 → gui | 1 | **예**. 붙으면 `1`, 끊기면 **Last Will**로 브로커가 `0` |
| `hospital/gui/alert` | `alert` | → gui | 1 | 아니오 |

- 구독: 로봇은 `hospital/robot/<내 이름>/cmd`, GUI는 `hospital/robot/+/status|progress|event|online`과 `hospital/gui/alert`.
- `<로봇>` 이름에 `/`, `+`, `#`는 쓸 수 없다.

### 오류 코드
WebSocket은 서버가 `error` 메시지로 돌려준다. MQTT는 브로커가 막지 않으므로 **감시기가 ERR로 표시**한다.

| code | 뜻 |
|---|---|
| `invalid_json` | JSON이 아님 |
| `invalid_envelope` | `type`·`payload`·`to` 형식이 틀림 |
| `unknown_type` | 규격에 없는 메시지 종류 |
| `sender_not_allowed` | 이 역할은 이 메시지를 보낼 수 없음 (예: 로봇이 `task_assign`) |
| `missing_field` | payload 필수 필드 없음 |
| `invalid_value` | 값이 범위 밖 (배터리 0–100, mode·stage·level 목록 등) |
| `target_not_found` / `target_role_mismatch` | (WebSocket) `to`의 클라이언트가 없음 / 받는 역할이 아님 |
| `unknown_topic` / `wrong_topic` | (MQTT) 규칙에 없는 토픽 / 그 토픽에 실을 수 없는 종류 |
| `from_mismatch` / `to_mismatch` | (MQTT) `from`이 토픽의 로봇과 다름 / cmd의 `to`가 토픽의 로봇과 다름 |

## 3. 띄우기·끄기 (서버 관리자용)

```bash
cd ~/dev_ws/tools/ws_interface_test
# 처음 한 번: 브로커 + 파이썬 환경 (paho-mqtt는 이 폴더 .venv에만, 시스템 websockets 재사용)
(cd mqtt && docker compose up -d)                                   # Mosquitto :1883, :9001
/usr/bin/python3 -m venv --system-site-packages .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python server.py --port 8765 --log logs/ --mqtt localhost:1883   # WebSocket 서버 + MQTT 다리 (--mqtt 빼면 WebSocket만)
.venv/bin/python mqtt_monitor.py --log logs/                               # MQTT 규격 감시 (OK/ERR)
.venv/bin/python mqtt_client.py --role robot --name pinky_mqtt --auto      # MQTT 로봇 흉내
.venv/bin/python client.py --role robot --name pinky_sim --auto            # WebSocket 로봇 흉내

.venv/bin/python mqtt_client.py --role gui --name tester --send task_assign --to pinky_mqtt   # MQTT로 한 번 보내기
.venv/bin/python mqtt_client.py --role gui --name tester                                      # MQTT 대화형: send <type> [to] [json]
.venv/bin/python client.py --role gui --name tester                                           # WebSocket 대화형

(cd mqtt && docker compose down)                                     # 브로커 끄기
```
기록: `logs/ws_<날짜>.jsonl`(WebSocket 프레임·다리에서 MQTT로 보낸 것), `logs/mqtt_<날짜>.jsonl`(감시 결과). `logs/`·`.venv/`는 git에 올리지 않는다.

## 4. 파일

| 파일 | 내용 |
|---|---|
| `messages.py` | **메시지 규격 한 곳**: 종류·보내는 쪽·받는 쪽·필수 필드·값 범위·예시 |
| `server.py` | WebSocket 시험 서버 + 시험 페이지·`/specs.json` 제공 (`--mqtt`면 다리 켬) |
| `client.py` | WebSocket 터미널 클라이언트 (한 번 보내기·대화형·로봇 흉내) |
| `test_page.html` | 브라우저 시험 페이지 (규격은 `/specs.json`에서 읽음) |
| `mqtt_topics.py` | MQTT 토픽 규칙 (종류 → 토픽·QoS·retain) |
| `mqtt_client.py` | MQTT 터미널 클라이언트 (보내기 전 규격 검사, Last Will, 로봇 흉내) |
| `mqtt_monitor.py` | MQTT 규격 감시기 (`hospital/#` 전체 OK/ERR) |
| `mqtt_bridge.py` | WebSocket GUI ↔ MQTT 로봇 다리 |
| `mqtt/` | Mosquitto `docker-compose.yml`(eclipse-mosquitto 2.0.20), `mosquitto.conf` |
| `test_ws_interface.py`, `test_mqtt_interface.py` | 테스트 25개 (MQTT 통합 테스트는 브로커가 떠 있을 때만) |
| `requirements.txt` · `pytest.ini` | `paho-mqtt==2.1.0`, `websockets>=13`, `pytest` · 이 폴더 테스트만 모으기 (`.venv/bin/python -m pytest -q`) |

## 5. 확인한 것 (2026-10-22)

- 테스트 25개 통과: WebSocket 14(규격 검사 11, 중계·접속 거부·HTTP 3), MQTT 11(토픽 규칙, 감시 검사 9, WebSocket GUI ↔ 다리 ↔ MQTT 로봇 1).
- 실제로 띄워서 확인: 브라우저(WebSocket GUI)가 MQTT 로봇 `pinky_mqtt`에 `task_assign` → `ack`(`delivered_to: ["mqtt:pinky_mqtt"]`) → accepted → 상태 3번 → arrived → done → idle이 페이지에 순서대로 표시. 감시기 9건 모두 OK.
- 테스트가 브로커에 retain을 남기지 않는 것도 확인.

## 6. 규격을 바꿀 때

`messages.py`(종류·필드·값)와 `mqtt_topics.py`(토픽)를 고치고 두 테스트를 돌린다. 시험 페이지는 `/specs.json`으로 같은 규격을 읽어 따로 고칠 필요가 없다.
EMR이나 로봇 코드에 실제로 넣기로 하면, 그 전에 `docs/`의 API 계약 문서에 2절 표를 옮겨 양쪽이 맞춘다.
