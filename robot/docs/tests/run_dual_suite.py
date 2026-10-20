#!/usr/bin/env python3
"""Two-arm natural-language test suite: 5 actions x 2 trials, against Gazebo ground truth.

Needs `ros2 launch vla_bringup dual_sim_vla.launch.py` running (world vla_floor).
Each trial resets the scene, sends one command to /execute_command, then records the
planner's stages, the result, the moved object's true pose and before/after images.

  python3 docs/tests/run_dual_suite.py docs/test_report               # all 10 trials
  python3 docs/tests/run_dual_suite.py docs/test_report carry fix     # only one action, files tagged "fix"
"""
import json
import math
import os
import re
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.action import ActionClient
from sensor_msgs.msg import Image

from vla_interfaces.action import ExecuteCommand

WORLD = 'vla_floor'
HOME = {   # initial layout of vla_floor.sdf: model -> (x, y, yaw)
    'block_red': (0.17, 0.27, 0.0), 'block_blue': (0.17, -0.27, 0.0),
    'block_yellow': (0.21, 0.10, 0.3), 'block_green': (0.21, -0.10, 0.0), 'tray': (0.13, 0.0, 0.0),
}
FAR = (0.60, 0.0, 0.0)   # parking spot outside the work area

# action, command, scene changes, moved model, expected final (x, y, z) from planner_dual.yaml regions
TRIALS = [
    ('auto', '빨간 블록을 왼쪽 뒤 구석으로 옮겨', {}, 'block_red', (0.10, 0.26, 0.0125)),
    ('auto', '초록 블록을 오른쪽 앞으로 옮겨', {}, 'block_green', (0.22, -0.14, 0.0125)),
    ('named_arm', '왼팔로 노란 블록을 왼쪽으로 옮겨', {}, 'block_yellow', (0.16, 0.22, 0.0125)),
    ('named_arm', '오른팔로 파란 블록을 오른쪽 뒤 구석으로 옮겨', {}, 'block_blue', (0.10, -0.26, 0.0125)),
    ('stack', '빨간 블록을 노란 블록 위에 쌓아', {}, 'block_red', ('block_yellow', 0.0375)),
    ('stack', '파란 블록을 초록 블록 위에 쌓아', {}, 'block_blue', ('block_green', 0.0375)),
    ('handoff', '빨간 블록을 오른쪽으로 옮겨', {'tray': FAR}, 'block_red', (0.16, -0.22, 0.0125)),
    ('handoff', '파란 블록을 왼쪽으로 옮겨', {'tray': FAR}, 'block_blue', (0.16, 0.22, 0.0125)),
    ('carry', '그릇을 두 팔로 들어서 뒤로 옮겨', {}, 'tray', (0.10, 0.0, 0.0)),
    ('carry', '쟁반을 양손으로 들어서 가운데로 옮겨', {'tray': (0.10, 0.0, 0.0)}, 'tray', (0.13, 0.0, 0.0)),
]


def gz_pose(model):
    s = subprocess.run(['gz', 'model', '-m', model, '-p'], capture_output=True, text=True).stdout
    m = re.findall(r'Pose \[ XYZ \(m\) \] \[ RPY \(rad\) \]:\s*\[([^\]]+)\]\s*\[([^\]]+)\]', s)
    if not m:
        return None
    return [float(v) for v in m[-1][0].split()], [float(v) for v in m[-1][1].split()]


def gz_set(model, x, y, yaw):
    z = 0.0 if model == 'tray' else 0.0125
    subprocess.run(['gz', 'service', '-s', f'/world/{WORLD}/set_pose', '--reqtype', 'gz.msgs.Pose',
                    '--reptype', 'gz.msgs.Boolean', '--timeout', '2000', '--req',
                    f'name: "{model}", position: {{x: {x}, y: {y}, z: {z}}}, '
                    f'orientation: {{z: {math.sin(yaw / 2)}, w: {math.cos(yaw / 2)}}}'],
                   capture_output=True)


class Suite:

    def __init__(self, out):
        self.out = out
        os.makedirs(out, exist_ok=True)
        rclpy.init()
        self.n = rclpy.create_node('dual_test_suite')
        self.img = None
        self.n.create_subscription(Image, '/vla/debug_image', self._on_img, 1)
        self.ac = ActionClient(self.n, ExecuteCommand, 'execute_command')
        threading.Thread(target=rclpy.spin, args=(self.n,), daemon=True).start()
        self.ac.wait_for_server()

    def _on_img(self, m):
        a = np.frombuffer(m.data, np.uint8).reshape(m.height, m.width, 3)
        self.img = cv2.cvtColor(a, cv2.COLOR_RGB2BGR) if m.encoding == 'rgb8' else a.copy()

    tag = ''

    def snapshot(self, name):
        name = name.replace('.png', f'{self.tag}.png')
        self.img = None
        t = time.time()
        while self.img is None and time.time() - t < 5:
            time.sleep(0.05)
        if self.img is not None:
            cv2.imwrite(os.path.join(self.out, name), self.img)
            return name
        return None

    def run(self, i, action, cmd, scene, model, expect):
        for m, p in HOME.items():
            gz_set(m, *p)
        for m, p in scene.items():
            gz_set(m, *p)
        time.sleep(3.0)
        before = self.snapshot(f'trial{i:02d}_before.png')
        stages, tilt = [], {'max': 0.0}
        stop = [False]

        def watch():
            while not stop[0]:
                p = gz_pose(model)
                if p:
                    tilt['max'] = max(tilt['max'], math.degrees(max(abs(p[1][0]), abs(p[1][1]))))
                time.sleep(0.3)
        if model == 'tray':
            threading.Thread(target=watch, daemon=True).start()

        t0 = time.time()
        f = self.ac.send_goal_async(ExecuteCommand.Goal(command=cmd),
                                    feedback_callback=lambda fb: stages.append(fb.feedback.stage))
        while not f.done():
            time.sleep(0.05)
        rf = f.result().get_result_async()
        while not rf.done():
            time.sleep(0.05)
        res = rf.result().result
        dur = time.time() - t0
        stop[0] = True
        time.sleep(1.5)
        after = self.snapshot(f'trial{i:02d}_after.png')

        (x, y, z), (r, p, yw) = gz_pose(model)
        if isinstance(expect[0], str):            # stacked on another block
            (bx, by, _), _ = gz_pose(expect[0])
            tx, ty, tz = bx, by, expect[1]
        else:
            tx, ty, tz = expect
        llm = next((s for s in stages if s.startswith('LLM')), '')
        llm_s = float(re.search(r'LLM \(([\d.]+)s\)', llm).group(1)) if llm else None
        arms = sorted({m.group(1) for s in stages for m in [re.search(r'\[(left|right|both) arm', s)] if m})
        rec = {
            'trial': i, 'action': action, 'command': cmd, 'success': bool(res.success),
            'message': res.message, 'plan': res.plan_json, 'arms': arms,
            'handoff': any('hand-off' in s for s in stages),
            'llm_s': llm_s, 'duration_s': round(dur, 1),
            'final': [round(x, 4), round(y, 4), round(z, 4)], 'target': [round(tx, 4), round(ty, 4), tz],
            'xy_err_mm': round(math.hypot(x - tx, y - ty) * 1000, 1), 'z_err_mm': round((z - tz) * 1000, 1),
            'tilt_max_deg': round(tilt['max'], 1) if model == 'tray' else None,
            'verified': [s for s in stages if 'verified' in s],
            'images': [before, after],
        }
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        return rec


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'docs/test_report'
    only = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != 'all' else None
    tag = f'_{sys.argv[3]}' if len(sys.argv) > 3 else ''
    s = Suite(out)
    s.tag = tag
    results = [s.run(i + 1, *t) for i, t in enumerate(TRIALS) if only in (None, t[0])]
    with open(os.path.join(out, f'results{tag}.json'), 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    ok = sum(r['success'] for r in results)
    print(f'\n{ok}/{len(results)} succeeded')
    rclpy.shutdown()


if __name__ == '__main__':
    main()
