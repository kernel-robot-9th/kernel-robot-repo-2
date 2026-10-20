"""Korean command -> which eraser (LLM picks an id from the detected list) -> floor cm + PROVISIONAL arm x, y.
No arm motion. The LLM only chooses; its color must match the chosen eraser or the code rejects the choice.
  python3 eraser_command.py "<명령>" out.jpg [input.jpg]
"""
import json
import math
import sys
import time
import urllib.request

import cv2

from erasers_xy import COLORS, capture, find_erasers, floor_homography

KO = {'red': '빨강', 'orange': '주황', 'yellow': '노랑', 'green': '초록(연두)', 'light blue': '하늘색',
      'blue': '파랑', 'purple': '보라', 'pink': '분홍'}

command, out = sys.argv[1], sys.argv[2]
frame = cv2.imread(sys.argv[3]) if len(sys.argv) > 3 else capture()
H, _ = floor_homography(frame)
erasers = find_erasers(frame, H)
print(f'{time.strftime("%T")} [vision] {len(erasers)} erasers')
for e in erasers:
    reach = math.hypot(*e['arm_m'])
    e['reach_cm'] = reach * 100
    print(f"   {e['id']:14s} {KO[e['color']]:7s} floor ({e['floor_cm'][0]:+.1f},{e['floor_cm'][1]:+.1f}) cm  "
          f"arm ({e['arm_m'][0]:+.3f},{e['arm_m'][1]:+.3f}) m  {reach * 100:.0f} cm from the arm")

ids = [e['id'] for e in erasers]
schema = {'type': 'object', 'required': ['intent', 'color', 'target_id', 'reason'],
          'properties': {'intent': {'type': 'string', 'enum': ['pick', 'locate', 'none']},
                         'color': {'type': 'string', 'enum': COLORS + ['any']},
                         'target_id': {'type': 'string', 'enum': ids + ['none']},
                         'reason': {'type': 'string'}}}
listing = '\n'.join(f"- {e['id']}: {KO[e['color']]}({e['color']}) 지우개, 팔에서 {e['reach_cm']:.0f} cm" for e in erasers)
system = ('너는 로봇 작업대의 물체 선택기다. 사용자 문장의 의도와 대상 색을 해석하고, 아래 후보 목록에서 '
          '정확히 맞는 것 하나의 id만 고른다. 문장의 색과 같은 색 후보가 없으면 target_id는 none. 좌표는 만들지 않는다.')
body = {'model': 'gemma4:e2b', 'stream': False, 'think': False, 'format': schema, 'options': {'temperature': 0},
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': f'후보:\n{listing}\n\n문장: {command}'}]}
t = time.time()
req = urllib.request.Request('http://localhost:11434/api/chat', json.dumps(body).encode(), {'Content-Type': 'application/json'})
answer = json.loads(json.loads(urllib.request.urlopen(req, timeout=120).read())['message']['content'])
print(f'{time.strftime("%T")} [language] "{command}" (LLM {time.time() - t:.1f} s) -> {json.dumps(answer, ensure_ascii=False)}')

target = next((e for e in erasers if e['id'] == answer['target_id']), None)
if target and answer['color'] not in ('any', target['color']):
    print(f"[check] rejected: command color {answer['color']} != {target['id']} color {target['color']}")
    target = None
vis = frame.copy()
for e in erasers:
    chosen = e is target
    cv2.drawContours(vis, [e['contour']], -1, (0, 0, 255) if chosen else (200, 200, 200), 4 if chosen else 2)
if target:
    (fx, fy), (ax, ay) = target['floor_cm'], target['arm_m']
    cv2.putText(vis, f"{target['id']} arm ({ax:+.3f},{ay:+.3f})", (int(target['u']) - 120, int(target['v']) - 45),
                0, 0.8, (0, 0, 255), 2)
    print(f"[result] {target['id']}: floor ({fx:+.1f},{fy:+.1f}) cm, yaw {target['yaw_deg']:+.0f} deg, "
          f"arm x {ax:+.3f} y {ay:+.3f} m (provisional)")
else:
    print('[result] no target')
cv2.imwrite(out, vis)
