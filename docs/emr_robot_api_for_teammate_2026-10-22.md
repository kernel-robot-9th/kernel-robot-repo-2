# 팀원 Pinky FMS ↔ EMR 연동 안내 (2026-10-22)

로봇 쪽 프로그램(팀원 Pinky FMS)이 EMR 배송을 가져가서 로봇을 보내고, 도착을 알리는 방법이다. 관제 PC 배송 실행기 없이 FMS가 직접 부른다.

- EMR 주소: `http://192.168.129.135:8000/api/v1` (시험 화면 `http://192.168.129.135:8000/docs`)
- **지금은 인증 없음**: 로봇 키(`X-Robot-Api-Key`)를 안 보내도 된다. 키 없이 부르면 EMR의 **배송로봇 1호**로 처리된다(시험 동안만).
- 본문은 JSON, 오류는 `{"code": "...", "detail": "..."}`. 시각은 UTC ISO 8601.
- 목적지 이름: EMR 장소에 Pinky 목적지 이름(`robot_dest`)이 들어 있다. FMS는 그 이름으로 `POST /goto {"dest": ...}`를 보내면 된다.

## 1. 흐름

```
EMR에 배송 예약(간호사 화면 또는 POST /deliveries)
   │
   ▼
① FMS: POST /robot/deliveries/claim        → 배송 하나를 맡음 (상태 dispatched, 응답에 목적지 robot_dest)
② FMS: 로봇 주행  POST <Pinky>/goto {"dest": robot_dest}   (약제실 PHARMACY는 "dock": true 권장)
③ FMS: POST /robot/arrived                  → 도착 (상태 arrived)
④ 간호사가 EMR 화면에서 "받았습니다"        → 수령 (상태 received)
   FMS는 GET /robot/me의 active_delivery가 null이 되면 수령된 것 → 복귀 (출발점 A = START_A)
   주행 실패면 ③ 대신 POST /robot/deliveries/{id}/progress {"stage":"failed","failure_reason":"navigation_failed"}
```

## 2. API

| 순서 | 요청 | 하는 일 | 응답 |
|---|---|---|---|
| 상태 | `GET /robot/me` | 내 로봇·복귀 장소·맡은 배송 | 아래 예 |
| 조회 | `GET /robot/deliveries?due_only=true` | **맡지 않고** 예약된 배송 목록만(예약 시각 순). 로봇 배정·상태 변경 없음 — 어느 로봇이 갈지는 FMS가 정한다 | 배송 목록(형식은 claim 응답과 같음, `status: reserved`) |
| ① | `POST /robot/deliveries/claim` (본문 없음) | 예약 시각이 지난 배송 중 가장 이른 것 하나를 맡는다. 이미 맡은 게 있으면 그것을 다시 준다 | 200 배송 · **204 맡을 것 없음** |
| ③ | `POST /robot/arrived` (본문 없음) | 맡은 배송을 도착으로 | 200 배송 · 409 `robot_no_active_delivery`(맡은 게 없음) |
| 실패 | `POST /robot/deliveries/{id}/progress` `{"stage": "failed", "failure_reason": "navigation_failed"}` | 실패 보고, 재고 자동 복구 | 200 |

실패 사유: `navigation_failed`(주행 실패) · `not_received`(도착 후 5분 안에 수령 없음) · `destination_blocked`(갈 수 없는 곳) · `robot_error`(그 밖).

`GET /robot/me` 예:

```json
{
  "robot": {"id": 1, "name": "배송로봇 1호", "robot_type": "amr"},
  "home_location": {"id": 18, "name": "출발점 A", "robot_dest": "START_A", "map_id": 5, "map_x_m": 1.827, "map_y_m": 0.24, "map_yaw_rad": 3.1416},
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
curl -X POST $E/robot/deliveries/claim        # 배송 #32(약제실 OMX)를 맡음 → robot_dest PHARMACY
# (로봇을 PHARMACY로 보냄 — 예: curl -X POST -H 'Content-Type: application/json' -d '{"dest":"PHARMACY","dock":true}' http://192.168.129.122:8080/goto)
curl -X POST $E/robot/arrived                 # 도착 → EMR 간호사 화면에 "받았습니다" 버튼
curl $E/robot/me                              # 간호사가 누르면 active_delivery가 null
```

## 4. 알아 둘 것

- 로봇 한 대는 배송을 하나씩만 맡는다. 맡은 배송이 끝나야(수령·실패) 다음 `claim`이 새 배송을 준다.
- 맡을 수 있는 배송은 목적지가 "Pinky 아레나" 맵의 장소인 것만이다(EMR 장소 id 8–18: 4인실·1인실·약제실 OMX·수술실·대기 포켓·충전·출발점 A).
- 도착 후 5분(`receipt_wait_seconds`) 안에 "받았습니다"가 없으면 FMS가 `not_received`로 실패를 보고하고 복귀하는 것을 권한다(EMR이 스스로 실패시키지는 않는다).
- 시험 중 예약: EMR 화면에서 하거나 `POST /deliveries {"destination_location_id": 9, "scheduled_at": "<지금 UTC>", "items": [{"supply_id": 1, "quantity": 1}]}`.
- 관제 PC 배송 실행기(`robot/src/fms/delivery_executor`)와 FMS를 동시에 돌리지 않는다 — 같은 로봇의 배송을 둘이 처리하게 된다.
- 운영 전에는 로봇 키·로그인을 다시 켠다(그때 FMS는 `X-Robot-Api-Key` 헤더를 붙인다).
