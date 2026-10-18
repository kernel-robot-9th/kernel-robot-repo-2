"""Preflight check for the OMX arms: clear latched errors, then verify every motor answers.

Usage: python clear_motor_errors.py [--reboot-all] [port ...]
  no args      check all four arms (followers and leaders)
  --reboot-all reboot every motor on the listed ports first (like Downloads/omx_reboot.py),
               even the ones that look healthy

Motors that report a hardware error, and buses with missing motors, get rebooted and
re-checked. Torque ends up off on a rebooted motor, so the arm may sag.
Exits non-zero with a diagnosis if a motor is still missing or undervolted, so that
record_bi.sh / teleop_bi.sh stop here instead of failing later inside lerobot.
"""
import sys
import time

import dynamixel_sdk as dxl

BAUDRATE = 1_000_000
ERRORS = {1: "input voltage", 4: "overheating", 8: "encoder", 16: "electrical shock", 32: "overload"}
# Followers are XL430 (11-13, 12 V rail) + XL330 (14-16, regulated 5 V rail); leaders are all XL330.
FOLLOWER_IDS = list(range(11, 17))
LEADER_IDS = list(range(1, 7))
ARMS = {
    "/dev/omx_follower": FOLLOWER_IDS,
    "/dev/omx_follower_left": FOLLOWER_IDS,
    "/dev/omx_leader": LEADER_IDS,
    "/dev/omx_leader_left": LEADER_IDS,
}
ADDR_HW_ERROR = 70
ADDR_VOLTAGE = 144
# Minimum sane Present_Input_Voltage per model. XL430 followers run off 12 V; XL330 runs off the
# follower's regulated ~6 V rail or, on the leaders, USB logic power (~4.3 V) -- datasheet min 3.7 V.
MIN_VOLT = {1060: 9.5, 1200: 3.6, 1190: 3.6}
REBOOT_WAIT_S = 2.5
MAX_ATTEMPTS = 2


def scan(pk, ph, ids):
    """Return {motor_id: (model, hardware_error, voltage)} for the motors that answer."""
    state = {}
    for motor_id in ids:
        model, comm, _ = pk.ping(ph, motor_id)
        if comm != dxl.COMM_SUCCESS or not model:
            continue
        err = pk.read1ByteTxRx(ph, motor_id, ADDR_HW_ERROR)[0]
        volt = pk.read2ByteTxRx(ph, motor_id, ADDR_VOLTAGE)[0] / 10
        state[motor_id] = (model, err, volt)
    return state


def check_arm(port, ids, reboot_all=False):
    """Check one bus. Returns a list of problem strings (empty = healthy)."""
    ph = dxl.PortHandler(port)
    if not ph.openPort():
        return [f"cannot open {port} (board unplugged? udev rule missing? another process holding it?)"]
    if not ph.setBaudRate(BAUDRATE):
        ph.closePort()
        return [f"cannot set {BAUDRATE} baud on {port}"]
    pk = dxl.PacketHandler(2.0)

    try:
        if reboot_all:
            print(f"{port}: rebooting all of {ids}")
            for motor_id in ids:
                pk.reboot(ph, motor_id)
            time.sleep(REBOOT_WAIT_S)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            state = scan(pk, ph, ids)
            missing = [i for i in ids if i not in state]
            errored = [i for i, (_, err, _) in state.items() if err]
            undervolt = [
                i for i, (model, _, volt) in state.items()
                if model in MIN_VOLT and volt < MIN_VOLT[model]
            ]
            volts = " ".join(f"{i}:{v:.1f}V" for i, (_, _, v) in sorted(state.items()))
            if not missing and not errored and not undervolt:
                print(f"{port}: OK  {volts}", flush=True)
                return []
            # A reboot cannot raise the supply voltage, so undervoltage alone is reported as is.
            if attempt == MAX_ATTEMPTS or not (missing or errored):
                break
            # Reboot the motors that latched an error. If some motors are missing entirely the
            # bus may have been interrupted mid-transaction, so reboot the whole chain.
            targets = ids if missing else errored
            for motor_id in errored:
                names = [n for bit, n in ERRORS.items() if state[motor_id][1] & bit]
                print(f"{port} id {motor_id}: {names} -> reboot", flush=True)
            if missing:
                print(f"{port}: missing {missing} -> rebooting whole chain", flush=True)
            for motor_id in targets:
                pk.reboot(ph, motor_id)
            time.sleep(REBOOT_WAIT_S)

        problems = []
        for motor_id in sorted(state):
            model, err, volt = state[motor_id]
            floor = MIN_VOLT.get(model)
            low = floor is not None and volt < floor
            if low:
                # The undervoltage line explains an input-voltage error, so don't report both.
                problems.append(
                    f"{port} id {motor_id}: undervoltage {volt:.1f}V (model {model} needs >{floor}V)"
                )
            if err and not (low and err == 1):
                names = [n for bit, n in ERRORS.items() if err & bit]
                problems.append(f"{port} id {motor_id}: error still latched: {names} ({volt:.1f}V)")
        if missing:
            problems.append(f"{port}: no response from motor ids {missing}")
        return problems
    finally:
        ph.closePort()


def main():
    args = sys.argv[1:]
    reboot_all = "--reboot-all" in args
    ports = [a for a in args if not a.startswith("-")]
    arms = {p: ARMS.get(p, FOLLOWER_IDS) for p in ports} if ports else ARMS

    problems = []
    for port, ids in arms.items():
        problems += check_arm(port, ids, reboot_all)

    if not problems:
        print("all arms ready")
        return 0

    sys.stdout.flush()
    print("\n=== 모터 점검 실패 / motor preflight failed ===", file=sys.stderr)
    for p in problems:
        print("  - " + p, file=sys.stderr)
    if any("undervoltage" in p or "input voltage" in p or "no response" in p for p in problems):
        print(
            "\n전원을 먼저 확인하세요 / check power first:\n"
            "  1. 해당 팔의 12V 아답터가 꽂혀 있고 멀티탭 스위치가 켜져 있는지\n"
            "     (12V adapter plugged in, power strip switched on)\n"
            "  2. OpenRB-150 보드의 전원 LED\n"
            "  3. 13번 -> 14번 사이 데이지체인 케이블 (wrist motors sit after id 13)\n"
            "  ~4V 만 보이면 USB 로직 전원만 들어온 상태입니다 — 12V 가 아예 없습니다.\n"
            "     (reading ~4V means only USB logic power is present, the 12V rail is dead)",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
