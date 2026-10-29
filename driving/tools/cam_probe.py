import time, cv2, numpy as np
from picamera2 import Picamera2
cam = Picamera2()
for (w, h) in [(1296, 972)]:
    cfg = cam.create_still_configuration(main={"size": (w, h), "format": "RGB888"})
    cam.configure(cfg); cam.start(); time.sleep(1.5)
    img = cam.capture_array(); cam.stop()
    cv2.imwrite(f"/home/pinky/aruco_probe_{w}.png", img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    print("frame", img.shape)
    for name in ["DICT_4X4_50", "DICT_4X4_250", "DICT_5X5_100", "DICT_6X6_250", "DICT_7X7_250", "DICT_ARUCO_ORIGINAL", "DICT_APRILTAG_36h11"]:
        det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name)), cv2.aruco.DetectorParameters())
        c, ids, rej = det.detectMarkers(gray)
        if ids is not None:
            for cc, i in zip(c, ids.ravel()):
                p = cc[0]; side = np.mean([np.linalg.norm(p[k] - p[(k + 1) % 4]) for k in range(4)])
                print(f"  {name}: id {i}, 중심 ({p[:,0].mean():.1f}, {p[:,1].mean():.1f}) px, 한 변 {side:.1f} px, 모서리 {np.round(p,1).tolist()}")
cam.close()
