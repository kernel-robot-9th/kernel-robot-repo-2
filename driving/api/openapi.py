# pinky_api.py 의 OpenAPI 3 명세 (손으로 씀 — 엔드포인트를 바꾸면 여기도 같이 고칠 것)
# /openapi.json 으로 나가고, /docs 의 Swagger UI 가 읽는다.

POSE = {'type': 'object', 'nullable': True, 'description': '라이다 중심, 그림 cm. TF map→base_footprint 없으면 null',
        'properties': {'x': {'type': 'number', 'example': 182.7}, 'y': {'type': 'number', 'example': 24.0},
                       'heading': {'type': 'number', 'description': 'deg, 0 = +x, 90 = +y', 'example': 180.0},
                       'age_s': {'type': 'number', 'description': 'TF 나이 s'}}}

SEGMENT = {'type': 'object', 'properties': {
    'mode': {'type': 'string', 'enum': ['nav', 'wall', 'rotate', 'dock'],
             'description': 'nav = Nav2 FollowPath, wall = 협로 벽 따라가기, rotate = 제자리 회전, dock = 카메라 정밀 주차'},
    'points': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'number'}}, 'example': [[180, 15], [130, 15]]},
    'final_heading': {'type': 'number'},
    'side': {'type': 'string', 'enum': ['left', 'right'], 'description': 'wall: 따라갈 벽 쪽'},
    'offset': {'type': 'number', 'description': 'wall: 축선에서 벽까지 cm'},
    'zones': {'type': 'array', 'items': {'type': 'string'}}}}

PLAN = {'type': 'object', 'properties': {
    'goal': {'type': 'object', 'properties': {'xy': {'type': 'array', 'items': {'type': 'number'}},
                                              'heading': {'type': 'number', 'nullable': True},
                                              'node': {'type': 'string', 'nullable': True}}},
    'nodes': {'type': 'array', 'items': {'type': 'string'}, 'example': ['B_180', 'B_130', 'GB130']},
    'points': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'number'}}},
    'length_cm': {'type': 'number'},
    'segments': {'type': 'array', 'items': {'$ref': '#/components/schemas/Segment'}}}}

JOB = {'type': 'object', 'properties': {
    'id': {'type': 'string', 'example': '5396f6e7'},
    'state': {'type': 'string', 'enum': ['running', 'succeeded', 'failed', 'canceled']},
    'request': {'type': 'object'},
    'segment': {'type': 'integer', 'description': '지금(또는 마지막) 구간 번호, 1부터'},
    'segments_total': {'type': 'integer'},
    'progress': {'type': 'object', 'nullable': True, 'description': 'nav: {remaining_cm, speed}, dock: {dock: 마지막 출력 줄}'},
    'error': {'type': 'string', 'nullable': True},
    't_start': {'type': 'string'},
    'time_s': {'type': 'number', 'nullable': True},
    'end_pose': {'$ref': '#/components/schemas/Pose'},
    'end_error_cm': {'type': 'number', 'nullable': True, 'description': '성공 시 목표 x,y 와 끝 위치 거리 (dock 작업은 null → dock_error)'},
    'notify': {'type': 'object', 'nullable': True, 'description': '도착 신호를 보냈으면 {url, status, error}'},
    'dock_error': {'type': 'object', 'nullable': True, 'description': 'dock 작업 성공 시 마커 기준 자세와의 최종 어긋남',
                   'properties': {'fwd_mm': {'type': 'number'}, 'left_mm': {'type': 'number'}, 'heading_deg': {'type': 'number'}}}}}

JOB_DETAIL = {'allOf': [{'$ref': '#/components/schemas/Job'}, {'type': 'object', 'properties': {
    'plan': {'$ref': '#/components/schemas/Plan'},
    'start_pose': {'$ref': '#/components/schemas/Pose'},
    'results': {'type': 'array', 'description': '구간별 결과', 'items': {'type': 'object', 'properties': {
        'segment': {'type': 'integer'}, 'mode': {'type': 'string'},
        'status': {'type': 'string', 'enum': ['ok', 'fail', 'canceled', 'blocked', 'contact', 'timeout', 'lost']},
        'time_s': {'type': 'number'}, 'why': {'type': 'string'}, 'pose': {'$ref': '#/components/schemas/Pose'}}}}}}]}

ERROR = {'type': 'object', 'properties': {'error': {'type': 'string'}}}


def _json(ref=None, schema=None, example=None):
    s = {'$ref': f'#/components/schemas/{ref}'} if ref else schema
    c = {'schema': s}
    if example is not None:
        c['example'] = example
    return {'content': {'application/json': c}}


def _err(desc):
    return dict(description=desc, **_json('Error'))


def spec(server_url=None):
    return {
        'openapi': '3.0.3',
        'info': {'title': 'Pinky API', 'version': '0.1.0', 'description': (
            '핑키 로봇 1대의 REST API (로봇에서 실행, 포트 8080).\n\n'
            '- 좌표: 그림 cm (아레나 왼쪽 아래 원점, x 오른쪽, y 위), 위치 = **라이다 중심**, heading deg (0 = +x, 90 = +y, 반시계 +)\n'
            '- 주행은 주행 그래프(graph/graph.yaml)를 따름. 교행 복도는 복도 가운데(y=15 / 145)를 Nav2 로, 협로는 벽 따라가기\n'
            '- 한 번에 작업 하나. ⚠️ `POST /goto` 는 로봇이 실제로 움직임')},
        'servers': [{'url': server_url or '/'}],
        'tags': [{'name': '상태'}, {'name': '주행'}, {'name': '위치'}, {'name': '도착 신호'}],
        'paths': {
            '/status': {'get': {'tags': ['상태'], 'summary': '위치·상태·지금 작업', 'responses': {'200': dict(description='OK', **_json(schema={
                'type': 'object', 'properties': {
                    'robot': {'type': 'object', 'properties': {'serial': {'type': 'string'}, 'hostname': {'type': 'string'},
                                                               'ips': {'type': 'array', 'items': {'type': 'string'}}}},
                    'frame': {'type': 'string'}, 'pose': {'$ref': '#/components/schemas/Pose'},
                    'localized': {'type': 'boolean'}, 'nav2_ready': {'type': 'boolean', 'description': 'follow_path 액션 서버 있음'},
                    'state': {'type': 'string', 'enum': ['idle', 'running']},
                    'job': {'allOf': [{'$ref': '#/components/schemas/Job'}], 'nullable': True}}}))}}},
            '/dests': {'get': {'tags': ['상태'], 'summary': '목적지 이름 목록 (그래프의 목적지 노드)', 'responses': {'200': dict(
                description='이름 → 정보', **_json(schema={'type': 'object', 'additionalProperties': {'type': 'object', 'properties': {
                    'xy': {'type': 'array', 'items': {'type': 'number'}}, 'heading': {'type': 'number'},
                    'name': {'type': 'string'}, 'dock': {'type': 'string', 'nullable': True}}}},
                    example={'PHARMACY': {'xy': [98.9, 178.8], 'heading': 90, 'name': '약제실 OMX', 'dock': 'aruco'}}))}}},
            '/plan': {'get': {'tags': ['주행'], 'summary': '경로만 계산 (움직이지 않음)',
                              'description': '`dest` 또는 `x`,`y` 중 하나. 기본 출발점은 지금 위치',
                              'parameters': [
                                  {'name': 'dest', 'in': 'query', 'schema': {'type': 'string'}, 'example': 'PHARMACY'},
                                  {'name': 'x', 'in': 'query', 'schema': {'type': 'number'}},
                                  {'name': 'y', 'in': 'query', 'schema': {'type': 'number'}},
                                  {'name': 'heading', 'in': 'query', 'schema': {'type': 'number'}, 'description': '도착 방향 (없으면 진행 방향)'},
                                  {'name': 'dock', 'in': 'query', 'schema': {'type': 'boolean'}},
                                  {'name': 'from', 'in': 'query', 'schema': {'type': 'string'}, 'description': '출발점 "x,y,heading" (지금 위치 대신)'}],
                              'responses': {'200': dict(description='경로', **_json('Plan')),
                                            '400': _err('목적지 없음 / 그래프로 못 감'), '503': _err('지금 위치 모름')}}},
            '/goto': {'post': {'tags': ['주행'], 'summary': '목적지로 주행 시작 ⚠️ 로봇이 움직임',
                               'requestBody': {'required': True, **_json('GotoRequest', example={'x': 60, 'y': 145, 'heading': 180})},
                               'responses': {'202': dict(description='시작함', **_json(schema={'type': 'object', 'properties': {
                                   'job': {'$ref': '#/components/schemas/Job'}, 'plan': {'$ref': '#/components/schemas/Plan'}}})),
                                   '400': _err('목적지 없음 / 그래프로 못 감 / dock 못 하는 목적지'),
                                   '409': _err('다른 작업이 도는 중 — 먼저 /cancel'), '503': _err('지금 위치 모름')}}},
            '/cancel': {'post': {'tags': ['주행'], 'summary': '지금 작업 멈춤 (작업 없으면 정지 명령만)', 'responses': {'200': dict(
                description='OK', **_json(schema={'type': 'object', 'properties': {
                    'canceled': {'type': 'string', 'nullable': True}, 'state': {'type': 'string'}}}))}}},
            '/jobs': {'get': {'tags': ['주행'], 'summary': '최근 작업 목록 (최신 먼저, 최대 50)', 'responses': {'200': dict(
                description='OK', **_json(schema={'type': 'array', 'items': {'$ref': '#/components/schemas/Job'}}))}}},
            '/jobs/{id}': {'get': {'tags': ['주행'], 'summary': '작업 상세 (구간별 결과)',
                                   'parameters': [{'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}],
                                   'responses': {'200': dict(description='OK', **_json('JobDetail')), '404': _err('없음')}}},
            '/notify': {
                'get': {'tags': ['도착 신호'], 'summary': '도착 신호 설정 보기',
                        'responses': {'200': dict(description='OK', **_json('NotifyConfig'))}},
                'put': {'tags': ['도착 신호'], 'summary': '도착 신호 받을 주소 등록 (로봇에 저장)',
                        'description': '등록한 목적지(dests)로 가는 /goto 작업이 성공하면 — dock 을 요청했으면 정밀 주차까지 끝난 뒤 — '
                                       '로봇이 url 로 `POST` (본문 = ArrivedSignal) 를 한 번 보낸다. 실패하면 1초 간격으로 3번까지. '
                                       '연결 실패·5xx 만 다시 보내고 4xx 는 그대로 둔다. 결과는 그 작업의 `notify` {url, status, error, response} 에 남는다. url 을 null 로 주면 끔.',
                        'requestBody': {'required': True, **_json('NotifyConfig', example={'url': 'http://192.168.129.135:8000/pinky/arrived', 'dests': ['PHARMACY']})},
                        'responses': {'200': dict(description='저장됨', **_json('NotifyConfig')), '400': _err('url 이나 목적지 이름이 잘못됨')}}},
            '/set_pose': {'post': {'tags': ['위치'], 'summary': 'AMCL 시작 위치 넣기 + 스캔 확인 (tools/set_pose.py, 움직이지 않음)',
                                   'description': 'Nav2 띄운 직후 꼭. `find` 는 스캔만으로 맵 전체에서 찾음 (~1분)',
                                   'requestBody': {'required': True, **_json('SetPoseRequest', example={'name': 'A'})},
                                   'responses': {'200': dict(description='위치 맞음', **_json('SetPoseResult')),
                                                 '422': dict(description='넣었지만 스캔과 안 맞음 (또는 실패)', **_json('SetPoseResult')),
                                                 '400': _err('인자 잘못'), '409': _err('주행 중'), '504': _err('시간 초과')}}},
        },
        'components': {'schemas': {
            'Pose': POSE, 'Segment': SEGMENT, 'Plan': PLAN, 'Job': JOB, 'JobDetail': JOB_DETAIL, 'Error': ERROR,
            'GotoRequest': {'type': 'object', 'description': '`dest` 또는 `x`+`y`', 'properties': {
                'x': {'type': 'number', 'description': '그림 cm'}, 'y': {'type': 'number', 'description': '그림 cm'},
                'heading': {'type': 'number', 'nullable': True, 'description': '도착 방향 deg (없으면 진행 방향)'},
                'dest': {'type': 'string', 'description': '목적지 이름 (GET /dests). 그래프 노드 이름도 됨', 'example': 'PHARMACY'},
                'dock': {'type': 'boolean', 'description': '도착 후 카메라 정밀 주차. 안 주면 정밀 주차가 되는 목적지(지금 PHARMACY)는 true, 나머지는 false. '
                                                         'PHARMACY 도착 신호(/notify)는 정밀 주차가 성공해야 보낸다'}}},
            'NotifyConfig': {'type': 'object', 'properties': {
                'url': {'type': 'string', 'nullable': True, 'description': '도착 신호를 받을 주소 (POST). null = 끔'},
                'dests': {'type': 'array', 'items': {'type': 'string'}, 'description': '신호를 보낼 목적지 이름 (기본 PHARMACY)'},
                'headers': {'type': 'object', 'additionalProperties': {'type': 'string'},
                            'description': '같이 보낼 HTTP 헤더 (예: {"X-Robot-Api-Key": "..."}). GET 에서는 값이 가려짐'}}},
            'ArrivedSignal': {'type': 'object', 'description': '로봇이 등록된 url 로 보내는 본문 (도착 신호)', 'properties': {
                'event': {'type': 'string', 'example': 'arrived'},
                'dest': {'type': 'string', 'example': 'PHARMACY'},
                'robot': {'type': 'object', 'properties': {'serial': {'type': 'string'}, 'ips': {'type': 'array', 'items': {'type': 'string'}}}},
                'job_id': {'type': 'string'}, 'time': {'type': 'string', 'example': '2026-10-22T22:00:00+0900'},
                'pose': {'$ref': '#/components/schemas/Pose'},
                'dock_error': {'type': 'object', 'nullable': True, 'description': '정밀 주차를 했으면 {fwd_mm, left_mm, heading_deg}'}}},
            'SetPoseRequest': {'type': 'object', 'description': '셋 중 하나', 'properties': {
                'name': {'type': 'string', 'description': 'tools/points.yaml 이름: A, B, C, D, F, G, start_A, omx_stop, omx_approach'},
                'x': {'type': 'number'}, 'y': {'type': 'number'}, 'heading': {'type': 'number'},
                'find': {'type': 'boolean', 'description': '스캔만으로 찾기'}}},
            'SetPoseResult': {'type': 'object', 'properties': {
                'ok': {'type': 'boolean'}, 'output': {'type': 'array', 'items': {'type': 'string'}},
                'pose': {'$ref': '#/components/schemas/Pose'}}},
        }},
    }


SWAGGER_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>Pinky API</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css">
</head><body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
<script>
window.ui = SwaggerUIBundle({url: 'openapi.json', dom_id: '#swagger-ui'});
</script>
<noscript>Swagger UI 를 못 불러옴 (인터넷 필요). 명세는 /openapi.json</noscript>
</body></html>
"""
