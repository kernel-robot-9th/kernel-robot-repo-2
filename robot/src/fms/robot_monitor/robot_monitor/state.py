"""Latest known state of one robot, and how it turns into the JSON the monitor sends.

Pure Python (no ROS) so the rules can be tested alone. Times are seconds from time.monotonic().
"""
import math
from dataclasses import dataclass, field

# action_msgs/msg/GoalStatus values
STATUS_ACCEPTED, STATUS_EXECUTING, STATUS_CANCELING = 1, 2, 3
STATUS_SUCCEEDED, STATUS_CANCELED, STATUS_ABORTED = 4, 5, 6
ACTIVE_STATUSES = {STATUS_ACCEPTED, STATUS_EXECUTING, STATUS_CANCELING}
RESULT_NAMES = {STATUS_SUCCEEDED: 'succeeded', STATUS_CANCELED: 'canceled', STATUS_ABORTED: 'aborted'}


def yaw_from_quaternion(x, y, z, w):
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


@dataclass
class RobotState:
    name: str
    namespace: str = ''
    emr_robot_id: int | None = None
    pose: tuple | None = None            # (x_m, y_m, yaw_rad) in the map frame
    pose_time: float | None = None
    velocity: tuple | None = None        # (linear_mps, angular_radps) from odom
    last_seen: float | None = None       # any message from the robot
    battery_percent: float | None = None
    battery_voltage_v: float | None = None
    battery_time: float | None = None
    nav_active: bool = False
    nav_last_result: str | None = None
    nav_result_time: float | None = None
    _finished_goals: set = field(default_factory=set, repr=False)

    def seen(self, now):
        self.last_seen = now

    def update_nav(self, statuses, now):
        """statuses: list of (goal_id bytes, status int) from navigate_to_pose/_action/status."""
        self.nav_active = any(status in ACTIVE_STATUSES for _, status in statuses)
        for goal_id, status in statuses:
            if status in RESULT_NAMES and goal_id not in self._finished_goals:
                self._finished_goals.add(goal_id)
                self.nav_last_result = RESULT_NAMES[status]
                self.nav_result_time = now
        if len(self._finished_goals) > 200:   # status lists are short; keep memory bounded
            self._finished_goals = {goal_id for goal_id, _ in statuses}

    def to_dict(self, now, offline_after_s=3.0, battery_low_percent=20.0):
        def age(stamp):
            return None if stamp is None else round(now - stamp, 2)

        online = self.last_seen is not None and now - self.last_seen <= offline_after_s
        state = 'offline' if not online else ('navigating' if self.nav_active else 'idle')
        return {
            'name': self.name,
            'namespace': self.namespace or '/',
            'emr_robot_id': self.emr_robot_id,
            'online': online,
            'state': state,
            'pose': None if self.pose is None else {
                'x_m': round(self.pose[0], 3), 'y_m': round(self.pose[1], 3), 'yaw_rad': round(self.pose[2], 3),
                'age_s': age(self.pose_time)},
            'velocity': None if self.velocity is None else {
                'linear_mps': round(self.velocity[0], 3), 'angular_radps': round(self.velocity[1], 3)},
            'battery': None if self.battery_percent is None and self.battery_voltage_v is None else {
                'percent': self.battery_percent, 'voltage_v': self.battery_voltage_v,
                'low': self.battery_percent is not None and self.battery_percent < battery_low_percent,
                'age_s': age(self.battery_time)},
            'navigation': {'active': self.nav_active, 'last_result': self.nav_last_result,
                           'last_result_age_s': age(self.nav_result_time)},
            'last_seen_age_s': age(self.last_seen),
        }
