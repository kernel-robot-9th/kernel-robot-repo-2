"""Robot monitor: subscribes to every configured robot and sends out their latest state.

Per robot (topics under its namespace, '' = root):
  battery/percent, battery/voltage    std_msgs/Float32 (pinky_bringup battery_publisher)
  odom                                nav_msgs/Odometry -> speed, and "the robot is alive"
  tf, tf_static                       pose = map -> base_footprint
  navigate_to_pose/_action/status     action_msgs/GoalStatusArray -> navigating, last result
Sends:
  HTTP  GET /api/robots, GET /api/robots/<name>, GET /api/robots/stream (Server-Sent Events, 1 s)
  ROS   /fms/robot_states  std_msgs/String (JSON, same body as GET /api/robots), 1 s

  ros2 run robot_monitor monitor                       # installed config/robots.yaml
  ros2 run robot_monitor monitor --config my_robots.yaml
"""
import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
import rclpy.executors
import yaml
from action_msgs.msg import GoalStatusArray
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from rclpy.time import Time
from std_msgs.msg import Float32, String
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer

from robot_monitor.state import RobotState, yaw_from_quaternion

LATCHED = QoSProfile(history=QoSHistoryPolicy.KEEP_LAST, depth=1, reliability=QoSReliabilityPolicy.RELIABLE,
                     durability=QoSDurabilityPolicy.TRANSIENT_LOCAL)
TF_STATIC = QoSProfile(history=QoSHistoryPolicy.KEEP_LAST, depth=100, reliability=QoSReliabilityPolicy.RELIABLE,
                       durability=QoSDurabilityPolicy.TRANSIENT_LOCAL)


def topic(namespace, name):
    namespace = namespace.strip('/')
    return f'/{namespace}/{name}' if namespace else f'/{name}'


class RobotMonitor(Node):

    def __init__(self, config):
        super().__init__('robot_monitor')
        self.config = config
        self.map_frame = config.get('map_frame', 'map')
        self.base_frame = config.get('base_frame', 'base_footprint')
        self.offline_after_s = float(config.get('offline_after_s', 3.0))
        self.battery_low_percent = float(config.get('battery_low_percent', 20.0))
        self.lock = threading.Lock()
        self.robots = {}
        self.tf_buffers = {}
        self.tf_stamps = {}
        for name, entry in config['robots'].items():
            entry = entry or {}
            namespace = entry.get('namespace', '')
            self.robots[name] = RobotState(name=name, namespace=namespace, emr_robot_id=entry.get('emr_robot_id'))
            self.tf_buffers[name] = Buffer()
            self._subscribe(name, namespace)
        self.states_pub = self.create_publisher(String, '/fms/robot_states', 10)
        self.create_timer(0.2, self._update_poses)
        self.create_timer(float(config.get('publish_period_s', 1.0)), self._publish)
        self.get_logger().info(f'monitoring {", ".join(f"{n} (ns {s.namespace or "/"})" for n, s in self.robots.items())}')

    # ------------------------------------------------------------------ subscriptions
    def _subscribe(self, name, namespace):
        def on_battery_percent(message):
            self._update(name, battery_percent=float(message.data), battery_time=True)

        def on_battery_voltage(message):
            self._update(name, battery_voltage_v=float(message.data), battery_time=True)

        def on_odom(message):
            twist = message.twist.twist
            self._update(name, velocity=(twist.linear.x, twist.angular.z))

        def on_tf(message, static=False):
            buffer = self.tf_buffers[name]
            for transform in message.transforms:
                if static:
                    buffer.set_transform_static(transform, 'robot_monitor')
                else:
                    buffer.set_transform(transform, 'robot_monitor')

        def on_nav_status(message):
            statuses = [(bytes(item.goal_info.goal_id.uuid), item.status) for item in message.status_list]
            now = time.monotonic()
            with self.lock:
                self.robots[name].update_nav(statuses, now)
                self.robots[name].seen(now)

        self.create_subscription(Float32, topic(namespace, 'battery/percent'), on_battery_percent, 10)
        self.create_subscription(Float32, topic(namespace, 'battery/voltage'), on_battery_voltage, 10)
        self.create_subscription(Odometry, topic(namespace, 'odom'), on_odom, 10)
        self.create_subscription(TFMessage, topic(namespace, 'tf'), on_tf, 100)
        self.create_subscription(TFMessage, topic(namespace, 'tf_static'), lambda m: on_tf(m, static=True), TF_STATIC)
        self.create_subscription(GoalStatusArray, topic(namespace, 'navigate_to_pose/_action/status'),
                                 on_nav_status, LATCHED)

    def _update(self, name, battery_time=False, **fields):
        now = time.monotonic()
        with self.lock:
            state = self.robots[name]
            for key, value in fields.items():
                setattr(state, key, value)
            if battery_time:
                state.battery_time = now
            state.seen(now)

    def _update_poses(self):
        for name, buffer in self.tf_buffers.items():
            try:
                transform = buffer.lookup_transform(self.map_frame, self.base_frame, Time())
            except Exception:  # noqa: BLE001 - no map yet, or TF not complete
                continue
            translation, rotation = transform.transform.translation, transform.transform.rotation
            pose = (translation.x, translation.y, yaw_from_quaternion(rotation.x, rotation.y, rotation.z, rotation.w))
            stamp = (transform.header.stamp.sec, transform.header.stamp.nanosec)
            with self.lock:
                state = self.robots[name]
                state.pose = pose
                if self.tf_stamps.get(name) != stamp:   # TF advanced: the pose is fresh even if the robot stands still
                    self.tf_stamps[name] = stamp
                    state.pose_time = time.monotonic()

    # ------------------------------------------------------------------ output
    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            robots = [state.to_dict(now, self.offline_after_s, self.battery_low_percent)
                      for state in self.robots.values()]
        return {'stamp': time.time(), 'robots': robots}

    def _publish(self):
        self.states_pub.publish(String(data=json.dumps(self.snapshot(), ensure_ascii=False)))


def make_http_server(monitor, host, port, stream_period_s=1.0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, status, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split('?', 1)[0].rstrip('/')
            if path == '/api/robots':
                return self._json(200, monitor.snapshot())
            if path == '/api/robots/stream':
                return self._stream()
            if path.startswith('/api/robots/'):
                name = path.rsplit('/', 1)[1]
                robot = next((r for r in monitor.snapshot()['robots'] if r['name'] == name), None)
                if robot is None:
                    return self._json(404, {'code': 'robot_not_found', 'detail': f'robot {name} is not monitored'})
                return self._json(200, robot)
            self._json(404, {'code': 'not_found', 'detail': path})

        def _stream(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                while True:
                    payload = json.dumps(monitor.snapshot(), ensure_ascii=False)
                    self.wfile.write(f'event: robots\ndata: {payload}\n\n'.encode())
                    self.wfile.flush()
                    time.sleep(stream_period_s)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def default_config():
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(get_package_share_directory('robot_monitor'), 'config', 'robots.yaml')
    except Exception:  # noqa: BLE001 - running from the source tree
        return os.path.join(os.path.dirname(__file__), '..', 'config', 'robots.yaml')


def main(argv=None):
    argv = rclpy.utilities.remove_ros_args(argv or sys.argv)[1:]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default=os.environ.get('ROBOT_MONITOR_CONFIG', default_config()))
    args = parser.parse_args(argv)
    with open(args.config) as handle:
        config = yaml.safe_load(handle) or {}
    if not config.get('robots'):
        raise SystemExit(f'{args.config}: no robots configured')

    rclpy.init()
    monitor = RobotMonitor(config)
    http = config.get('http', {}) or {}
    host, port = http.get('host', '0.0.0.0'), int(http.get('port', 8090))
    server = make_http_server(monitor, host, port, float(config.get('publish_period_s', 1.0)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monitor.get_logger().info(f'HTTP http://{host}:{port}/api/robots (stream: /api/robots/stream)')
    try:
        rclpy.spin(monitor)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        server.shutdown()
        monitor.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
