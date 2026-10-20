#!/usr/bin/env python3
"""ExecuteCommand action server: text command -> Ollama plan -> validated PickPlace steps.

Also accepts plain strings on /vla/command and reports progress on /vla/status.
"""
import json
import math
import threading
import time

import rclpy
from rclpy.action import ActionClient, ActionServer, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from tf2_ros import Buffer, TransformListener

from vla_interfaces.action import CarryTogether, ExecuteCommand, PickPlace
from vla_interfaces.msg import BlockArray
from vla_planner.llm_plan import PlanError, ask_ollama, resolve_plan


class PlannerNode(Node):

    def __init__(self):
        super().__init__('vla_planner')
        p = self.declare_parameter
        p('ollama_host', 'http://localhost:11434')
        p('model', 'gemma4:e2b')
        p('llm_timeout', 90.0)
        p('block_height', 0.025)
        p('relative_offset', 0.05)
        p('min_clearance', 0.035)
        p('min_reach', 0.09)
        p('max_reach', 0.25)
        p('max_blocks_age', 2.0)      # seconds; refuse to plan on a stale scene
        p('settle_time', 1.0)         # wait after each step before the next one
        p('dry_run', False)           # plan only, do not move
        p('verify_tolerance', 0.03)   # m; camera check that the block ended up at the target
        p('arm_names', [''])          # [''] = one arm at the frame origin; [left, right] = two arms
        p('tray_handle', 0.025)
        p('handoff_x_min', 0.10)      # hand-off points only this far in front of the arm bases
        p('handoff_clearance', 0.05)
        # named table areas in the blocks' frame (empty = the single-arm defaults)
        p('region_names', [''])
        p('region_x', [0.0])
        p('region_y', [0.0])

        cb = ReentrantCallbackGroup()
        self._blocks = None
        self._blocks_stamp = 0.0
        # stacks this node built: {color: (x, y, level)}; the camera cannot see height
        self._levels = {}
        self._busy = threading.Lock()

        self.create_subscription(BlockArray, '/vla/blocks', self._on_blocks, 10, callback_group=cb)
        self.create_subscription(String, '/vla/command', self._on_command_topic, 10, callback_group=cb)
        self._status = self.create_publisher(String, '/vla/status', 10)
        self._pick_place = ActionClient(self, PickPlace, 'pick_place', callback_group=cb)
        self._carry = ActionClient(self, CarryTogether, 'carry_together', callback_group=cb)
        self._tf = Buffer()
        self._tf_listener = TransformListener(self._tf, self)
        self._arm_bases = None
        self._server = ActionServer(self, ExecuteCommand, 'execute_command', self._execute,
                                    goal_callback=self._on_goal, callback_group=cb)
        self.get_logger().info(f'planner ready (model {self.prm("model")}); '
                               'send goals to /execute_command or strings to /vla/command')

    def prm(self, n):
        return self.get_parameter(n).value

    def _on_blocks(self, msg):
        self._blocks = msg
        self._blocks_stamp = time.monotonic()

    def say(self, text):
        self.get_logger().info(text)
        self._status.publish(String(data=text))

    def _scene(self):
        msg = self._blocks
        if msg is None or time.monotonic() - self._blocks_stamp > self.prm('max_blocks_age'):
            raise PlanError('no recent /vla/blocks (is perception running?)')
        if not msg.table_calibrated:
            raise PlanError('table not calibrated yet (all 4 markers must be visible)')
        blocks = []
        for b in msg.blocks:
            d = {'id': b.id, 'color': b.color, 'x': b.x, 'y': b.y, 'yaw': b.yaw,
                 'kind': b.kind or 'block', 'length': b.length, 'width': b.width}
            mem = self._levels.get(b.color)
            if mem and math.hypot(mem[0] - b.x, mem[1] - b.y) < 0.02:
                d['level'] = mem[2]
            blocks.append(d)
        return blocks

    def arm_bases(self):
        """{arm: (x, y)} of each arm base in the blocks' frame (TF, cached)."""
        names = list(self.prm('arm_names'))
        if names == ['']:
            return None
        if self._arm_bases is None:
            frame = self._blocks.header.frame_id
            bases = {}
            for n in names:
                deadline = time.monotonic() + 5.0
                while True:
                    try:
                        t = self._tf.lookup_transform(frame, f'{n}_link0', rclpy.time.Time())
                        break
                    except Exception as e:  # noqa: BLE001
                        if time.monotonic() > deadline:
                            raise PlanError(f'no TF {frame} -> {n}_link0: {e}')
                        time.sleep(0.1)
                bases[n] = (t.transform.translation.x, t.transform.translation.y)
            self._arm_bases = bases
            self.get_logger().info(f'arm bases in {frame}: {bases}')
        return self._arm_bases

    def regions(self):
        names = [n for n in self.prm('region_names') if n]
        if not names:
            return None
        return dict(zip(names, zip(self.prm('region_x'), self.prm('region_y'))))

    # ------------------------------------------------------------------ core
    def run_command(self, command, feedback=None):
        def stage(s):
            self.say(s)
            if feedback:
                feedback(s)

        blocks = self._scene()
        stage(f'planning: "{command}" with {len(blocks)} blocks')
        t0 = time.monotonic()
        arms = self.arm_bases()
        plan = ask_ollama(self.prm('ollama_host'), self.prm('model'), blocks, command,
                          timeout=self.prm('llm_timeout'), arms=list(arms) if arms else None)
        stage(f'LLM ({time.monotonic() - t0:.1f}s): {json.dumps(plan, ensure_ascii=False)}')

        steps = resolve_plan(plan, blocks,
                             block_height=self.prm('block_height'),
                             offset=self.prm('relative_offset'),
                             min_clearance=self.prm('min_clearance'),
                             min_reach=self.prm('min_reach'),
                             max_reach=self.prm('max_reach'),
                             region_xy=self.regions(), arms=arms,
                             tray_handle=self.prm('tray_handle'),
                             handoff_x_min=self.prm('handoff_x_min'),
                             handoff_clearance=self.prm('handoff_clearance'))

        if self.prm('dry_run'):
            stage(f'dry run, {len(steps)} step(s) resolved')
            return plan, steps

        if not self._pick_place.wait_for_server(timeout_sec=10.0):
            raise PlanError('/pick_place action server not available')
        colors = {b['id']: b['color'] for b in blocks}
        for i, s in enumerate(steps):
            if s.get('action') == 'carry':
                self._run_carry(i, len(steps), s, stage)
                continue
            who = f' [{s["arm"]} arm{", hand-off" if s.get("handoff") else ""}]' if s.get('arm') else ''
            stage(f'step {i + 1}/{len(steps)}{who}: {s["pick_id"]} -> '
                  f'({s["place_x"]:.3f}, {s["place_y"]:.3f}, +{s["place_z_offset"]:.3f})')
            goal = PickPlace.Goal()
            for k in ('pick_x', 'pick_y', 'pick_yaw', 'pick_z_offset',
                      'place_x', 'place_y', 'place_yaw', 'place_z_offset'):
                setattr(goal, k, float(s[k]))
            goal.arm = s.get('arm', '')
            goal.pick_color = colors[s['pick_id']]
            res = self._call(self._pick_place, goal)
            if res is None or not res.success:
                raise PlanError(f'step {i + 1} failed: {"timeout" if res is None else res.message}')
            level = int(round(s['place_z_offset'] / self.prm('block_height')))
            color = colors[s['pick_id']]
            if level:
                self._levels[color] = (s['place_x'], s['place_y'], level)
            else:
                self._levels.pop(color, None)
            time.sleep(self.prm('settle_time'))
            err = self._verify(color, s['place_x'], s['place_y'])
            if err is None or err > self.prm('verify_tolerance'):
                got = 'not seen' if err is None else f'{err * 1000:.0f} mm away'
                raise PlanError(f'step {i + 1}: {color} block is {got} from the target')
            if s['place_z_offset'] > 0.0:
                # a correct stack hides the lower block; seeing it elsewhere means it was knocked off
                below = colors.get(s.get('below_id'))
                d = self._nearest(below, s['place_x'], s['place_y']) if below else None
                if d is not None and d > 0.015:
                    self._levels.pop(color, None)
                    raise PlanError(f'step {i + 1}: stack failed, {below} block was pushed '
                                    f'{d * 1000:.0f} mm away')
            stage(f'step {i + 1} verified: {color} block {err * 1000:.0f} mm from target')
        return plan, steps

    def _run_carry(self, i, n, s, stage):
        stage(f'step {i + 1}/{n} [both arms]: carry {s["pick_id"]} -> ({s["place_x"]:.3f}, {s["place_y"]:.3f})')
        if not self._carry.wait_for_server(timeout_sec=10.0):
            raise PlanError('/carry_together action server not available')
        goal = CarryTogether.Goal()
        for k in ('tray_x', 'tray_y', 'tray_yaw', 'tray_length', 'place_x', 'place_y', 'place_yaw'):
            setattr(goal, k, float(s[k]))
        res = self._call(self._carry, goal, timeout=300.0)
        if res is None or not res.success:
            raise PlanError(f'step {i + 1} failed: {"timeout" if res is None else res.message}')
        time.sleep(self.prm('settle_time'))
        err = self._verify(None, s['place_x'], s['place_y'], kind='tray')
        if err is None or err > self.prm('verify_tolerance'):
            got = 'not seen' if err is None else f'{err * 1000:.0f} mm away'
            raise PlanError(f'step {i + 1}: tray is {got} from the target')
        stage(f'step {i + 1} verified: tray {err * 1000:.0f} mm from target')

    def _verify(self, color, x, y, kind=None):
        """Distance from the target to the nearest fresh detection of that color."""
        stamp = self._blocks_stamp
        deadline = time.monotonic() + 3.0
        while self._blocks_stamp == stamp and time.monotonic() < deadline:
            time.sleep(0.05)
        return self._nearest(color, x, y, kind)

    def _nearest(self, color, x, y, kind=None):
        d = [math.hypot(b.x - x, b.y - y) for b in self._blocks.blocks
             if (b.kind == kind if kind else b.color == color)]
        return min(d) if d else None

    def _call(self, client, goal, timeout=180.0):
        done = threading.Event()
        holder = {}

        def on_goal(fut):
            h = fut.result()
            if not h.accepted:
                done.set()
                return
            h.get_result_async().add_done_callback(
                lambda rf: (holder.update(r=rf.result().result), done.set()))

        client.send_goal_async(goal).add_done_callback(on_goal)
        done.wait(timeout)
        return holder.get('r')

    # ------------------------------------------------------------------ interfaces
    def _on_goal(self, _):
        return GoalResponse.REJECT if self._busy.locked() else GoalResponse.ACCEPT

    def _execute(self, gh):
        res = ExecuteCommand.Result()
        fb = ExecuteCommand.Feedback()

        def feedback(s):
            fb.stage = s
            gh.publish_feedback(fb)

        with self._busy:
            try:
                plan, _ = self.run_command(gh.request.command, feedback)
                res.success, res.message = True, 'done'
                res.plan_json = json.dumps(plan, ensure_ascii=False)
                gh.succeed()
            except Exception as e:  # noqa: BLE001
                self.say(f'FAILED: {e}')
                res.success, res.message = False, str(e)
                gh.abort()
        return res

    def _on_command_topic(self, msg):
        if not self._busy.acquire(blocking=False):
            self.say('busy, command ignored')
            return
        try:
            self.run_command(msg.data)
            self.say('done')
        except Exception as e:  # noqa: BLE001
            self.say(f'FAILED: {e}')
        finally:
            self._busy.release()


def main():
    rclpy.init()
    node = PlannerNode()
    ex = MultiThreadedExecutor(num_threads=4)
    ex.add_node(node)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
