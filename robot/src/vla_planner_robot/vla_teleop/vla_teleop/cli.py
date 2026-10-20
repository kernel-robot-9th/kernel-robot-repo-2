"""Real OMX arm teleop tool: leader arm -> follower arm, with a coordinate viewer and point recording.

  ros2 run vla_teleop teleop scan                      # every OpenRB: role, motor IDs, errors, voltage (read-only)
  ros2 run vla_teleop teleop start --arm right         # error check -> follower -> slow align -> leader -> viewer
  ros2 run vla_teleop teleop here blue_round           # record tool x/y/z + tilt + top/wrist images
  ros2 run vla_teleop teleop stop                      # fold the arm with the leader first
  ros2 run vla_teleop teleop clear-errors --arm right  # reboot motors that report a hardware error (arm stopped)
  ros2 run vla_teleop teleop status
  ros2 run vla_teleop teleop tap --x 0.19 --y -0.08 --z -0.04 [--dry-run]   # follower only: hover, touch, back, stop
  ros2 run vla_teleop teleop pick --x .. --y .. --z .. --place-x .. --place-y .. --place-z .. [--record --dry-run]
  ros2 run vla_teleop teleop camera --tune             # find + save fixed exposure / white balance (scene lit as usual)
  ros2 run vla_teleop teleop camera                    # re-apply the saved values (start/tap/pick also do this)

Safety: the follower starts with init_position:=false (no automatic motion) and is moved to the leader pose
over align_duration_s before the leader is started, so it never jumps. Stopping turns the follower torque off,
so `stop` refuses unless the arm is folded (or --force). Settings: config/arms.yaml.
"""
import argparse
import glob
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time

import yaml

from vla_teleop import dxl

STATE_DIR = os.path.expanduser('~/.cache/vla_teleop')
STATE_FILE = os.path.join(STATE_DIR, 'state.json')
LID_COLORS = {'orange': [(5, 120, 120), (18, 255, 255)], 'green': [(45, 45, 60), (85, 255, 190)],
              'blue': [(95, 90, 80), (125, 255, 255)]}


# ---------------------------------------------------------------------------- config / state
def default_config():
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(get_package_share_directory('vla_teleop'), 'config', 'arms.yaml')
    except Exception:  # noqa: BLE001 - source tree
        return os.path.join(os.path.dirname(__file__), '..', 'config', 'arms.yaml')


def load_state():
    try:
        with open(STATE_FILE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, 'w') as handle:
        json.dump(state, handle, indent=2)


def alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError, TypeError):
        return False


def running_state():
    state = load_state()
    if state and any(alive(pgid) for pgid in state.get('pgids', {}).values()):
        return state
    return None


# ---------------------------------------------------------------------------- processes
def child_env():
    env = dict(os.environ)
    for key in ('VIRTUAL_ENV', 'CONDA_PREFIX'):    # a venv/conda python breaks rclpy tools
        env.pop(key, None)
    return env


def launch(cmd, log_path):
    """Start a process in its own process group; returns the group id."""
    log = open(log_path, 'w')
    process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=child_env(), start_new_session=True)
    return process.pid


def wait_for(log_path, needle, pgid, timeout_s, count=1):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not alive(pgid):
            raise RuntimeError(f'process exited, see {log_path}')
        try:
            with open(log_path) as handle:
                if handle.read().count(needle) >= count:
                    return
        except OSError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f'timeout waiting for "{needle}" in {log_path}')


def stop_group(pgid, name, timeout_s=8.0):
    if not alive(pgid):
        return
    print(f'{time.strftime("%T")} stop {name}')
    for sig, wait in ((signal.SIGINT, timeout_s), (signal.SIGTERM, 3.0), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        deadline = time.time() + wait
        while time.time() < deadline and alive(pgid):
            time.sleep(0.2)
        if not alive(pgid):
            return


# ---------------------------------------------------------------------------- ROS helpers (imported lazily)
def read_follower_joints(timeout_s=3.0):
    import rclpy
    from sensor_msgs.msg import JointState
    if not rclpy.ok():
        rclpy.init()
    node = rclpy.create_node('vla_teleop_cli')
    got = {}
    node.create_subscription(JointState, '/joint_states', lambda m: got.setdefault('m', m), 10)
    deadline = time.time() + timeout_s
    while 'm' not in got and time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    node.destroy_node()
    if 'm' not in got:
        return None
    named = dict(zip(got['m'].name, got['m'].position))
    return [named[f'joint{i}'] for i in range(1, 6)], named.get('gripper_joint_1')


def align_follower(target, duration_s, gripper=None):
    """Move the follower arm joints (and the gripper, when given) to `target` over duration_s."""
    import rclpy
    from builtin_interfaces.msg import Duration
    from control_msgs.action import FollowJointTrajectory
    from rclpy.action import ActionClient
    from trajectory_msgs.msg import JointTrajectoryPoint
    if not rclpy.ok():
        rclpy.init()
    node = rclpy.create_node('vla_teleop_align')
    client = ActionClient(node, FollowJointTrajectory, '/arm_controller/follow_joint_trajectory')
    if not client.wait_for_server(timeout_sec=10.0):
        raise RuntimeError('follower arm_controller action not available')
    goal = FollowJointTrajectory.Goal()
    goal.trajectory.joint_names = [f'joint{i}' for i in range(1, 6)] + ([] if gripper is None else ['gripper_joint_1'])
    seconds = int(duration_s)
    goal.trajectory.points = [JointTrajectoryPoint(
        positions=list(target) + ([] if gripper is None else [gripper]), time_from_start=Duration(sec=seconds, nanosec=int((duration_s - seconds) * 1e9)))]
    future = client.send_goal_async(goal)
    rclpy.spin_until_future_complete(node, future)
    if not future.result().accepted:
        raise RuntimeError('alignment goal rejected')
    result = future.result().get_result_async()
    rclpy.spin_until_future_complete(node, result)
    node.destroy_node()
    return result.result().result.error_code


def tool_pose(q):
    from vla_executor.omx_ik import fk_tool
    x, y, z = fk_tool(q)
    tilt_deg = math.degrees(q[1] + q[2] + q[3] - math.pi / 2)
    return x, y, z, tilt_deg


def path_min_z(q_from, q_to, steps=40):
    """Lowest tool z along a straight joint-space move (what the trajectory controller interpolates)."""
    from vla_executor.omx_ik import fk_tool
    return min(fk_tool([a + (b - a) * k / steps for a, b in zip(q_from, q_to)])[2] for k in range(steps + 1))


def plan_tap(home_q, x, y, z, hover_dz, safe_z_min, allow_below_safe=False):
    """[입력] current joints, touch point (arm base frame, m) [출력] list of (name, joints) or raises ValueError.

    home -> hover (z + hover_dz) -> touch (z) -> hover -> home, tool pointing straight down.
    """
    from vla_executor.omx_ik import top_down_ik
    if z < safe_z_min and not allow_below_safe:
        raise ValueError(f'touch z {z:+.3f} is below the safe height {safe_z_min:+.3f} (use --allow-below-safe)')
    hover, touch = top_down_ik(x, y, z + hover_dz), top_down_ik(x, y, z)
    if hover is None or touch is None:
        raise ValueError(f'({x:+.3f}, {y:+.3f}) is out of reach at z {z:+.3f} / {z + hover_dz:+.3f}')
    home = list(home_q)
    moves = [('hover', home, hover), ('touch', hover, touch), ('lift', touch, hover), ('home', hover, home)]
    floor = min(z, safe_z_min) if allow_below_safe else safe_z_min
    for name, q_from, q_to in moves:
        low = path_min_z(q_from, q_to)
        if low < floor - 0.002:
            raise ValueError(f'{name}: the joint-space path dips to z {low:+.3f} (limit {floor:+.3f})')
    return [(name, q_to) for name, _, q_to in moves]


def ik_rect(x, y, z, closing_yaw=None):
    """Top-down IK with the finger closing direction (rad, base frame) for a rectangular object: the fingers are
    symmetric, so yaw and yaw + pi are the same grasp (the smaller joint5 is used); no square-block pi/2 folding."""
    from vla_executor.omx_ik import top_down_ik, wrap
    q = top_down_ik(x, y, z)
    if q is None or closing_yaw is None:
        return q
    q5 = wrap(q[0] + math.pi / 2 - closing_yaw)
    q[4] = min(q5, wrap(q5 + math.pi), key=abs)
    return q


def plan_pick(home_q, pick, place, hover_dz, safe_z_min, grip_open, grip_close, allow_below_safe=False,
              grasp_yaw=None, place_yaw=None):
    """[입력] current joints, pick / place tool points (arm base frame, m) [출력] [(name, joints, gripper, min s)].

    open -> above pick -> down -> close -> up -> above place -> down -> open -> up -> home (closed); tool points down.
    grasp_yaw / place_yaw: finger closing direction (rad, arm base frame) at the pick / place (place defaults to the
    pick yaw, so the object keeps its orientation); None -> joint5 = 0.
    Raises ValueError when a point is out of reach or a move dips below the allowed height.
    """
    lowest = min(pick[2], place[2])
    place_yaw = grasp_yaw if place_yaw is None else place_yaw
    if lowest < safe_z_min and not allow_below_safe:
        raise ValueError(f'z {lowest:+.3f} is below the safe height {safe_z_min:+.3f} (use --allow-below-safe)')
    q = {}
    for name, (x, y, z) in (('pick', pick), ('above pick', (pick[0], pick[1], pick[2] + hover_dz)),
                            ('place', place), ('above place', (place[0], place[1], place[2] + hover_dz))):
        q[name] = ik_rect(x, y, z, grasp_yaw if 'pick' in name else place_yaw)
        if q[name] is None:
            raise ValueError(f'{name} ({x:+.3f}, {y:+.3f}, {z:+.3f}) is out of reach')
    home = list(home_q)
    plan = [('open', home, grip_open, 2.0), ('above pick', q['above pick'], grip_open, 3.0),
            ('down', q['pick'], grip_open, 6.0), ('close', q['pick'], grip_close, 2.0),
            ('up', q['above pick'], grip_close, 6.0), ('above place', q['above place'], grip_close, 3.0),
            ('down', q['place'], grip_close, 6.0), ('release', q['place'], grip_open, 2.0),
            ('up', q['above place'], grip_open, 6.0), ('home', home, grip_close, 3.0)]
    floor = min(lowest, safe_z_min) if allow_below_safe else safe_z_min
    previous = home
    for name, joints, _, _ in plan:
        low = path_min_z(previous, joints)
        if low < floor - 0.002:
            raise ValueError(f'{name}: the joint-space path dips to z {low:+.3f} (limit {floor:+.3f})')
        previous = joints
    return plan


def camera(spec):
    """Config camera entry (a /dev path or a glob, e.g. the hub-port suffix of a by-path name) -> device path."""
    matches = sorted(glob.glob(spec))
    return matches[0] if matches else spec


def snapshot(device, path):
    import cv2
    device = camera(device)
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if 'SNAP' in device:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    ok, frame = False, None
    for _ in range(10):
        ok, frame = cap.read()
    cap.release()
    if ok:
        cv2.imwrite(path, frame)
    print(f'   {"saved" if ok else "could not read"} {path}')


def camera_devices(cfg):
    """{name: (device path, capture size or None)} for the cameras that are plugged in."""
    devices = {'top': (camera(cfg['top_camera']), (1920, 1080))}
    for arm, entry in cfg['arms'].items():
        devices[f'{arm}_wrist'] = (camera(entry['wrist_camera']), None)
    return {name: dev for name, dev in devices.items() if os.path.exists(dev[0])}


def apply_camera_settings(cfg, quiet=False):
    """Re-apply the saved fixed exposure / white balance to every plugged-in camera. [출력] names applied."""
    from vla_teleop import camera_lock
    saved = camera_lock.load(cfg['camera_settings'])
    applied = []
    for name, (device, _) in camera_devices(cfg).items():
        if name not in saved:
            continue
        try:
            failed = camera_lock.lock(device, saved[name])
        except Exception as error:  # noqa: BLE001 - a camera problem must not stop the arm tools
            print(f'   camera {name}: could not apply settings ({error})', file=sys.stderr)
            continue
        applied.append(name)
        if failed or not quiet:
            print(f'   camera {name} ({device}): fixed exposure {saved[name].get("exposure_time_absolute")}, '
                  f'white balance {saved[name].get("white_balance_temperature")} K'
                  + (f'  NOT APPLIED: {failed}' if failed else ''))
    return applied


def move_seconds(q_from, q_to, speed_deg_s, min_s):
    return max(min_s, max(abs(math.degrees(b - a)) for a, b in zip(q_from, q_to)) / speed_deg_s)


# ---------------------------------------------------------------------------- commands
def cmd_scan(cfg, args):
    names = {}
    for arm, entry in cfg['arms'].items():
        names[entry['follower_serial']] = f'{arm} follower'
        names[entry['leader_serial']] = f'{arm} leader'
    for serial, port, role, motors in dxl.scan_all():
        print(f'{serial}  {os.path.basename(port):8s}  {role:8s}  ({names.get(serial, "not in config")})')
        for m in motors:
            flags = ', '.join(dxl.error_names(m['hw_error'] or 0)) or 'ok'
            print(f"   ID {m['id']:2d} {m['model']:11s} {dxl.raw_to_rad(m['position_raw'] or 2048):+.3f} rad  "
                  f"error {m['hw_error']} ({flags})  {m['voltage_v']} V  {m['temperature_c']} C  "
                  f"torque {'ON' if m['torque'] else 'off'}")
    return 0


def cmd_start(cfg, args):
    if running_state():
        print('already running (vla_teleop status); stop it first', file=sys.stderr)
        return 1
    arm = cfg['arms'][args.arm]
    follower_port, leader_port = dxl.port_path(arm['follower_serial']), dxl.port_path(arm['leader_serial'])
    with dxl.Bus(arm['follower_serial']) as bus:
        motors = [bus.motor(i) for i in dxl.FOLLOWER_IDS]
        follower_q = bus.joints_rad(dxl.FOLLOWER_IDS[:5])
    missing = [i for i, m in zip(dxl.FOLLOWER_IDS, motors) if m is None]
    errors = {m['id']: dxl.error_names(m['hw_error']) for m in motors if m and m['hw_error']}
    if missing or errors:
        print(f'follower not ready: missing {missing}, errors {errors}. Run: teleop clear-errors --arm {args.arm}',
              file=sys.stderr)
        return 1
    with dxl.Bus(arm['leader_serial']) as bus:
        leader_q = bus.joints_rad(dxl.LEADER_IDS[:5])
    gap = [math.degrees(a - b) for a, b in zip(leader_q, follower_q)]
    print(f'{time.strftime("%T")} {args.arm} arm: follower {arm["follower_serial"]}, leader {arm["leader_serial"]}')
    print(f'   leader-follower gap (deg): {[round(g, 1) for g in gap]}')
    if args.dry_run:
        print('dry run: nothing started')
        return 0

    session = os.path.join(STATE_DIR, time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(session, exist_ok=True)
    state = {'arm': args.arm, 'session': session, 'pgids': {}, 'started': time.strftime('%F %T')}
    apply_camera_settings(cfg, quiet=True)
    try:
        print(f'{time.strftime("%T")} follower: start (init_position false, holds its pose)')
        state['pgids']['follower'] = launch(
            ['ros2', 'launch', 'open_manipulator_bringup', 'omx_f_follower_ai.launch.py', f'port_name:={follower_port}',
             'init_position:=false', 'start_rviz:=false'], os.path.join(session, 'follower.log'))
        save_state(state)
        wait_for(os.path.join(session, 'follower.log'), 'Torque ON', state['pgids']['follower'], 40, count=6)
        wait_for(os.path.join(session, 'follower.log'), 'activated arm_controller', state['pgids']['follower'], 40)
        if max(abs(g) for g in gap) > cfg['align_skip_deg']:
            print(f'{time.strftime("%T")} follower: align to the leader over {cfg["align_duration_s"]:.0f} s')
            code = align_follower(leader_q, float(cfg['align_duration_s']))
            joints = read_follower_joints()
            rest = [round(math.degrees(a - b), 1) for a, b in zip(leader_q, joints[0])] if joints else '?'
            print(f'   done (error_code {code}), remaining gap (deg): {rest}')
        print(f'{time.strftime("%T")} leader: start (the follower now follows it)')
        state['pgids']['leader'] = launch(
            ['ros2', 'launch', 'open_manipulator_bringup', 'omx_l_leader_ai.launch.py', f'port_name:={leader_port}'],
            os.path.join(session, 'leader.log'))
        save_state(state)
        wait_for(os.path.join(session, 'leader.log'), 'activated joint_trajectory_command_broadcaster',
                 state['pgids']['leader'], 40)
        if not args.no_view and os.environ.get('DISPLAY'):
            state['pgids']['viewer'] = launch(
                [sys.executable, '-m', 'vla_teleop.viewer', session, camera(cfg['top_camera']), str(cfg['safe_z_min_m'])],
                os.path.join(session, 'viewer.log'))
            save_state(state)
    except Exception as error:  # noqa: BLE001 - report and clean up whatever started
        print(f'start failed: {error}', file=sys.stderr)
        for name in ('viewer', 'leader', 'follower'):
            stop_group(state['pgids'].get(name), name)
        return 1
    print(f'{time.strftime("%T")} teleop running. Logs: {session}')
    print('   record a point: teleop here <name>    stop (fold first): teleop stop')
    return 0


def cmd_here(cfg, args):
    import cv2
    import numpy as np
    state = running_state()
    joints = read_follower_joints()
    if joints is None:
        print('no follower /joint_states (is teleop running, same ROS_DOMAIN_ID?)', file=sys.stderr)
        return 1
    q, grip = joints
    x, y, z, tilt = tool_pose(q)
    print(f'{time.strftime("%T")} {args.label}: tool x {x:+.4f} y {y:+.4f} z {z:+.4f} m  tilt {tilt:+.1f} deg'
          + ('' if abs(tilt) <= 5 else '  (gripper not vertical: x, y are not straight above the target)')
          + ('  BELOW SAFE Z' if z < cfg['safe_z_min_m'] else ''))
    arm = cfg['arms'][state['arm'] if state else args.arm]
    cap = cv2.VideoCapture(camera(arm['wrist_camera']), cv2.CAP_V4L2)
    ok, wrist = False, None
    for _ in range(10):
        ok, wrist = cap.read()
    cap.release()
    lid_note = ''
    color = args.label.split('_')[0]
    if ok and color in LID_COLORS:
        hsv = cv2.cvtColor(wrist, cv2.COLOR_BGR2HSV)
        lo, hi = LID_COLORS[color]
        mask = cv2.morphologyEx(cv2.inRange(hsv, np.array(lo), np.array(hi)), cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
        moments = cv2.moments(mask)
        if moments['m00'] > 0:
            du = moments['m10'] / moments['m00'] - wrist.shape[1] / 2
            dv = moments['m01'] / moments['m00'] - wrist.shape[0] / 2
            centred = abs(du) < 60 and abs(dv) < 60
            lid_note = f'{color} {100 * mask.mean() / 255:.0f} % of wrist image, offset ({du:+.0f},{dv:+.0f}) px' \
                       + (' (centred)' if centred else ' (not centred)')
        else:
            lid_note = f'no {color} in the wrist image'
        print('   wrist:', lid_note)
    if args.dry:
        return 0
    session = state['session'] if state else os.path.join(STATE_DIR, 'manual')
    os.makedirs(session, exist_ok=True)
    stem = os.path.join(session, f'here_{args.label}_{time.strftime("%H%M%S")}')
    latest = os.path.join(session, 'latest_top.jpg')
    if os.path.exists(latest):
        shutil.copy(latest, stem + '_top.jpg')
    if ok:
        cv2.imwrite(stem + '_wrist.jpg', wrist)
    path = os.path.join(session, 'points.csv')
    new = not os.path.exists(path)
    with open(path, 'a') as handle:
        if new:
            handle.write('label,time,x_m,y_m,z_m,tilt_deg,j1,j2,j3,j4,j5,gripper,wrist\n')
        handle.write(f'{args.label},{time.strftime("%T")},{x:.4f},{y:.4f},{z:.4f},{tilt:.1f},'
                     + ','.join(f'{v:.4f}' for v in q) + f',{grip or 0:.4f},"{lid_note}"\n')
    print(f'   saved to {path}')
    return 0


def cmd_stop(cfg, args):
    state = running_state()
    if not state:
        print('nothing running')
        return 0
    joints = read_follower_joints() if alive(state['pgids'].get('follower')) else None
    if joints and not args.force:
        x, _, z, _ = tool_pose(joints[0])
        folded = cfg['folded']
        if x > folded['max_x_m'] or z > folded['max_z_m']:
            print(f'arm not folded (tool x {x:.3f}, z {z:.3f}). Stopping turns the follower torque off and it would '
                  f'drop. Fold it with the leader first, or use --force.', file=sys.stderr)
            return 2
    for name in ('leader', 'follower', 'viewer'):
        stop_group(state['pgids'].get(name), name)
    print(f'stopped. Logs and points: {state["session"]}')
    return 0


def prepare_follower(cfg, args):
    """[출력] (arm config, home joints) or None after printing why the follower cannot be used."""
    if running_state():
        print('teleop is running (the leader would fight the moves); stop it first', file=sys.stderr)
        return None
    arm = cfg['arms'][args.arm]
    with dxl.Bus(arm['follower_serial']) as bus:
        motors = [bus.motor(i) for i in dxl.FOLLOWER_IDS]
        home_q = bus.joints_rad(dxl.FOLLOWER_IDS[:5])
    errors = {m['id']: dxl.error_names(m['hw_error']) for m in motors if m and m['hw_error']}
    if None in motors or errors:
        print(f'follower not ready: errors {errors}. Run: teleop clear-errors --arm {args.arm}', file=sys.stderr)
        return None
    hx, _, hz, _ = tool_pose(home_q)
    folded = cfg['folded']
    if hx > folded['max_x_m'] or hz > folded['max_z_m']:
        print(f'start pose is not folded (tool x {hx:.3f}, z {hz:.3f}); the follower is stopped at the end, '
              f'so it must start folded', file=sys.stderr)
        return None
    return arm, home_q


def run_plan(cfg, args, arm, home_q, plan, tag):
    """Execute [(name, joints, gripper or None, min seconds)] on the follower alone, then stop it at home."""
    speed = float(cfg.get('tap_speed_deg_s', 15.0))
    previous = home_q
    for name, q, grip, min_s in plan:
        x, y, z, tilt = tool_pose(q)
        seconds = move_seconds(previous, q, speed, min_s)
        print(f'   {name:12s} tool ({x:+.3f}, {y:+.3f}, {z:+.3f}) tilt {tilt:+.1f}  '
              + (f'gripper {grip:+.2f}  ' if grip is not None else '') + f'{seconds:.1f} s')
        previous = q
    if args.dry_run:
        print('dry run: nothing started')
        return 0
    session = os.path.join(STATE_DIR, time.strftime('%Y%m%d-%H%M%S') + f'-{tag}')
    os.makedirs(session, exist_ok=True)
    state = {'arm': args.arm, 'session': session, 'pgids': {}, 'started': time.strftime('%F %T')}
    apply_camera_settings(cfg, quiet=True)
    if args.record:
        state['pgids']['recorder'] = launch(
            [sys.executable, '-m', 'vla_teleop.recorder', session, f'top={camera(cfg["top_camera"])}',
             f'wrist={camera(arm["wrist_camera"])}'], os.path.join(session, 'recorder.log'))
        wait_for(os.path.join(session, 'recorder.log'), 'recording', state['pgids']['recorder'], 10)
        print(f'{time.strftime("%T")} recording top + wrist video')
    print(f'{time.strftime("%T")} follower: start (init_position false, holds its pose)')
    state['pgids']['follower'] = launch(
        ['ros2', 'launch', 'open_manipulator_bringup', 'omx_f_follower_ai.launch.py',
         f'port_name:={dxl.port_path(arm["follower_serial"])}', 'init_position:=false', 'start_rviz:=false'],
        os.path.join(session, 'follower.log'))
    save_state(state)
    try:
        wait_for(os.path.join(session, 'follower.log'), 'Torque ON', state['pgids']['follower'], 40, count=6)
        wait_for(os.path.join(session, 'follower.log'), 'activated arm_controller', state['pgids']['follower'], 40)
        previous = home_q
        for name, q, grip, min_s in plan:
            code = align_follower(q, move_seconds(previous, q, speed, min_s), gripper=grip)
            joints = read_follower_joints()
            if joints:
                x, y, z, tilt = tool_pose(joints[0])
                print(f'{time.strftime("%T")} {name:12s} done (error_code {code})  tool ({x:+.3f}, {y:+.3f}, '
                      f'{z:+.3f}) tilt {tilt:+.1f}' + (f'  gripper {joints[1]:+.3f}' if joints[1] is not None else ''))
            if name == 'touch' and not args.record:   # cameras are busy while recording
                time.sleep(1.0)
                for label, device in (('wrist', arm['wrist_camera']), ('top', cfg['top_camera'])):
                    snapshot(device, os.path.join(session, f'touch_{label}.jpg'))
            previous = q
    except Exception as error:  # noqa: BLE001 - keep torque on, report
        print(f'{tag} failed: {error}. The follower keeps holding its pose; fold it, then: teleop stop --force',
              file=sys.stderr)
        return 1
    finally:
        if args.record:
            time.sleep(1.0)
            stop_group(state['pgids'].get('recorder'), 'recorder')
    stop_group(state['pgids']['follower'], 'follower')
    print(f'{time.strftime("%T")} done. Log: {session}')
    return 0


def cmd_tap(cfg, args):
    """Follower only (no leader): hover above (x, y), go down to z, come back up, return to the start pose, stop."""
    ready = prepare_follower(cfg, args)
    if not ready:
        return 1
    arm, home_q = ready
    try:
        plan = plan_tap(home_q, args.x, args.y, args.z, args.hover, cfg['safe_z_min_m'], args.allow_below_safe)
    except ValueError as error:
        print(f'refused: {error}', file=sys.stderr)
        return 1
    print(f'{time.strftime("%T")} {args.arm} tap at x {args.x:+.3f} y {args.y:+.3f} z {args.z:+.3f} '
          f'(hover {args.z + args.hover:+.3f})')
    return run_plan(cfg, args, arm, home_q,
                    [(name, q, None, 6.0 if name in ('touch', 'lift') else 3.0) for name, q in plan], 'tap')


def cmd_pick(cfg, args):
    """Follower only: open, pick at (x, y, z), carry, release at (place x, y, z), return to the start pose, stop."""
    ready = prepare_follower(cfg, args)
    if not ready:
        return 1
    arm, home_q = ready
    grip = cfg['gripper']
    try:
        plan = plan_pick(home_q, (args.x, args.y, args.z), (args.place_x, args.place_y, args.place_z), args.hover,
                         cfg['safe_z_min_m'], grip['open'], grip['close'], args.allow_below_safe,
                         None if args.yaw is None else math.radians(args.yaw),
                         None if args.place_yaw is None else math.radians(args.place_yaw))
    except ValueError as error:
        print(f'refused: {error}', file=sys.stderr)
        return 1
    print(f'{time.strftime("%T")} {args.arm} pick at ({args.x:+.3f}, {args.y:+.3f}, {args.z:+.3f}) -> place at '
          f'({args.place_x:+.3f}, {args.place_y:+.3f}, {args.place_z:+.3f})')
    return run_plan(cfg, args, arm, home_q, plan, 'pick')


def cmd_camera(cfg, args):
    """--tune: measure and save fixed exposure / white balance; otherwise re-apply the saved values."""
    from vla_teleop import camera_lock
    devices = camera_devices(cfg)
    if not devices:
        print('no configured camera is plugged in (top_camera / wrist_camera in arms.yaml)', file=sys.stderr)
        return 1
    if running_state():
        print('note: teleop is running; the viewer keeps the top camera busy, tuning may fail', file=sys.stderr)
    if args.tune:
        saved = camera_lock.load(cfg['camera_settings'])
        for name in args.only or devices:
            if name not in devices:
                print(f'   camera {name}: not plugged in, skipped', file=sys.stderr)
                continue
            device, size = devices[name]
            try:
                saved[name] = camera_lock.tune(device, *(size or (None, None)))
            except RuntimeError as error:
                print(f'   camera {name}: {error}; not saved', file=sys.stderr)
        camera_lock.save(cfg['camera_settings'], saved)
        print(f'saved to {os.path.expanduser(cfg["camera_settings"])}')
        return 0
    applied = apply_camera_settings(cfg)
    if not applied:
        print(f'nothing applied: no saved settings for the plugged-in cameras ({", ".join(devices)}). '
              f'Run: teleop camera --tune', file=sys.stderr)
        return 1
    return 0


def cmd_clear_errors(cfg, args):
    state = running_state()
    if state and state.get('arm') == args.arm:
        print('teleop is running on this arm; stop it first (the port is in use)', file=sys.stderr)
        return 1
    arm = cfg['arms'][args.arm]
    for role, serial, ids in (('follower', arm['follower_serial'], dxl.FOLLOWER_IDS),
                              ('leader', arm['leader_serial'], dxl.LEADER_IDS)):
        with dxl.Bus(serial) as bus:
            bad = [(i, bus.read(i, 'hw_error')) for i in ids]
            bad = [(i, code) for i, code in bad if code]
            if not bad:
                print(f'{role} {serial}: no hardware errors')
                continue
            for dxl_id, code in bad:
                print(f'{role} {serial}: ID {dxl_id} error {code} ({", ".join(dxl.error_names(code))}) -> reboot '
                      + ('ok' if bus.reboot(dxl_id) else 'FAILED'))
            time.sleep(1.0)
            after = {i: bus.read(i, 'hw_error') for i, _ in bad}
            print(f'   after reboot: {after}  (torque is off; it comes back on at the next start)')
    return 0


def cmd_status(cfg, args):
    state = load_state()
    if not state:
        print('no teleop session')
        return 0
    print(f"session {state['session']} ({state['arm']} arm, started {state['started']})")
    for name, pgid in state.get('pgids', {}).items():
        print(f"   {name:8s} {'running' if alive(pgid) else 'stopped'}")
    log = os.path.join(state['session'], 'pose_log.csv')
    if os.path.exists(log):
        with open(log) as handle:
            lines = handle.read().splitlines()
        if len(lines) > 1:
            t, x, y, z = lines[-1].split(',')[:4]
            print(f'   last pose {t}: x {float(x):+.3f} y {float(y):+.3f} z {float(z):+.3f} m')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default=default_config())
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('scan', help='every OpenRB-150: role, motors, errors (read-only)')
    start = sub.add_parser('start', help='follower -> align -> leader -> viewer')
    start.add_argument('--arm', default='right')
    start.add_argument('--dry-run', action='store_true', help='check errors and the pose gap only')
    start.add_argument('--no-view', action='store_true')
    here = sub.add_parser('here', help='record the current tool position')
    here.add_argument('label', help='e.g. blue_round (a color prefix enables the wrist lid check)')
    here.add_argument('--arm', default='right', help='only used when no session is running')
    here.add_argument('--dry', action='store_true', help='print only, do not save')
    stop = sub.add_parser('stop', help='stop leader, follower, viewer (fold the arm first)')
    stop.add_argument('--force', action='store_true')
    tap = sub.add_parser('tap', help='follower only: hover, touch (x, y, z), lift, return to the start pose, stop')
    tap.add_argument('--arm', default='right')
    tap.add_argument('--x', type=float, required=True, help='arm base frame, m')
    tap.add_argument('--y', type=float, required=True)
    tap.add_argument('--z', type=float, required=True, help='lowest tool height, m')
    tap.add_argument('--hover', type=float, default=0.05, help='approach height above z, m')
    tap.add_argument('--allow-below-safe', action='store_true', help='allow z below safe_z_min_m')
    tap.add_argument('--record', action='store_true', help='save top.mp4 and wrist.mp4 in the session folder')
    tap.add_argument('--dry-run', action='store_true', help='print the plan only')
    pick = sub.add_parser('pick', help='follower only: pick at (x, y, z), place at (place x, y, z), return, stop')
    pick.add_argument('--arm', default='right')
    for key in ('x', 'y', 'z', 'place-x', 'place-y', 'place-z'):
        pick.add_argument(f'--{key}', type=float, required=True, help='arm base frame, m (z: tool height)')
    pick.add_argument('--hover', type=float, default=0.05, help='approach height above each point, m')
    pick.add_argument('--yaw', type=float, help='finger closing direction, deg in the arm base frame (default: joint5 0)')
    pick.add_argument('--place-yaw', type=float, help='closing direction at the place, deg (default: --yaw)')
    pick.add_argument('--allow-below-safe', action='store_true', help='allow z below safe_z_min_m')
    pick.add_argument('--record', action='store_true', help='save top.mp4 and wrist.mp4 in the session folder')
    pick.add_argument('--dry-run', action='store_true', help='print the plan only')
    cam = sub.add_parser('camera', help='fixed exposure / white balance: --tune to measure and save, else apply')
    cam.add_argument('--tune', action='store_true', help='measure with the scene lit as usual, then save')
    cam.add_argument('--only', nargs='+', help='camera names: top, right_wrist, left_wrist')
    clear = sub.add_parser('clear-errors', help='reboot motors that report a hardware error')
    clear.add_argument('--arm', default='right')
    sub.add_parser('status')
    args = parser.parse_args(argv)
    with open(args.config) as handle:
        cfg = yaml.safe_load(handle)
    os.environ['ROS_DOMAIN_ID'] = str(cfg['ros_domain_id'])
    commands = {'scan': cmd_scan, 'start': cmd_start, 'here': cmd_here, 'stop': cmd_stop, 'tap': cmd_tap, 'pick': cmd_pick, 'camera': cmd_camera,
                'clear-errors': cmd_clear_errors, 'status': cmd_status}
    return commands[args.command](cfg, args)


if __name__ == '__main__':
    sys.exit(main())
