# Pinky REST API 목록

- 주소: `http://<로봇 IP>:8080` (지금 FASTCAMPUS_10F 에서 **pinky_6364 = `192.168.129.68`** (2026-10-26~; ee3a = .107, 62f4 = .122), 로봇 AP 에서는 `192.168.4.1`)
- **Swagger UI: `http://<로봇 IP>:8080/docs`** (여기서 바로 눌러 볼 수 있음, 화면을 그리는 데 인터넷 필요) · OpenAPI 명세: `/openapi.json`
- 좌표: 그림 cm (아레나 왼쪽 아래 원점, x 오른쪽, y 위), 위치 = **라이다 중심**, heading deg (0 = +x, 90 = +y, 반시계 +)
- 본문은 JSON (`Content-Type: application/json`). 오류는 `{"error": "..."}`
- 한 번에 작업 하나. ⚠️ `POST /goto` 만 로봇을 움직인다
- 로봇이 켜지면 bringup·Nav2·API 가 저절로 뜸. 단 AMCL 은 A 에서 시작 → 로봇이 다른 곳이면 먼저 `POST /set_pose`

| 메서드 | 경로 | 하는 일 | 보내는 것 | 응답 |
|---|---|---|---|---|
| GET | `/status` | 위치·상태·지금 작업 | — | `pose`, `localized`, `nav2_ready`, `state`(idle/running), `job`, `robot`(serial·IP) |
| GET | `/dests` | 목적지 이름 목록 | — | `{이름: {xy, heading, name, dock}}` |
| GET | `/plan` | 경로만 계산 (안 움직임) | `?dest=PHARMACY` 또는 `?x=60&y=145[&heading=180]`, `&dock=true`, `&from=x,y,h` | 노드·점·구간 목록 |
| POST | `/goto` | 주행 시작 ⚠️ | `{"x":60,"y":145,"heading":180}` 또는 `{"dest":"PHARMACY"}` (PHARMACY 는 dock 기본 true) | 202 `{job, plan}` · 400 못 가는 곳 · 409 다른 작업 중 · 503 위치 모름 |
| POST | `/cancel` | 지금 작업 멈춤 | — | `{canceled: 작업 id, state}` |
| GET | `/jobs` | 최근 작업 (최신 먼저, 50개) | — | 작업 요약 목록 |
| GET | `/jobs/<id>` | 작업 상세 | — | `state`, `segment`/`segments_total`, `progress`(남은 cm), 구간별 `results`, `end_pose`, `end_error_cm` |
| POST | `/set_pose` | AMCL 시작 위치 넣기 + 스캔 확인 (안 움직임) | `{"name":"A"}` / `{"x":..,"y":..,"heading":..}` / `{"find":true}` | 200 맞음 · 422 안 맞음, `output`, `pose` |
| GET / PUT | `/notify` | 도착 신호 설정 보기 / 등록 | `{"url":"http://…", "dests":["PHARMACY"]}` (url null = 끔) | 저장된 설정 |
| GET | `/docs` | Swagger UI | — | HTML |
| GET | `/openapi.json` | OpenAPI 3 명세 | — | JSON |

작업 `state`: `running` → `succeeded` / `failed` / `canceled`. 구간 `mode`: `nav`(Nav2) · `wall`(협로 벽 따라가기) · `rotate` · `dock`(정밀 주차).

방 번호 (2026-10-27 확정, `/dests` 의 `name` 앞에 붙음): 101호 ROOM4_L, 102호 ROOM4_R, 103호 ROOM1_LU, 104호 ROOM1_CUL, 105호 ROOM1_CUR, 106호 ROOM1_LD, 107호 ROOM1_CLL, 108호 ROOM1_CLR, 수술실 SURGERY. 로봇 API 의 `dest` 는 노드 이름 그대로다 (방 번호로 주문하는 건 FMS API — fms 브랜치 `fms/API.md`).

목적지 이름 (`/dests`): ROOM4_L, PHARMACY(정밀 주차 가능), ROOM4_R, ROOM1_CUL, ROOM1_CUR, ROOM1_CLL, ROOM1_CLR, ROOM1_LU, ROOM1_LD(왼쪽 1인실 — 10-26 엶, 30cm 단일차선 협로 경유), SURGERY, POCKET, CHARGER. (START_A 는 2026-10-26 그래프에서 뺌 — 출발점 A 로 가려면 `{"x":182.7,"y":24,"heading":180}`)
`/set_pose` 이름 (tools/points.yaml): A, B, C, D, F, G, start_A, omx_stop, omx_approach.

```bash
B=http://192.168.129.68:8080
curl $B/status
curl -X POST -H "Content-Type: application/json" -d '{"x":182.7,"y":24,"heading":180}' $B/goto
curl $B/jobs/<id>
curl -X POST $B/cancel
```

## 도착 신호 (`/notify`, 2026-10-22)

약제실에 도착하면(정밀 주차를 요청했으면 그것까지 끝나면) 로봇이 등록된 주소로 한 번 알린다 → OMX 가 박스를 내려놓음.
적재 끝은 기다리지 않음 — 다음 `/goto` 는 관제 PC 가 보낸다.

```bash
# 한 번 등록 (로봇에 저장, 재시작해도 남음). 지금 등록된 곳 = 관제 서버(팀원)의 '지금 도착했습니다'
curl -X PUT -H "Content-Type: application/json" -d '{"url":"http://192.168.129.135:8000/api/v1/robot/arrived","dests":["PHARMACY"]}' http://192.168.129.68:8080/notify
# 관제 서버가 로봇 키를 요구하게 되면: ... -d '{"headers":{"X-Robot-Api-Key":"<키>"}}'  (GET /notify 에서는 값이 가려짐)
```

로봇이 보내는 것: `POST <url>`, `Content-Type: application/json`

```json
{"event": "arrived", "dest": "PHARMACY",
 "robot": {"serial": "1cdda27b956a1efc", "ips": ["192.168.129.122", "192.168.4.1"]},
 "job_id": "b709869d", "time": "2026-10-22T21:52:02+0900",
 "pose": {"x": 96.2, "y": 187.1, "heading": 88.5},
 "dock_error": {"fwd_mm": -0.4, "left_mm": 1.7, "heading_deg": 0.4}}
```

- `/goto {"dest":"PHARMACY"}` 는 `dock` 을 안 주면 **정밀 주차까지** 한다. 도착 신호는 **정밀 주차가 성공한 뒤에만** 보냄
  (`"dock": false` 로 보내면 신호 안 보냄 — 작업 `notify.error` 에 이유). 실패·취소, x,y 로 보낸 작업은 안 보냄.
- 연결 실패·5xx 면 1초 간격 3번까지, 4xx 는 다시 안 보냄. 결과는 그 작업의 `notify` (`GET /jobs/<id>`) 에 `{url, status, error, response}`.
- 관제 서버 `/api/v1/robot/arrived` 응답: 200 = 맡은 배송이 arrived 로, **409 robot_no_active_delivery = 로봇에 배정된 배송이 없음**, 401 = 키 문제.
