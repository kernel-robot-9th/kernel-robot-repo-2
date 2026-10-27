# [②] 관제 대신 FollowPath 를 보내 보는 테스트 클라이언트
# 그림 좌표(cm, 왼쪽아래 원점) 꼭짓점들을 직선으로 잇고 촘촘히 나눠 map 프레임 경로로 보낸다.
# 좌표는 기본으로 **라이다 중심** 위치다 (--ref lidar). Nav2 는 바퀴 축(base_footprint, 라이다보다 1.7cm 앞)을 따라가므로
# 각 점을 진행 방향으로 1.7cm 옮겨서 보낸다. 바퀴 축 좌표를 직접 주려면 --ref axle.
#   python3 follow_path_client.py --dry-run 105,150 105,180          # 경로만 출력 (로봇 안 움직임)
#   python3 follow_path_client.py --final-heading 90 105,150 105,180  # 실제 전송 (로봇이 움직임!)
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coords import user_to_map  # noqa: E402

LIDAR_BEHIND_AXLE = 0.017  # m, URDF rplidar_mount x = -0.017 (base_link 기준)


def densify(pts, step_cm):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / step_cm)))
        out += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(1, n + 1)]
    return out


def build_poses(pts, final_heading, ref='lidar'):
    poses = []
    for i, (x, y) in enumerate(pts):
        if i + 1 < len(pts):
            h = math.degrees(math.atan2(pts[i + 1][1] - y, pts[i + 1][0] - x))
        elif final_heading is not None:
            h = final_heading
        else:
            h = math.degrees(math.atan2(y - pts[i - 1][1], x - pts[i - 1][0]))
        mx, my, yaw = user_to_map(x, y, h)
        if ref == 'lidar':  # 라이다 중심 -> 바퀴 축
            mx, my = mx + LIDAR_BEHIND_AXLE * math.cos(yaw), my + LIDAR_BEHIND_AXLE * math.sin(yaw)
        poses.append((mx, my, yaw))
    return poses


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('points', nargs='+', help='x,y (cm) 꼭짓점들')
    ap.add_argument('--step', type=float, default=2.0, help='경로 점 간격 cm')
    ap.add_argument('--final-heading', type=float, default=None, help='마지막 자세 heading (deg, 사용자 좌표)')
    ap.add_argument('--namespace', default='')
    ap.add_argument('--ref', choices=['lidar', 'axle'], default='lidar', help='좌표 기준점 (기본: 라이다 중심)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    pts = [tuple(map(float, p.split(','))) for p in a.points]
    poses = build_poses(densify(pts, a.step), a.final_heading, a.ref)
    print(f'{len(poses)} poses, start map=({poses[0][0]:.3f}, {poses[0][1]:.3f}) '
          f'end map=({poses[-1][0]:.3f}, {poses[-1][1]:.3f}, yaw {math.degrees(poses[-1][2]):.1f}deg)')
    if a.dry_run:
        return

    import rclpy
    from geometry_msgs.msg import PoseStamped
    from nav_msgs.msg import Path
    from nav2_msgs.action import FollowPath
    from rclpy.action import ActionClient

    rclpy.init()
    node = rclpy.create_node('follow_path_client')
    action = (a.namespace.rstrip('/') + '/follow_path') if a.namespace else 'follow_path'
    client = ActionClient(node, FollowPath, action)
    if not client.wait_for_server(timeout_sec=5.0):
        print(f'{action} 액션 서버 없음'); return
    path = Path()
    path.header.frame_id = 'map'
    path.header.stamp = node.get_clock().now().to_msg()
    for x, y, yaw in poses:
        p = PoseStamped(); p.header = path.header
        p.pose.position.x, p.pose.position.y = x, y
        p.pose.orientation.z, p.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        path.poses.append(p)
    goal = FollowPath.Goal(path=path, controller_id='FollowPath', goal_checker_id='general_goal_checker',
                           progress_checker_id='progress_checker')
    fut = client.send_goal_async(goal, feedback_callback=lambda f: print(
        f'  남은 거리 {f.feedback.distance_to_goal:.2f} m, 속도 {f.feedback.speed:.2f} m/s', end='\r'))
    rclpy.spin_until_future_complete(node, fut)
    gh = fut.result()
    if not gh.accepted:
        print('거부됨'); return
    res = gh.get_result_async()
    try:
        rclpy.spin_until_future_complete(node, res)
        r = res.result()
        print(f'\n결과 status={r.status} error_code={r.result.error_code}')
    except KeyboardInterrupt:
        print('\n취소 요청'); rclpy.spin_until_future_complete(node, gh.cancel_goal_async())
    rclpy.shutdown()


if __name__ == '__main__':
    main()
