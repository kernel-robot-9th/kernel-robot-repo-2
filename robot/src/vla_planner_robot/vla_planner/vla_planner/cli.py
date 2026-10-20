#!/usr/bin/env python3
"""Interactive prompt: type a command (Korean/English), it is sent to /execute_command."""
import sys

import rclpy
from rclpy.action import ActionClient

from vla_interfaces.action import ExecuteCommand


def main():
    rclpy.init()
    node = rclpy.create_node('vla_cli')
    client = ActionClient(node, ExecuteCommand, 'execute_command')
    if not client.wait_for_server(timeout_sec=10.0):
        print('execute_command server not available')
        return
    print('명령을 입력하세요 (빈 줄/Ctrl-D 로 종료). 예: 빨간 블록을 파란 블록 위에 쌓아')
    try:
        while True:
            try:
                line = input('> ').strip()
            except EOFError:
                break
            if not line:
                break
            goal = ExecuteCommand.Goal(command=line)
            fut = client.send_goal_async(
                goal, feedback_callback=lambda f: print('  ·', f.feedback.stage))
            rclpy.spin_until_future_complete(node, fut)
            handle = fut.result()
            if not handle.accepted:
                print('  rejected (busy?)')
                continue
            rf = handle.get_result_async()
            rclpy.spin_until_future_complete(node, rf)
            r = rf.result().result
            print(('  ✔ ' if r.success else '  ✘ ') + r.message)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    sys.exit(0)


if __name__ == '__main__':
    main()
