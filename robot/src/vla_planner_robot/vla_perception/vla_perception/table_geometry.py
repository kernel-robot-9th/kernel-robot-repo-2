"""Pure-numpy/OpenCV helpers: marker homography, parallax correction, color blobs."""
import cv2
import numpy as np

DEFAULT_HSV = {
    # OpenCV HSV: H 0-179. Several ranges per color are concatenated (6 numbers each).
    'red': [0, 120, 70, 8, 255, 255, 170, 120, 70, 179, 255, 255],
    'green': [40, 100, 60, 85, 255, 255],
    'blue': [100, 120, 60, 130, 255, 255],
    'yellow': [20, 100, 100, 35, 255, 255],
    'purple': [125, 80, 60, 160, 255, 255],     # trays
}


def image_to_numpy(msg):
    """sensor_msgs/Image -> BGR uint8 array (no cv_bridge: avoids numpy ABI issues)."""
    buf = np.frombuffer(msg.data, dtype=np.uint8)
    enc = msg.encoding.lower()
    if enc in ('rgb8', 'bgr8'):
        img = buf.reshape(msg.height, msg.step)[:, :msg.width * 3].reshape(msg.height, msg.width, 3)
        return cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if enc == 'rgb8' else img.copy()
    if enc == 'mono8':
        img = buf.reshape(msg.height, msg.step)[:, :msg.width]
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if enc in ('yuv422_yuy2', 'yuyv'):
        img = buf.reshape(msg.height, msg.width, 2)
        return cv2.cvtColor(img, cv2.COLOR_YUV2BGR_YUYV)
    raise ValueError(f'unsupported encoding {msg.encoding}')


class Undistorter:
    """Maps raw pixel coordinates to ideal (undistorted) pixel coordinates."""

    def __init__(self, K=None, D=None):
        self.K = None if K is None else np.asarray(K, float).reshape(3, 3)
        self.D = None if D is None or not np.any(D) else np.asarray(D, float)

    def __call__(self, pts):
        pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
        if self.K is None or self.D is None:
            return pts.reshape(-1, 2)
        return cv2.undistortPoints(pts, self.K, self.D, P=self.K).reshape(-1, 2)


class TableHomography:
    """Pixel <-> table plane (robot base frame, z = 0) from >= 4 marker centers."""

    def __init__(self, img_pts, table_pts, K=None):
        img_pts = np.asarray(img_pts, np.float64)
        table_pts = np.asarray(table_pts, np.float64)
        self.H, _ = cv2.findHomography(img_pts, table_pts)           # pixel -> table
        self.H_inv = np.linalg.inv(self.H)                           # table -> pixel
        self.reproj_err = float(np.abs(self.to_table(img_pts) - table_pts).max())
        self.camera_center = self._camera_center(K) if K is not None else None

    def to_table(self, px):
        px = np.asarray(px, np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(px, self.H).reshape(-1, 2)

    def to_pixel(self, xy):
        xy = np.asarray(xy, np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(xy, self.H_inv).reshape(-1, 2)

    def _camera_center(self, K):
        """Camera position in the table frame from plane-to-image homography and intrinsics."""
        K = np.asarray(K, float).reshape(3, 3)
        M = np.linalg.inv(K) @ self.H_inv
        s = 2.0 / (np.linalg.norm(M[:, 0]) + np.linalg.norm(M[:, 1]))
        M = M * s
        if M[2, 2] < 0:          # the table must be in front of the camera
            M = -M
        r1, r2, t = M[:, 0], M[:, 1], M[:, 2]
        R = np.column_stack([r1, r2, np.cross(r1, r2)])
        U, _, Vt = np.linalg.svd(R)                                  # re-orthonormalize
        R = U @ Vt
        C = -R.T @ t
        return C if C[2] > 0 else None

    def correct_height(self, xy, h):
        """Table-plane hit point of a ray -> true xy of a point at height h on that ray."""
        if self.camera_center is None or h == 0.0:
            return np.asarray(xy, float)
        C = self.camera_center
        xy = np.asarray(xy, float)
        return C[:2] + (xy - C[:2]) * (C[2] - h) / C[2]


DEFAULT_ARUCO_DICT = 'DICT_5X5_100'
_detectors = {}


def aruco_dictionary_id(name):
    """'DICT_5X5_100' (or the cv2 constant itself) -> cv2.aruco dictionary id."""
    if isinstance(name, int):
        return name
    value = getattr(cv2.aruco, str(name).upper(), None)
    if not isinstance(value, int) or not str(name).upper().startswith('DICT_'):
        raise ValueError(f'unknown ArUco dictionary "{name}" (e.g. DICT_4X4_50, DICT_5X5_100)')
    return value


def detect_markers(bgr, dictionary=DEFAULT_ARUCO_DICT):
    key = aruco_dictionary_id(dictionary)
    if key not in _detectors:
        _detectors[key] = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(key),
                                                  cv2.aruco.DetectorParameters())
    corners, ids, _ = _detectors[key].detectMarkers(bgr)
    if ids is None:
        return {}
    return {int(i): c.reshape(4, 2) for i, c in zip(ids.ravel(), corners)}


def color_blobs(bgr, hsv_ranges, roi_mask=None, min_area=150, max_area=20000):
    """Return [(color, contour)] for every connected blob matching an HSV range."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    kernel = np.ones((5, 5), np.uint8)
    out = []
    for color, flat in hsv_ranges.items():
        mask = np.zeros(hsv.shape[:2], np.uint8)
        for k in range(0, len(flat), 6):
            lo = np.array(flat[k:k + 3], np.uint8)
            hi = np.array(flat[k + 3:k + 6], np.uint8)
            mask |= cv2.inRange(hsv, lo, hi)
        if roi_mask is not None:
            mask &= roi_mask
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            a = cv2.contourArea(c)
            if min_area <= a <= max_area:
                out.append((color, c))
    return out


def blob_pose_on_table(contour, homography, undistort, height):
    """Contour (pixels) -> pose of the object's top face in the table frame.

    Returns (x, y, yaw mod 90 deg, (long side, short side), long-axis yaw in [-pi/2, pi/2)).
    """
    pts = undistort(contour.reshape(-1, 2).astype(np.float64))
    xy = homography.to_table(pts)
    xy = homography.correct_height(xy, height)
    (cx, cy), (w, h), ang = cv2.minAreaRect((xy * 1000.0).astype(np.float32))   # mm for precision
    a = np.deg2rad(ang)
    yaw = (a + np.pi / 4) % (np.pi / 2) - np.pi / 4            # square block: yaw mod 90 deg
    long_yaw = a if w >= h else a + np.pi / 2                  # minAreaRect: w lies along `ang`
    long_yaw = (long_yaw + np.pi / 2) % np.pi - np.pi / 2
    return (cx / 1000.0, cy / 1000.0, float(yaw), (max(w, h) / 1000.0, min(w, h) / 1000.0),
            float(long_yaw))
