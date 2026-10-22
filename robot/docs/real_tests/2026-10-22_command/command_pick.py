"""Korean command -> LLM picks a detected block and a named place -> right-arm coordinates from the 2026-10-22
calibration (calib/top_intrinsics.yaml + top_homography.yaml) -> `teleop pick` arguments. Moves nothing.

  python3 command_pick.py "<명령>" [input.jpg]

Blocks: coloured blobs on the board (S >= 65 and V >= 170). Pixel -> arm with top_camera.pixel_to_arm (undistort + H).
Height: the board plane touched during calibration, z = a + b x + c y (tool on the board, arm sag included);
grasp at half the block height (block height = its top-view short side, cubes).
"""
import json
import math
import os
import sys
import time
import urllib.request

import cv2
import numpy as np
import yaml

sys.path.insert(0, os.path.expanduser('~/dev_ws/robot/src/vla_planner_robot/vla_calibration'))
sys.path.insert(0, os.path.expanduser('~/dev_ws/robot/src/vla_planner_robot/vla_executor'))
from vla_calibration.top_camera import load_calibration, pixel_to_arm  # noqa: E402
from vla_executor.omx_ik import top_down_ik  # noqa: E402

CAMERA = '/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0'
HUES = [(0, 8, 'red'), (8, 22, 'orange'), (22, 35, 'yellow'), (35, 85, 'green'), (85, 130, 'blue'), (130, 150, 'purple'),
        (150, 181, 'pink')]
KO = {'red': '빨강', 'orange': '주황', 'yellow': '노랑', 'green': '초록(연두)', 'blue': '파랑', 'light blue': '하늘색',
      'purple': '보라', 'pink': '분홍'}
PLACES = {'left': ('왼쪽', 0.20, 0.07), 'centre': ('가운데', 0.21, -0.02), 'right': ('오른쪽', 0.19, -0.11)}
SAFE_Z = -0.04


def capture():
    cap = cv2.VideoCapture(CAMERA, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG')); cap.set(3, 1920); cap.set(4, 1080)
    for _ in range(30):
        ok, frame = cap.read()
    cap.release()
    return frame


def board_z(calib, x, y):
    p = calib['plane_z']
    return p['a'] + p['b'] * x + p['c'] * y


def find_blocks(frame, calib):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 65, 170), (180, 255, 255))   # white board S<50, black squares V<100, carpet V<145
    mask[:400] = 0                                              # walls and beyond: not the work surface
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    blocks, counts = [], {}
    for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        if not 800 < cv2.contourArea(contour) < 30000:
            continue
        blob = np.zeros_like(mask); cv2.drawContours(blob, [contour], -1, 255, -1)
        hue, sat = float(np.median(hsv[..., 0][blob > 0])), float(np.median(hsv[..., 1][blob > 0]))
        color = next(n for lo, hi, n in HUES if lo <= hue < hi)
        if color == 'blue' and sat < 170:
            color = 'light blue'
        rect = cv2.minAreaRect(contour)
        corners = [pixel_to_arm(u, v, calib) for u, v in cv2.boxPoints(rect)]
        sides = [math.dist(corners[k], corners[(k + 1) % 4]) for k in range(4)]
        k = int(np.argmax(sides[:2]))
        yaw_long = math.degrees(math.atan2(corners[k + 1][1] - corners[k][1], corners[k + 1][0] - corners[k][0]))
        x, y = pixel_to_arm(*rect[0], calib)
        size = (max(sides[:2]), min(sides[:2]))
        z = board_z(calib, x, y) + size[1] / 2                 # grasp at half height (cube: height = short side)
        n = counts.get(color, 0); counts[color] = n + 1
        blocks.append({'id': f"{color.replace(' ', '_')}_{n}", 'color': color, 'u': rect[0][0], 'v': rect[0][1],
                       'x': x, 'y': y, 'z': z, 'size_m': size, 'closing_yaw': (yaw_long + 90 + 90) % 180 - 90,
                       'reach': math.hypot(x, y), 'reachable': top_down_ik(x, y, z) is not None and
                       top_down_ik(x, y, z + 0.05) is not None, 'contour': contour})
    return blocks


def ask_llm(command, blocks):
    ids = [b['id'] for b in blocks]
    schema = {'type': 'object', 'required': ['intent', 'color', 'target_id', 'place', 'reason'],
              'properties': {'intent': {'type': 'string', 'enum': ['pick', 'locate', 'none']},
                             'color': {'type': 'string', 'enum': sorted(KO) + ['any']},
                             'target_id': {'type': 'string', 'enum': ids + ['none']},
                             'place': {'type': 'string', 'enum': list(PLACES) + [f'on_{i}' for i in ids] + ['none']},
                             'reason': {'type': 'string'}}}
    listing = '\n'.join(f"- {b['id']}: {KO[b['color']]}({b['color']}) 블록, 팔에서 {b['reach'] * 100:.0f} cm"
                        + ('' if b['reachable'] else ' (팔이 닿지 않음)') for b in blocks)
    places = ', '.join(f'{k}={v[0]}' for k, v in PLACES.items()) + ', ' + ', '.join(f'on_{i}={i} 위에 쌓기' for i in ids)
    system = ('너는 로봇 작업대의 물체 선택기다. 사용자 문장의 의도, 대상 색, 놓을 곳을 해석해 후보 목록에서 정확히 맞는 '
              'id 하나와 놓을 곳 하나를 고른다. 같은 색 후보가 없으면 target_id는 none. 놓을 곳을 말하지 않으면 place는 none. '
              '좌표는 만들지 않는다.')
    body = {'model': 'gemma4:e2b', 'stream': False, 'think': False, 'format': schema, 'options': {'temperature': 0},
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': f'후보:\n{listing}\n놓을 곳: {places}\n\n문장: {command}'}]}
    t = time.time()
    req = urllib.request.Request('http://localhost:11434/api/chat', json.dumps(body).encode(), {'Content-Type': 'application/json'})
    answer = json.loads(json.loads(urllib.request.urlopen(req, timeout=120).read())['message']['content'])
    return answer, time.time() - t


def main():
    command = sys.argv[1]
    frame = cv2.imread(sys.argv[2]) if len(sys.argv) > 2 else capture()
    calib = load_calibration()
    blocks = find_blocks(frame, calib)
    print(f'{time.strftime("%T")} [vision] {len(blocks)} blocks')
    for b in blocks:
        print(f"   {b['id']:13s} {KO[b['color']]:6s} pixel ({b['u']:.0f},{b['v']:.0f}) arm ({b['x']:+.3f}, {b['y']:+.3f}, "
              f"{b['z']:+.3f}) size {b['size_m'][0] * 100:.1f}x{b['size_m'][1] * 100:.1f} cm reach {b['reach']:.3f} "
              f"{'ok' if b['reachable'] else 'OUT OF REACH'}")
    answer, dt = ask_llm(command, blocks)
    print(f'{time.strftime("%T")} [language] "{command}" (LLM {dt:.1f} s) -> {json.dumps(answer, ensure_ascii=False)}')
    target = next((b for b in blocks if b['id'] == answer['target_id']), None)
    same = {'blue': {'blue', 'light blue'}, 'light blue': {'blue', 'light blue'}}
    if target and answer['color'] != 'any' and target['color'] not in same.get(answer['color'], {answer['color']}):
        print(f"[check] rejected: command color {answer['color']} != {target['color']}"); target = None
    vis = frame.copy()
    for b in blocks:
        cv2.drawContours(vis, [b['contour']], -1, (0, 0, 255) if b is target else (200, 200, 200), 3)
        cv2.putText(vis, b['id'], (int(b['u']) - 50, int(b['v']) - 30), 0, 0.8, (0, 0, 255) if b is target else (230, 230, 230), 2)
    cv2.imwrite('command_last.jpg', vis)
    if not target:
        print('[result] no target'); return 1
    if not target['reachable']:
        print(f"[result] {target['id']} is out of reach ({target['reach']:.3f} m): move it closer to the arm"); return 1
    place = answer['place'] if answer['place'] in PLACES else None
    base = next((b for b in blocks if f"on_{b['id']}" == answer['place']), None)
    if base is target:
        base = None
    print(f"[result] {target['id']} at ({target['x']:+.3f}, {target['y']:+.3f}), grasp z {target['z']:+.3f}, "
          f"closing yaw {target['closing_yaw']:+.0f} deg")
    place_yaw = target['closing_yaw']
    if base:                       # stack: release on top of the base block, fingers along the base block's sides
        name, px, py = f"{base['id']} 위", base['x'], base['y']
        base_h = max(base['size_m'][1], 0.02)
        pz = board_z(calib, px, py) + base_h + target['size_m'][1] / 2 + 0.008
        place_yaw = base['closing_yaw']
        place = 'stack'
    elif place:
        name, px, py = PLACES[place]
        pz = board_z(calib, px, py) + target['size_m'][1] / 2 + 0.008      # release ~8 mm above the board
    if place:
        print(f'   place {name}: ({px:+.3f}, {py:+.3f}, {pz:+.3f}), closing yaw {place_yaw:+.0f} deg')
        args = (f"--x {target['x']:.3f} --y {target['y']:.3f} --z {target['z']:.3f} --yaw {target['closing_yaw']:.0f} "
                f"--place-x {px:.3f} --place-y {py:.3f} --place-z {pz:.3f} --place-yaw {place_yaw:.0f} --hover 0.08")
        if min(target['z'], pz) < SAFE_Z:
            args += ' --allow-below-safe'
        print(f'ros2 run vla_teleop teleop pick {args} --record')
    return 0


if __name__ == '__main__':
    sys.exit(main())
