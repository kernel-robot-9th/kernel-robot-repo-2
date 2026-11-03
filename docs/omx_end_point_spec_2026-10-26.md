# OMX → EMR 완료 신호 API 명세 (2026-10-26)

OMX(로봇팔)가 작업을 마치면 EMR에 "끝났다"를 알리는 주소다. OMX 쪽에서 GET 한 번만 부르면 된다.

- 공유 페이지(같은 내용): https://claude.ai/artifact/7d65tAgrobQZwvsaVZwV6w

## 1. 한눈에

| 항목 | 값 |
|---|---|
| 주소 | `GET http://192.168.129.135:8000/api/v1/robot/{request_id}/end-point` |
| 방식 | **GET**, 본문 없음 |
| 인증 | **없음**(헤더 필요 없음) |
| 보내는 때 | OMX 작업이 **성공으로 끝났을 때 한 번**. 지금은 성공 신호만 받는다 |
| 성공 응답 | `200` + JSON |
| 시험 화면 | `http://192.168.129.135:8000/docs` → robot-access → "OMX 완료 신호" |

## 2. 경로 값 `request_id`

- OMX `POST /command`·`POST /pinky`에 넣은 `request_id`를 **그대로** 넣는다(예: `yolo-8b5efa75`).
- 쓸 수 있는 글자: 영문 대소문자, 숫자, `.` `_` `-`
- 길이: 1~64자
- 이 규칙을 벗어나면(공백·한글·`;` 등) `422`가 돌아온다.

## 3. 응답

`200 OK`

```json
{"request_id": "yolo-8b5efa75", "received": true, "received_at": "2026-10-26T06:29:16.701579Z"}
```

| 칸 | 뜻 |
|---|---|
| `request_id` | 보낸 값 그대로 |
| `received` | 항상 `true` |
| `received_at` | EMR이 받은 시각(UTC, ISO 8601) |

- 응답 헤더 `Cache-Control: no-store`가 붙는다. 중간에서 캐시되지 않게 하려는 것이다.
- **같은 `request_id`를 여러 번 보내도 매번 `200`이다.** 응답을 못 받았으면 다시 보내도 된다.

| 코드 | 언제 |
|---|---|
| `200` | 받음 |
| `422` | `request_id` 형식이 틀림 |
| `405` | GET이 아닌 방식(POST 등) |
| 연결 실패·시간 초과 | EMR이 꺼져 있거나 네트워크 문제. 잠시 뒤 다시 보낸다 |

## 4. 부르는 예

curl:

```bash
curl -i http://192.168.129.135:8000/api/v1/robot/yolo-8b5efa75/end-point
```

Python(OMX 쪽, `requests`). 실패하면 1초 간격으로 3번까지 다시 보내는 예다.

```python
import time
import requests

EMR_API = "http://192.168.129.135:8000/api/v1"

def notify_emr_end_point(request_id: str) -> bool:
    """OMX 작업이 성공으로 끝났을 때 EMR에 알린다. 받았으면 True."""
    for _ in range(3):
        try:
            response = requests.get(f"{EMR_API}/robot/{request_id}/end-point", timeout=2)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False
```

## 5. EMR이 하는 일 (지금)

- 받은 신호를 EMR 서버 로그에 남긴다(`omx_end_point`: request_id, 보낸 주소, 받은 시각).
- **배송 상태·화면·DB는 아직 바꾸지 않는다.** 적재 흐름(FMS에 적재 완료 `/loaded` 전달 등)과는 FMS 연동을 할 때 잇는다.
- 실패 신호와 진행 단계는 아직 받지 않는다. 필요하면 이 주소 형식에 맞춰 따로 정한다.

## 6. 확인 방법

1. 위 curl을 OMX가 있는 PC에서 실행한다. `200`과 JSON이 오면 네트워크와 주소가 맞다.
2. EMR 쪽에서는 서버 로그에서 확인한다: `docker compose logs api | grep omx_end_point`
3. 2026-10-26 EMR 서버에서 직접 불러 `200`·`422`를 확인했다. EMR 자동 테스트 7개(`emr/backend/tests/test_api/test_omx_end_point.py`)도 통과했다.

## 7. 주의

- 인증이 없다. 같은 네트워크의 누구나 부를 수 있다. 지금은 로그만 남기므로 영향은 없지만, 이 신호로 배송 상태를 바꾸게 되면 인증을 넣는다.
- EMR 주소(`192.168.129.135`)가 바뀌면 알려 준다.

## 8. OMX 명령 형식 — `POST /command` 바뀜 (2026-10-26 합의)

OMX `POST /command`의 `command`를 문장(예: `"pick and place green gauze"`)에서 **색깔별 개수**로 바꾸기로 했다.

```json
{
  "command": {"blue": 2, "green": 1},
  "request_id": "yolo-8b5efa75"
}
```

| 칸 | 형식 | 뜻 |
|---|---|---|
| `command.blue` | 정수 | 집을 파란색(blue gauze) 개수 |
| `command.green` | 정수 | 집을 초록색(green gauze) 개수 |
| `request_id` | 문자열 | 이 작업의 번호. **끝나면 같은 값으로 완료 신호(1장 주소)를 부른다** |

흐름: `POST /command {command: {blue, green}, request_id}` → OMX가 집어 싣기 → 성공하면 `GET {EMR}/api/v1/robot/{request_id}/end-point`.

아직 정할 것:
- 개수가 0인 색은 칸을 빼는가, `0`으로 보내는가?
- 한 번에 몇 개까지인가? 로봇 적재 한도는 3개다(팀원 FMS 설계).
- EMR 비품(A 약품·주사제 등)과 blue·green의 대응
- 바뀐 OMX API는 2026-10-26 확인 시점에 꺼져 있어(8000 포트 응답 없음) 실제 명세(`/openapi.json`)로는 아직 확인하지 못했다.

**EMR이 지금 보내는 형식(2026-10-26)**: 위 새 형식으로 바뀌기 전까지 EMR은 **예전 형식**으로 보낸다 — `{"command": "pick and place green gauze", "request_id": "emr-20261026T063012-1a2b3c"}`. `request_id`는 EMR이 만들며 `emr-`로 시작한다. 끝나면 이 값 그대로 1장 주소를 불러 주면 된다. OMX가 새 형식으로 바뀌면 알려 달라 — EMR 쪽을 같이 바꾼다.
