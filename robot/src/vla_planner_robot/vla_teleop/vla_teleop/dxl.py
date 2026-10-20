"""Direct Dynamixel access for the OMX arms (no ROS): find ports, read state, clear hardware errors.

Only reads, except reboot_motors(), which clears a motor's hardware error (torque stays off,
the arm does not move). Never call these while a ros2_control node owns the same port.
"""
import glob
import math
import os

from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

BAUD = 1000000
FOLLOWER_IDS = list(range(11, 17))    # OMX-F: joint1..5 + gripper
LEADER_IDS = list(range(1, 7))        # OMX-L
ADDR = {'torque': 64, 'hw_error': 70, 'position': 132, 'voltage': 144, 'temperature': 146}
ERROR_BITS = {0: 'input voltage', 2: 'overheating', 3: 'motor encoder', 4: 'electrical shock', 5: 'overload'}
MODELS = {1060: 'XL430-W250', 1200: 'XL330-M288', 1190: 'XL330-M077'}


def port_path(serial):
    """[입력] OpenRB-150 USB serial prefix [출력] /dev/serial/by-id path (raises if not plugged in)"""
    matches = glob.glob(f'/dev/serial/by-id/*OpenRB-150_{serial}*')
    if not matches:
        raise FileNotFoundError(f'OpenRB-150 {serial} is not connected')
    return matches[0]


def raw_to_rad(raw):
    """Present Position (0..4095, 2048 = 0 rad) -> radians, the convention of the ROBOTIS hardware interface."""
    return (raw - 2048) * 2.0 * math.pi / 4096.0


def error_names(code):
    return [name for bit, name in ERROR_BITS.items() if code & (1 << bit)]


class Bus:
    def __init__(self, serial):
        self.path = port_path(serial)
        self.port = PortHandler(self.path)
        if not self.port.openPort() or not self.port.setBaudRate(BAUD):
            raise OSError(f'cannot open {self.path} (is a ros2_control node using it?)')
        self.packet = PacketHandler(2.0)

    def close(self):
        self.port.closePort()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def read(self, dxl_id, name):
        size = {'torque': 1, 'hw_error': 1, 'temperature': 1, 'voltage': 2, 'position': 4}[name]
        reader = {1: self.packet.read1ByteTxRx, 2: self.packet.read2ByteTxRx, 4: self.packet.read4ByteTxRx}[size]
        value, result, _ = reader(self.port, dxl_id, ADDR[name])
        return value if result == COMM_SUCCESS else None

    def motor(self, dxl_id):
        model, result, _ = self.packet.ping(self.port, dxl_id)
        if result != COMM_SUCCESS:
            return None
        voltage = self.read(dxl_id, 'voltage')
        return {'id': dxl_id, 'model': MODELS.get(model, str(model)), 'position_raw': self.read(dxl_id, 'position'),
                'hw_error': self.read(dxl_id, 'hw_error'), 'torque': bool(self.read(dxl_id, 'torque')),
                'voltage_v': None if voltage is None else voltage / 10.0, 'temperature_c': self.read(dxl_id, 'temperature')}

    def joints_rad(self, ids):
        values = [self.read(dxl_id, 'position') for dxl_id in ids]
        if None in values:
            raise IOError(f'{self.path}: could not read positions of {ids}')
        return [raw_to_rad(v) for v in values]

    def reboot(self, dxl_id):
        result, _ = self.packet.reboot(self.port, dxl_id)
        return result == COMM_SUCCESS


def scan_all():
    """[출력] list of (serial, port, role, motors) for every OpenRB-150 plugged in."""
    out = []
    for path in sorted(glob.glob('/dev/serial/by-id/*OpenRB-150_*')):
        serial = path.split('OpenRB-150_')[1][:8]
        with Bus(serial) as bus:
            followers = [m for m in (bus.motor(i) for i in FOLLOWER_IDS) if m]
            leaders = [m for m in (bus.motor(i) for i in LEADER_IDS) if m]
        role = 'follower' if followers else ('leader' if leaders else 'unknown')
        out.append((serial, os.path.realpath(path), role, followers or leaders))
    return out
