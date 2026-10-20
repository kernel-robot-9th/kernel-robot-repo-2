"""Vision (code) -> candidates with color+shape, LLM picks one by meaning (schema-limited), print pixel coordinates."""
import json, math, sys, time, urllib.request
import cv2, numpy as np
command, out = sys.argv[1], sys.argv[2]
if len(sys.argv) > 3:   # optional input image instead of the live camera
    frame = cv2.imread(sys.argv[3])
else:
    cap = cv2.VideoCapture(4, cv2.CAP_V4L2); cap.set(3, 1920); cap.set(4, 1080)
    for _ in range(20): ok, frame = cap.read()
    cap.release()
print(f'{time.strftime("%T")} [vision] frame {frame.shape[1]}x{frame.shape[0]}')
hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
RANGES = {'orange': [(5, 80, 120), (18, 255, 255)], 'green': [(45, 45, 60), (85, 255, 190)],
          'blue': [(95, 90, 80), (125, 255, 255)]}
KO = {'orange': '주황', 'green': '초록', 'blue': '파랑', 'round': '원형', 'square': '사각'}
H, W = frame.shape[:2]
roi = (0, int(H * 0.42), int(W * 0.97), int(H * 0.78))   # work area: floor trays, not walls / arms / image edge
candidates, counts = [], {}
for color, (lo, hi) in RANGES.items():
    mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        area = cv2.contourArea(contour)
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        if not (2500 < area < 40000 and roi[0] < cx < roi[2] and roi[1] < cy < roi[3]):
            continue
        hull = cv2.convexHull(contour)
        circularity = 4 * math.pi * cv2.contourArea(hull) / cv2.arcLength(hull, True) ** 2
        rect = cv2.minAreaRect(hull); (rw, rh) = rect[1]
        fill = cv2.contourArea(hull) / (math.pi * radius ** 2)   # of the enclosing circle: circle ~0.9, square ~0.64
        shape = 'square' if max(rw, rh) >= 115 else 'round'   # size separates them here (outline does not); provisional px threshold
        key = f'{color}_{shape}'; n = counts.get(key, 0); counts[key] = n + 1
        candidates.append({'id': f'{key}_{n}', 'color': color, 'shape': shape, 'u': int(cx), 'v': int(cy),
                           'size_px': int(max(rw, rh)), 'fill': round(fill, 2), 'circularity': round(circularity, 2),
                           'contour': hull})
print(f'[vision] {len(candidates)} candidates (gray lids not detected yet)')
for c in candidates:
    print(f"   {c['id']:16s} {KO[c['color']]} {KO[c['shape']]}  pixel ({c['u']},{c['v']})  size {c['size_px']}px  fill {c['fill']}")

ids = [c['id'] for c in candidates]
schema = {'type': 'object', 'required': ['intent', 'object', 'attributes', 'target_id', 'reason'],
          'properties': {'intent': {'type': 'string', 'enum': ['pick', 'locate', 'none']},
                         'object': {'type': 'string'},
                         'attributes': {'type': 'object', 'properties': {'color': {'type': 'string'}, 'shape': {'type': 'string'}}},
                         'target_id': {'type': 'string', 'enum': ids + ['none']},
                         'reason': {'type': 'string'}}}
listing = '\n'.join(f"- {c['id']}: {KO[c['color']]}({c['color']}) {KO[c['shape']]}({c['shape']}) 용기" for c in candidates)
system = ('너는 로봇 작업대의 물체 선택기다. 사용자 문장의 의미(의도, 대상, 색, 모양)를 해석하고, '
          '아래 후보 목록에서 정확히 맞는 것 하나의 id만 고른다. 맞는 것이 없으면 target_id는 none. 좌표는 만들지 않는다.')
body = {'model': 'gemma4:e2b', 'stream': False, 'think': False, 'format': schema, 'options': {'temperature': 0},
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': f'후보:\n{listing}\n\n문장: {command}'}]}
t = time.time()
req = urllib.request.Request('http://localhost:11434/api/chat', json.dumps(body).encode(), {'Content-Type': 'application/json'})
answer = json.loads(json.loads(urllib.request.urlopen(req, timeout=120).read())['message']['content'])
print(f'\n{time.strftime("%T")} [language] "{command}"  (LLM {time.time()-t:.1f} s)')
print(json.dumps(answer, ensure_ascii=False, indent=2))

target = next((c for c in candidates if c['id'] == answer['target_id']), None)
vis = frame.copy()
cv2.rectangle(vis, roi[:2], roi[2:], (0, 255, 255), 1)
for c in candidates:
    chosen = c is target
    cv2.drawContours(vis, [c['contour']], -1, (0, 0, 255) if chosen else (200, 200, 200), 4 if chosen else 2)
    cv2.putText(vis, c['id'], (c['u'] - 60, c['v'] - c['size_px'] // 2 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 0, 255) if chosen else (230, 230, 230), 2)
if target:
    cv2.drawMarker(vis, (target['u'], target['v']), (0, 0, 255), cv2.MARKER_CROSS, 40, 3)
    cv2.putText(vis, f"({target['u']},{target['v']}) px", (target['u'] + 25, target['v'] + 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    print(f"\n[coordinates] {target['id']}: pixel (u={target['u']}, v={target['v']}), size {target['size_px']} px  "
          f"-> metric (x, y) needs floor markers with unique ids")
else:
    print('\n[coordinates] no target')
cv2.imwrite(out, vis)
