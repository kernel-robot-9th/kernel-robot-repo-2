"""Shared helpers for the calibration tools: ROS image I/O, param files, waiting."""
import os
import threading
import time

import numpy as np
import rclpy
import yaml
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter

DEFAULT_CALIB_DIR = os.path.expanduser('~/dev_ws/robot/calib')


class _NoAliasDumper(yaml.SafeDumper):
    """ROS 2's YAML param parser does not understand anchors/aliases (&id001 / *id001)."""

    def ignore_aliases(self, data):
        return True


def spin_in_background(node):
    ex = MultiThreadedExecutor(num_threads=4)
    ex.add_node(node)
    t = threading.Thread(target=ex.spin, daemon=True)
    t.start()
    return ex


def wait_for(pred, timeout, period=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(period)
    return None


def update_param_file(path, node_params):
    """Merge {node_name: {param: value}} into a ROS 2 params YAML (keeps other keys)."""
    data = {}
    if os.path.exists(path):
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    for node, params in node_params.items():
        section = data.setdefault(node, {}).setdefault('ros__parameters', {})
        for k, v in params.items():
            # 'hsv.red' -> nested {'hsv': {'red': ...}} like hand-written ROS yaml
            *parents, leaf = k.split('.')
            d = section
            for p in parents:
                d = d.setdefault(p, {})
            d[leaf] = v
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w') as f:
        yaml.dump(data, f, Dumper=_NoAliasDumper, sort_keys=False, default_flow_style=None)
    return path


def flatten_params(section, prefix=''):
    out = {}
    for k, v in section.items():
        key = f'{prefix}{k}'
        if isinstance(v, dict):
            out.update(flatten_params(v, key + '.'))
        else:
            out[key] = v
    return out


def param_overrides(paths, section_name):
    """Parameters from YAML files (section `section_name`) as rclpy overrides.

    Needed at node construction for values that shape the node (e.g. the executor's
    arm_names, which decide which arms and parameters exist)."""
    out = {}
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        section = (data.get(section_name) or {}).get('ros__parameters') or {}
        out.update(flatten_params(section))
    return [Parameter(k, value=v) for k, v in out.items()]


def apply_param_files(node, paths, section_name):
    """Set the node's already-declared parameters from YAML files (section `section_name`).

    Used so a tool behaves like the running node (same gripper/height settings)."""
    applied = []
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        section = (data.get(section_name) or {}).get('ros__parameters') or {}
        for k, v in flatten_params(section).items():
            if node.has_parameter(k):
                if isinstance(v, list) and v and isinstance(v[0], int) and \
                        isinstance(node.get_parameter(k).value, list) and \
                        node.get_parameter(k).value and isinstance(node.get_parameter(k).value[0], float):
                    v = [float(x) for x in v]
                node.set_parameters([Parameter(k, value=v)])
                applied.append(k)
    return applied


def to_list(a, nd=4):
    return [round(float(x), nd) for x in np.asarray(a).ravel()]
