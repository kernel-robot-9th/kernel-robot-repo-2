# 제자리 회전 시간 재기: lane_drive.Driver.rotate 로 정해 둔 방향들을 차례로 돌며 (각도, 시간, 끝 오차)를 기록
# **로봇에서** 실행. 로봇이 제자리에서 돎 (주변 15 cm 비울 것)
#   python3 rot_test.py                         # 기본 순서: +90 ×4, -90 ×4, +180 ×2, -180 ×2 (지금 방향 기준)
#   python3 rot_test.py --seq 90,90,-180,180    # 상대 각도 순서 직접
#   python3 rot_test.py --wmax 1.0 --settle 0.3 # 더 빠르게 시험
# 결과: edge_logs/rot_<시각>.csv (rot_deg, rot_s, end_err_deg) — edge_costs 는 edges_*.csv 만 읽으므로 따로 봄
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rclpy  # noqa: E402
from lane_drive import ROT_SETTLE, ROT_WMAX, Driver  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seq', default='90,90,90,90,-90,-90,-90,-90,180,180,-180,-180')
    ap.add_argument('--wmax', type=float, default=ROT_WMAX, help='최대 각속도 rad/s')
    ap.add_argument('--settle', type=float, default=ROT_SETTLE, help='회전 앞뒤 AMCL 대기 s')
    a = ap.parse_args()
    rclpy.init()
    dr = Driver()
    os.makedirs(os.path.join(HERE, 'edge_logs'), exist_ok=True)
    path = os.path.join(HERE, 'edge_logs', time.strftime('rot_%m%d_%H%M%S.csv'))
    f = open(path, 'w')
    f.write('i,rot_deg,rot_s,status,end_err_deg,wmax,settle\n')
    try:
        for i, d in enumerate(float(x) for x in a.seq.split(',')):
            th0 = math.degrees(dr.pose()[2])
            tgt = (th0 + d) % 360
            tgt = round(tgt / 90) * 90 % 360          # 축 방향(0/90/180/270)으로 맞춤
            rot = (tgt - th0 + 180) % 360 - 180
            t0 = time.time()
            st = dr.rotate(tgt, wmax=a.wmax, settle=a.settle)
            dt = time.time() - t0
            err = (math.degrees(dr.pose()[2]) - tgt + 180) % 360 - 180
            f.write(f'{i + 1},{rot:.1f},{dt:.2f},{st},{err:.1f},{a.wmax},{a.settle}\n'); f.flush()
            print(f'{i + 1:2d}  회전 {rot:+7.1f}°  {dt:5.1f} s  {st}  끝 오차 {err:+.1f}°', flush=True)
            if st != 'ok':
                break
    finally:
        dr.stop(); f.close()
        print(f'저장: {path}')
        dr.n.destroy_node(); rclpy.shutdown()


if __name__ == '__main__':
    main()
