#!/usr/bin/env python3
"""Sim helper for intrinsic calibration: spawn the checkerboard and move it through
random poses under the top camera (what a person would do by hand on the real setup).

  ros2 run vla_sim checkerboard_sweep.py --poses 40
"""
import argparse
import math
import random
import subprocess
import time

WORLD = 'vla_table'


def gz_call(service, reqtype, req):
    return subprocess.run(['gz', 'service', '-s', f'/world/{WORLD}/{service}', '--reqtype', reqtype,
                           '--reptype', 'gz.msgs.Boolean', '--timeout', '3000', '--req', req],
                          capture_output=True, text=True).stdout


def set_pose(x, y, z, roll, pitch, yaw):
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    q = (sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy,
         cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy)
    gz_call('set_pose', 'gz.msgs.Pose',
            f'name: "checkerboard", position: {{x: {x}, y: {y}, z: {z}}}, '
            f'orientation: {{x: {q[0]}, y: {q[1]}, z: {q[2]}, w: {q[3]}}}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--poses', type=int, default=40)
    ap.add_argument('--dwell', type=float, default=1.5)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    random.seed(a.seed)
    gz_call('create', 'gz.msgs.EntityFactory',
            'sdf: "<sdf version=\\"1.10\\"><include><uri>model://checkerboard</uri>'
            '<name>checkerboard</name><pose>0.19 0 0.2 0 0 0</pose></include></sdf>"')
    for i in range(a.poses):
        z = random.uniform(0.10, 0.40)
        reach = 0.12 * (0.75 - z) / 0.75 + 0.03          # keep the board in view
        set_pose(0.19 + random.uniform(-reach, reach), random.uniform(-1.4 * reach, 1.4 * reach), z,
                 random.uniform(-0.5, 0.5), random.uniform(-0.5, 0.5), random.uniform(-0.6, 0.6))
        print(f'pose {i + 1}/{a.poses}', flush=True)
        time.sleep(a.dwell)
    set_pose(3.0, 3.0, 0.0, 0, 0, 0)                     # park it out of the way
    print('done')


if __name__ == '__main__':
    main()
