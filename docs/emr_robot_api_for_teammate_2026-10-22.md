# 팀원 Pinky FMS ↔ EMR 연동 안내 (2026-10-22)

> **최신 정리는 [`fms_emr_api_2026-10-27.md`](fms_emr_api_2026-10-27.md)** (2026-10-27, 복귀 장소 없앰 · **`/robot/arrived`는 약제실 도착 전용, 병실 도착은 progress arrived**). 공유 페이지 https://claude.ai/artifact/TH6bZL1EVRRimPxnGxGrns

로봇 쪽 프로그램(팀원 Pinky FMS)이 EMR 배송을 가져가서 로봇을 보내고, 도착을 알리는 방법이다. 관제 PC 배송 실행기 없이 FMS가 직접 부른다.

- EMR 주소: `http://192.168.129.135:8000/api/v1` (시험 화면 `http://192.168.129.135:8000/docs`)
- **지금은 인증 없음**: 로봇 키(`X-Robot-Api-Key`)를 안 보내도 된다. 키 없이 부르면 EMR의 **배송로봇 1호**로 처리된다(시험 동안만).
- 본문은 JSON, 오류는 `{"code": "...", "detail": "..."}`. 시각은 UTC ISO 8601.
- 목적지 이름: EMR 장소에 Pinky 목적지 이름(`robot_dest`)이 들어 있다. FMS는 그 이름으로 `POST /goto {"dest": ...}`를 보내면 된다.

## 1. 흐름

```
⓪ (준비) Pinky GET /status 응답에 battery_percent·contamination_percent(0~100)를 넣는다 — EMR이 claim 때 직접 물어본다 (2026-10-23)
EMR에 배송 예약(간호사 화면 또는 POST /deliveries)
   │
   ▼
① FMS: POST /robot/deliveries/claim        → 배송 하나를 맡음 (상태 dispatched, 응답에 목적지 robot_dest)
                                              이때 EMR이 Pinky GET /status를 물어 배터리·오염도·주행 준비가 기준 밖이면 204 + X-Claim-Skip-Reason
② FMS: 로봇 주행  POST <Pinky>/goto {"dest": robot_dest}   (약제실 PHARMACY는 "dock": true 권장)
③ FMS: POST /robot/arrived                  → 도착 (상태 arrived)
④ 간호사가 EMR 화면에서 "받았습니다"        → 수령 (상태 received)
   FMS는 GET /robot/me의 active_delivery가 null이 되면 수령된 것 → 그다음 어디로 갈지는 FMS가 정한다(EMR은 복귀 장소를 정하지 않음, 2026-10-27)
   주행 실패면 ③ 대신 POST /robot/deliveries/{id}/progress {"stage":"failed","failure_reason":"navigation_failed"}
```

## 2. API

| 순서 | 요청 | 하는 일 | 응답 |
|---|---|---|---|
| 상태 | `GET /robot/me` | 내 로봇·맡은 배송 | 아래 예 |
| 조회 | `GET /robot/deliveries?due_only=true` | **맡지 않고** 예약된 배송 목록만(예약 시각 순). 로봇 배정·상태 변경 없음 — 어느 로봇이 갈지는 FMS가 정한다 | 배송 목록(형식은 claim 응답과 같음, `status: reserved`) |
| ① | `POST /robot/deliveries/claim` (본문 없음) | 예약 시각이 지난 배송 중 가장 이른 것 하나를 맡는다. 이미 맡은 게 있으면 그것을 다시 준다. 새 배송을 주기 전에 EMR이 Pinky `/status`를 묻는다(아래) | 200 배송 · **204 맡을 것 없음**(로봇 상태 때문이면 헤더 `X-Claim-Skip-Reason`) |
| ③ | `POST /robot/arrived` (본문 없음) | 맡은 배송을 도착으로 | 200 배송 · 409 `robot_no_active_delivery`(맡은 게 없음) |
| 실패 | `POST /robot/deliveries/{id}/progress` `{"stage": "failed", "failure_reason": "navigation_failed"}` | 실패 보고, 재고 자동 복구 | 200 |

실패 사유: `navigation_failed`(주행 실패) · `not_received`(도착 후 5분 안에 수령 없음) · `destination_blocked`(갈 수 없는 곳) · `robot_error`(그 밖).

### 팀원 Pinky API에 필요한 것 (2026-10-23)

EMR이 claim 때 로봇 서버(EMR 로봇 탭의 "로봇 서버" 주소, 지금 `http://192.168.129.107:8080`)의 `GET /status`를 직접 부른다(2초 제한, GET만). 지금 응답에 있는 `localized`·`nav2_ready`·`state`에 더해 **두 칸을 넣어 달라**:

```json
{"localized": true, "nav2_ready": true, "state": "idle", "battery_percent": 82.5, "contamination_percent": 12, "pose": {"...": "..."}}
```

- `battery_percent`: 0~100 숫자 · `contamination_percent`: 0~100 숫자(0 = 깨끗, 로봇이 잰 값)
- **두 칸이 없으면 EMR은 배송을 주지 않는다**(`robot_status_incomplete`). 2026-10-23 지금이 그 상태다.

claim이 새 배송을 주지 않는 이유 (`X-Claim-Skip-Reason`): `robot_server_not_set`(로봇 서버 주소 없음) · `robot_server_unreachable`(2초 안에 응답 없음·200 아님) · `robot_status_incomplete`(`battery_percent`·`contamination_percent` 0~100이 없음) · `robot_not_ready`(`localized`·`nav2_ready`가 true가 아니거나 `state`가 `idle`이 아님) · `robot_battery_low`(배터리 30 % 미만) · `robot_contamination_high`(오염도 70 초과). 기준값은 가정값이라 바뀔 수 있다.

`GET /robot/me` 예:

```json
{
  "robot": {"id": 1, "name": "배송로봇 1호", "robot_type": "amr"},
  "active_delivery": null,
  "receipt_wait_seconds": 300
}
```

`claim` 응답(배송) 예 — FMS는 `id`와 `destination.robot_dest`만 쓰면 된다:

```json
{
  "id": 32,
  "status": "dispatched",
  "destination": {"id": 9, "name": "약제실 OMX", "robot_dest": "PHARMACY", "map_id": 5, "map_x_m": 0.989, "map_y_m": 1.788, "map_yaw_rad": 1.5708},
  "items": [{"name": "A 약품", "quantity": 1}],
  "scheduled_at": "2026-10-22T13:23:58Z",
  "dispatched_at": "...", "arrived_at": null, "receipt_deadline_at": null,
  "receipt_method": "button"
}
```

## 3. curl로 한 번에 해 보기

```bash
E=http://192.168.129.135:8000/api/v1
curl -i -X POST $E/robot/deliveries/claim     # 배송 #32(약제실 OMX)를 맡음 → robot_dest PHARMACY (204면 X-Claim-Skip-Reason 확인)
# (로봇을 PHARMACY로 보냄 — 예: curl -X POST -H 'Content-Type: application/json' -d '{"dest":"PHARMACY","dock":true}' http://192.168.129.122:8080/goto)
curl -X POST $E/robot/arrived                 # 도착 → EMR 간호사 화면에 "받았습니다" 버튼
curl $E/robot/me                              # 간호사가 누르면 active_delivery가 null
```

## 4. 알아 둘 것

- 로봇 한 대는 배송을 하나씩만 맡는다. 맡은 배송이 끝나야(수령·실패) 다음 `claim`이 새 배송을 준다.
- 맡을 수 있는 배송은 목적지에 **로봇 목적지 이름(`robot_dest`)이 있는 장소**인 것만이다(지금 EMR 장소 id 8–18: 4인실·1인실·약제실 OMX·수술실·대기 포켓·충전·출발점 A). 2026-10-27부터 EMR은 **복귀 장소를 정하지 않는다** — 끝난 뒤 어디로 갈지는 FMS가 정한다(`/robot/me`에 `home_location` 없음).
- 도착 후 5분(`receipt_wait_seconds`) 안에 "받았습니다"가 없으면 FMS가 `not_received`로 실패를 보고하고 복귀하는 것을 권한다(EMR이 스스로 실패시키지는 않는다).
- 시험 중 예약: EMR 화면에서 하거나 `POST /deliveries {"destination_location_id": 9, "scheduled_at": "<지금 UTC>", "items": [{"supply_id": 1, "quantity": 1}]}`.
- 관제 PC 배송 실행기(`robot/src/fms/delivery_executor`)는 **쓰지 않는다**(2026-10-23 결정) — 로봇 쪽 처리(claim·주행·도착)는 FMS가 맡는다.
- 운영 전에는 로봇 키·로그인을 다시 켠다(그때 FMS는 `X-Robot-Api-Key` 헤더를 붙인다).
