# 정밀 주차 기준 자세 저장: 이상적인 자리(마커 앞)에서 마커를 N장 찍어 평균 → aruco_ref.json
# 카메라: OV5647 (picamera2), 1296x972 전체 화각. 영상은 위아래·좌우가 뒤집혀(180° 회전) 들어온다 (2026-10-22 확인).
# 보정값이 없어 초점거리는 사양값(fx≈1286px)을 라이다·odom 이동으로 맞춘 1169px 를 쓴다 (좌우 값은 fx 와 무관).
#   python3 aruco_ref.py            # 기준 저장
#   python3 aruco_ref.py --check    # 저장하지 않고 지금 값과 기준의 차이만 출력
import json, math, os, sys, time
import cv2, numpy as np
from picamera2 import Picamera2

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1296, 972
FX = 1169.0  # px. 사양값 1286 으로는 앞뒤 거리 차이가 10% 크게 나옴 → 라이다·odom 5cm 후진으로 맞춤 (2026-10-22)
K = np.array([[FX, 0, W / 2], [0, FX, H / 2], [0, 0, 1]])
DIST = np.zeros(5)
DICT, MARKER_ID, SIZE = 'DICT_4X4_50', 2, 0.017   # 한 변 1.7cm
OBJ = np.array([[-SIZE / 2, SIZE / 2, 0], [SIZE / 2, SIZE / 2, 0], [SIZE / 2, -SIZE / 2, 0], [-SIZE / 2, -SIZE / 2, 0]], np.float32)


def robot_pose(rvec, tvec):
    """영상 180° 회전 반영. 반환: 마커까지 앞 거리 z, 마커가 로봇 왼쪽으로 떨어진 x_left (m), 마커 면이 로봇 정면과 이루는 각 yaw (deg)"""
    R, _ = cv2.Rodrigues(rvec)
    x, y, z = tvec.ravel()
    x_left = x          # 원래 카메라 x 는 영상 오른쪽 = 180° 회전이므로 로봇 왼쪽
    n = R[:, 2]         # 마커 면 법선 (카메라 좌표)
    yaw = math.degrees(math.atan2(n[0], -n[2]))   # 정면으로 마주 보면 0
    return dict(z=float(z), x_left=float(x_left), yaw=float(yaw))


def capture(n=20):
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICT)), cv2.aruco.DetectorParameters())
    cam = Picamera2()
    cam.configure(cam.create_still_configuration(main={"size": (W, H), "format": "RGB888"}))
    cam.start(); time.sleep(1.5)
    C, img = [], None
    for _ in range(n):
        img = cam.capture_array()
        c, ids, _ = det.detectMarkers(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if ids is not None and MARKER_ID in ids.ravel():
            C.append(c[list(ids.ravel()).index(MARKER_ID)][0])
    cam.stop(); cam.close()
    return np.array(C), img


def solve(corners):
    ok, rvec, tvec = cv2.solvePnP(OBJ, corners.astype(np.float32), K, DIST, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    return rvec, tvec


if __name__ == '__main__':
    C, img = capture()
    if len(C) == 0:
        print('마커 못 찾음'); sys.exit(1)
    mc = C.mean(0); jit = C.std(0).max()
    rvec, tvec = solve(mc); p = robot_pose(rvec, tvec)
    side = float(np.mean([np.linalg.norm(mc[k] - mc[(k + 1) % 4]) for k in range(4)]))
    print(f'인식 {len(C)}장, 모서리 흔들림 최대 {jit:.2f}px, 중심 ({mc[:, 0].mean():.1f}, {mc[:, 1].mean():.1f}) px, 한 변 {side:.1f}px')
    print(f'마커까지 앞 {100 * p["z"]:.2f}cm, 마커가 왼쪽으로 {100 * p["x_left"]:+.2f}cm, 마커 면 각도 {p["yaw"]:+.1f}°')
    path = os.path.join(HERE, 'aruco_ref.json')
    if '--check' in sys.argv:
        r = json.load(open(path))
        print(f'기준 대비: 앞 {100 * (p["z"] - r["pose"]["z"]):+.2f}cm, 왼 {100 * (p["x_left"] - r["pose"]["x_left"]):+.2f}cm, 각 {p["yaw"] - r["pose"]["yaw"]:+.1f}°, '
              f'중심 {mc[:, 0].mean() - np.mean(np.array(r["corners"])[:, 0]):+.1f}/{mc[:, 1].mean() - np.mean(np.array(r["corners"])[:, 1]):+.1f}px')
    else:
        json.dump(dict(time=time.strftime('%Y-%m-%d %H:%M:%S'), dict=DICT, id=MARKER_ID, size_m=SIZE, image_wh=[W, H], K=K.tolist(),
                       rotated_180=True, corners=mc.tolist(), corner_jitter_px=float(jit), n=len(C), side_px=side,
                       rvec=rvec.ravel().tolist(), tvec=tvec.ravel().tolist(), pose=p), open(path, 'w'), indent=1)
        cv2.imwrite(os.path.join(HERE, 'aruco_ref.png'), img)
        print('저장', path)
