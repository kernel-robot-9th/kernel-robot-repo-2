# FMS API v1 (관제 PC ↔ FMS) OpenAPI 명세 — 손으로 씀. sim_server.py 의 /api/v1 을 바꾸면 여기와 API.md 도 같이 고칠 것.
# GET /api/v1/openapi.json 으로 나가고 /docs 의 Swagger UI 가 읽는다. FMS → 관제 PC 로 보내는 것은 webhooks 에 적었다.

ERR = {'type': 'object', 'properties': {
    'error': {'type': 'string', 'example': 'unknown_room'},
    'message': {'type': 'string', 'example': '모르는 병실 "110호". 쓸 수 있는 이름: 101호, …'}}}

ROOM = {'type': 'string', 'description': '방 번호 101호~108호, 수술실 ("101" 처럼 숫자만도 됨). 약제실은 주문 목적지 아님',
        'example': '101호'}

ORDER = {'type': 'object', 'properties': {
    'order_id': {'type': 'string', 'example': 'o-17'},
    'request_id': {'type': 'string', 'example': 'pc-20261027-0001'},
    'room': {'type': 'string', 'example': '101호'},
    'item': {'type': 'string', 'example': '진통제'},
    'status': {'type': 'string', 'enum': ['queued', 'assigned', 'loaded', 'delivered', 'canceled', 'failed']},
    'batch_id': {'type': ['string', 'null'], 'example': 'b-5'},
    'robot': {'type': ['integer', 'null'], 'example': 1},
    'created_at': {'type': 'string', 'example': '2026-10-27T14:03:21+09:00'},
    'delivered_at': {'type': ['string', 'null']},
    'fail_reason': {'type': ['string', 'null']}}}

BATCH = {'type': 'object', 'properties': {
    'batch_id': {'type': 'string', 'example': 'b-5'},
    'status': {'type': 'string', 'enum': ['assigned', 'called', 'at_pharmacy', 'delivering', 'completed', 'failed']},
    'robot': {'type': 'integer', 'example': 1},
    'name': {'type': 'string', 'example': 'pinky_6364'},
    'orders': {'type': 'array', 'items': {'type': 'object', 'properties': {
        'order_id': {'type': 'string'}, 'room': {'type': 'string'}, 'item': {'type': 'string'}, 'status': {'type': 'string'}}}},
    'count': {'type': 'integer', 'example': 2},
    'rooms': {'type': 'array', 'items': {'type': 'string'}, 'description': '방문 순서', 'example': ['104호', '101호']}}}

ROBOT = {'type': 'object', 'properties': {
    'robot': {'type': 'integer', 'example': 1}, 'name': {'type': 'string', 'example': 'pinky_6364'},
    'online': {'type': 'boolean'},
    'state': {'type': 'string', 'enum': ['idle', 'reserved', 'moving', 'waiting', 'docking', 'loading', 'spinning',
                                         'pausing', 'decon', 'charging', 'error']},
    'task': {'type': 'string', 'enum': ['none', 'delivery', 'decon', 'charge', 'park', 'yield']},
    'pose': {'type': 'object', 'description': 'cm, 경기장 그림 왼쪽 아래 원점, 라이다 중심. heading deg 0=+x 90=+y',
             'properties': {'x': {'type': 'number'}, 'y': {'type': 'number'}, 'heading': {'type': 'number'}}},
    'node': {'type': 'string', 'example': 'R58'}, 'next_node': {'type': ['string', 'null']},
    'place': {'type': 'string', 'example': '오른쪽 협로'},
    'destination': {'type': ['object', 'null'], 'properties': {'node': {'type': 'string'}, 'room': {'type': ['string', 'null']}}},
    'path': {'type': 'array', 'items': {'type': 'string'}},
    'battery': {'type': 'integer'}, 'contamination': {'type': 'integer'},
    'load': {'type': 'integer'}, 'capacity': {'type': 'integer', 'example': 3},
    'batch_id': {'type': ['string', 'null']}, 'orders': {'type': 'array', 'items': {'type': 'string'}}}}

EVENT_TYPES = ['order_created', 'batch_assigned', 'robot_called', 'robot_at_pharmacy', 'batch_departed', 'robot_departed',
               'robot_arrived', 'order_delivered', 'batch_completed', 'order_canceled', 'order_failed', 'robot_error']

EVENT = {'type': 'object', 'description': '공통 껍데기 + 종류별 필드 (API.md 이벤트 표)',
         'properties': {'event_id': {'type': 'string', 'example': 'e-1203'}, 'seq': {'type': 'integer', 'example': 1203},
                        'time': {'type': 'string'}, 'type': {'type': 'string', 'enum': EVENT_TYPES}},
         'additionalProperties': True,
         'example': {'event_id': 'e-1203', 'seq': 1203, 'time': '2026-10-27T14:03:22+09:00', 'type': 'batch_assigned',
                     'batch_id': 'b-5', 'robot': 1, 'name': 'pinky_6364',
                     'orders': [{'order_id': 'o-17', 'room': '101호', 'item': '진통제'}], 'count': 1, 'rooms': ['101호']}}


def _err(*codes):
    return {str(c): {'description': d, 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}}
            for c, d in codes}


def _ok(code, desc, ref):
    return {str(code): {'description': desc, 'content': {'application/json': {'schema': {'$ref': ref}}}}}


SPEC = {
    'openapi': '3.1.0',
    'info': {'title': 'Pinky FMS API v1 (관제 PC ↔ FMS)', 'version': '1.0.0',
             'description': '관제 PC 는 배송 요청과 OMX 준비·적재 완료만 보내고, 배차·경로·로봇 실행은 FMS 가 맡는다. '
                            'FMS 는 로봇 상태(1초마다)와 이벤트를 관제 PC 로 POST 한다 (webhooks). 설명: fms/API.md'},
    'paths': {
        '/api/v1/orders': {'post': {
            'summary': '배송 요청 1건 넣기', 'tags': ['관제 PC → FMS'],
            'requestBody': {'required': True, 'content': {'application/json': {'schema': {
                'type': 'object', 'required': ['request_id', 'room', 'item'],
                'properties': {'request_id': {'type': 'string', 'description': '관제 PC 가 만드는 고유 값. 같은 값 = 같은 주문',
                                              'example': 'pc-20261027-0001'},
                               'room': ROOM, 'item': {'type': 'string', 'description': '자유 문자열 (1건 = 1개)', 'example': '진통제'}}}}}},
            'responses': {**_ok(202, '새 주문', '#/components/schemas/Order'),
                          **_ok(200, '같은 request_id 로 이미 받은 주문', '#/components/schemas/Order'),
                          **_err((400, 'missing_field / unknown_room / bad_json'))}}},
        '/api/v1/orders/{order_id}': {
            'parameters': [{'name': 'order_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}, 'example': 'o-17'}],
            'get': {'summary': '주문 조회', 'tags': ['관제 PC → FMS'],
                    'responses': {**_ok(200, '주문', '#/components/schemas/Order'), **_err((404, 'not_found'))}},
            'delete': {'summary': '주문 취소 (status = queued 일 때만)', 'tags': ['관제 PC → FMS'],
                       'responses': {**_ok(200, '취소됨', '#/components/schemas/Order'),
                                     **_err((404, 'not_found'), (409, 'order_locked: 이미 묶음에 들어감'))}}},
        '/api/v1/batches/{batch_id}': {
            'parameters': [{'name': 'batch_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}, 'example': 'b-5'}],
            'get': {'summary': '묶음 조회', 'tags': ['관제 PC → FMS'],
                    'responses': {**_ok(200, '묶음', '#/components/schemas/Batch'), **_err((404, 'not_found'))}}},
        '/api/v1/batches/{batch_id}/ready': {
            'parameters': [{'name': 'batch_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}, 'example': 'b-5'}],
            'post': {'summary': 'OMX 물품 준비 끝 → FMS 가 핑키를 약제실로 부름', 'tags': ['관제 PC → FMS'],
                     'responses': {'200': {'description': '핑키 출발', 'content': {'application/json': {'schema': {
                         'type': 'object', 'properties': {'batch_id': {'type': 'string'}, 'status': {'type': 'string', 'example': 'called'},
                                                          'robot': {'type': 'integer'}, 'name': {'type': 'string'},
                                                          'eta_s': {'type': 'integer', 'description': '약제실 정밀 주차 끝까지 예상 초'}}}}}},
                                   **_err((404, 'not_found'), (409, 'bad_batch_state: assigned 가 아님'))}}},
        '/api/v1/batches/{batch_id}/loaded': {
            'parameters': [{'name': 'batch_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}, 'example': 'b-5'}],
            'post': {'summary': 'OMX 가 핑키에 다 실음 → FMS 가 병실로 출발시킴', 'tags': ['관제 PC → FMS'],
                     'responses': {'200': {'description': '출발', 'content': {'application/json': {'schema': {
                         'type': 'object', 'properties': {'batch_id': {'type': 'string'}, 'status': {'type': 'string', 'example': 'delivering'}}}}}},
                                   **_err((404, 'not_found'), (409, 'bad_batch_state: at_pharmacy 가 아님'))}}},
        '/api/v1/state': {'get': {
            'summary': '지금 상태 한 번에 (관제 PC 가 다시 켜졌을 때)', 'tags': ['관제 PC → FMS'],
            'responses': {'200': {'description': '로봇 전부 + 끝나지 않은 주문·묶음 + 마지막 이벤트 seq',
                                  'content': {'application/json': {'schema': {'type': 'object', 'properties': {
                                      'time': {'type': 'string'},
                                      'robots': {'type': 'array', 'items': {'$ref': '#/components/schemas/RobotStatus'}},
                                      'orders': {'type': 'array', 'items': {'$ref': '#/components/schemas/Order'}},
                                      'batches': {'type': 'array', 'items': {'$ref': '#/components/schemas/Batch'}},
                                      'last_seq': {'type': 'integer'}}}}}}}}},
        '/api/v1/rooms': {'get': {'summary': '방 번호 목록', 'tags': ['관제 PC → FMS'],
                                  'responses': {'200': {'description': '{rooms: [{room, name, contamination, orderable}]}'}}}},
        '/api/v1/map': {'get': {'summary': '지도 (벽, 노드 좌표, 엣지) — 화면 그리기용', 'tags': ['관제 PC → FMS'],
                                'responses': {'200': {'description': '{walls, nodes: {이름: {xy, type, name}}, edges, room_codes, …}'}}}},
        '/api/v1/events': {'get': {
            'summary': '최근 이벤트 (시험용: 관제 PC 서버 없이 확인)', 'tags': ['시험용'],
            'parameters': [{'name': 'after', 'in': 'query', 'schema': {'type': 'integer'}, 'description': '이 seq 다음부터'}],
            'responses': {'200': {'description': '{events: [...], last_seq}'}}}},
    },
    'webhooks': {
        'robot-status': {'post': {
            'summary': 'FMS → 관제 PC: 로봇 상태 1초마다 — POST {관제 PC}/api/v1/fms/robot-status (실패해도 다시 안 보냄)',
            'requestBody': {'content': {'application/json': {'schema': {'type': 'object', 'properties': {
                'time': {'type': 'string'}, 'robots': {'type': 'array', 'items': {'$ref': '#/components/schemas/RobotStatus'}}}}}}},
            'responses': {'200': {'description': '2xx 면 됨 (본문 안 봄)'}}}},
        'events': {'post': {
            'summary': 'FMS → 관제 PC: 이벤트 1건 — POST {관제 PC}/api/v1/fms/events (연결 실패·5xx 면 1, 2, 4초 뒤 다시)',
            'requestBody': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Event'}}}},
            'responses': {'200': {'description': '2xx 면 됨. 같은 event_id 는 한 번만 처리'}}}},
    },
    'components': {'schemas': {'Error': ERR, 'Order': ORDER, 'Batch': BATCH, 'RobotStatus': ROBOT, 'Event': EVENT}},
}

SWAGGER_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>Pinky FMS API v1</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css">
</head><body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
<script>
window.ui = SwaggerUIBundle({url: '/api/v1/openapi.json', dom_id: '#swagger-ui'});
</script>
</body></html>
"""
