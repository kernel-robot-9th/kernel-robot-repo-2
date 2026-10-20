"""Teleop viewer: follower /joint_states -> tool position (FK, arm base frame) over the live top camera.

Read-only (sends no commands). Writes <session>/pose_log.csv (1 Hz) and <session>/latest_top.jpg (clean frame, 1 Hz).
  python3 -m vla_teleop.viewer <session_dir> <top_camera> <safe_z_min_m>
"""
import os
import sys
import threading
import time

import cv2
import rclpy
from sensor_msgs.msg import JointState

from vla_executor.omx_ik import fk_tool


def main():
    session, camera, safe_z = sys.argv[1], sys.argv[2], float(sys.argv[3])
    state = {}

    def on_joints(message):
        named = dict(zip(message.name, message.position))
        if all(f'joint{i}' in named for i in range(1, 6)):
            state.update(q=[named[f'joint{i}'] for i in range(1, 6)], grip=named.get('gripper_joint_1'), t=time.time())

    rclpy.init()
    node = rclpy.create_node('vla_teleop_viewer')
    node.create_subscription(JointState, '/joint_states', on_joints, 10)
    threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()

    cap = cv2.VideoCapture(camera, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    log_path = os.path.join(session, 'pose_log.csv')
    new = not os.path.exists(log_path)
    log = open(log_path, 'a')
    if new:
        log.write('time,x_m,y_m,z_m,j1,j2,j3,j4,j5,gripper\n')
    title = 'vla_teleop view (q: close)'
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(title, 1280, 720)
    last_write = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue
        lines = []
        q = state.get('q')
        if q is None or time.time() - state.get('t', 0) > 1.0:
            lines.append(('follower: no /joint_states', (0, 0, 255)))
        else:
            x, y, z = fk_tool(q)
            tilt = (q[1] + q[2] + q[3] - 1.5708) * 57.296
            low = z < safe_z
            lines.append((f'tool  x {x:+.3f}  y {y:+.3f}  z {z:+.3f} m' + ('   BELOW SAFE Z' if low else ''),
                          (0, 0, 255) if low else (0, 255, 255)))
            lines.append((f'tilt {tilt:+.1f} deg   gripper {state.get("grip") or 0:+.2f}   joints '
                          + ' '.join(f'{v:+.2f}' for v in q), (255, 255, 255)))
            if time.time() - last_write > 1.0:
                last_write = time.time()
                cv2.imwrite(os.path.join(session, 'latest_top.jpg'), frame)
                log.write(f'{time.strftime("%T")},{x:.4f},{y:.4f},{z:.4f},' + ','.join(f'{v:.4f}' for v in q)
                          + f',{state.get("grip") or 0:.4f}\n')
                log.flush()
        shown = frame.copy()
        cv2.rectangle(shown, (0, 0), (shown.shape[1], 30 + 44 * len(lines)), (0, 0, 0), -1)
        for i, (text, color) in enumerate(lines):
            cv2.putText(shown, text, (14, 44 + 44 * i), cv2.FONT_HERSHEY_SIMPLEX, 1.1, color, 2)
        cv2.imshow(title, shown)
        if cv2.waitKey(30) & 0xFF == ord('q'):
            break
    cap.release()
    cv2.destroyAllWindows()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
