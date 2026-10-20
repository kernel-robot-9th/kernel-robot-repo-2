"""LLM prompt/schema and deterministic plan resolution (no ROS here, unit-testable)."""
import json
import math
import urllib.request

REGIONS = ['center', 'left', 'right', 'front', 'back',
           'front_left', 'front_right', 'back_left', 'back_right']
DIRECTIONS = ['left', 'right', 'front', 'back']

# base frame: +x = away from the robot ("front"), +y = robot's left
DEFAULT_REGION_XY = {
    'center': (0.18, 0.0),
    'left': (0.17, 0.12), 'right': (0.17, -0.12),
    'front': (0.23, 0.0), 'back': (0.12, 0.0),
    'front_left': (0.21, 0.10), 'front_right': (0.21, -0.10),
    'back_left': (0.12, 0.10), 'back_right': (0.12, -0.10),
}
DIRECTION_VEC = {'left': (0.0, 1.0), 'right': (0.0, -1.0), 'front': (1.0, 0.0), 'back': (-1.0, 0.0)}

def build_schema(block_ids, arms=None):
    """JSON schema whose enums only allow real block ids and valid place targets.

    Ollama turns the schema into a decoding grammar, so even a small model cannot
    emit placeholder ids or omit the region. With several arms each step also names
    an arm ("auto" unless the command asks for one).
    """
    ids = sorted(block_ids) or ['none']
    step = {
        'type': 'object',
        'properties': {
            'pick': {'type': 'string', 'enum': ids},
            'place': {'type': 'string', 'enum': None},
        },
        'required': ['pick', 'place'],
    }
    if arms and len(arms) > 1:
        step['properties']['arm'] = {'type': 'string', 'enum': ['auto'] + list(arms)}
        step['required'].append('arm')
    places = list(REGIONS)
    for t in ids:
        places.append(f'on_top:{t}')
        places += [f'{d}_of:{t}' for d in DIRECTIONS]
    step['properties']['place']['enum'] = places
    return {
        'type': 'object',
        'properties': {
            'feasible': {'type': 'boolean'},
            'reason': {'type': 'string'},
            'steps': {'type': 'array', 'maxItems': 4, 'items': step},
        },
        'required': ['feasible', 'reason', 'steps'],
    }


def parse_place(place):
    """'center' | 'on_top:red_0' | 'left_of:red_0' -> step fields used by resolve_plan."""
    if place in REGIONS:
        return {'place_mode': 'region', 'region': place}
    if place.startswith('on_top:'):
        return {'place_mode': 'on_top', 'target': place.split(':', 1)[1]}
    for d in DIRECTIONS:
        if place.startswith(f'{d}_of:'):
            return {'place_mode': 'relative', 'direction': d, 'target': place.split(':', 1)[1]}
    return {'place_mode': None}


SYSTEM_PROMPT = """You are the task planner of a small robot arm doing top-down pick and place of
toy blocks on a table. You receive the list of detected blocks and a user command
(Korean or English). Output ONLY JSON matching the schema.

Each step has:
- "pick": the id of the block to move (copy it from the block list).
- "place": where to put it, one of
  * a table area: center, left, right, front, back, front_left, front_right, back_left, back_right
  * "on_top:<id>"  -> stack on that block
  * "left_of:<id>", "right_of:<id>", "front_of:<id>", "back_of:<id>" -> next to that block

Directions are from the robot's point of view: front = far from the robot, back = near the robot,
left = robot's left, right = robot's right.
Korean: 앞/먼쪽=front, 뒤/가까운쪽=back, 왼쪽=left, 오른쪽=right, 가운데/중앙=center,
위에/쌓아=on_top, 옆/옆에=*_of, 구석/모서리=corner (e.g. 왼쪽 뒤 구석 = back_left).
Colors: 빨간/빨강=red, 초록/녹색=green, 파란/파랑=blue, 노란/노랑=yellow.

Examples:
- "빨간 블록을 가운데로" -> {"pick": "red_0", "place": "center"}
- "파란 블록을 오른쪽으로 치워" -> {"pick": "blue_0", "place": "right"}   (a table area, no other block named)
- "초록 블록을 빨간 블록 왼쪽에" -> {"pick": "green_0", "place": "left_of:red_0"}
- "노란 블록을 파란 블록 위에" -> {"pick": "yellow_0", "place": "on_top:blue_0"}

Use a "*_of:<id>" place only when the command names that other block.
Multi-step commands become several steps in execution order.
If the command refers to a block that is not in the list, or is not a pick-and-place task,
set feasible=false, steps=[] and explain briefly in "reason". "reason": one short sentence."""

ARMS_PROMPT = """

There are two arms: "left" (on the robot's left) and "right". Every step has "arm":
- "left" / "right" only when the command names that arm (왼팔/왼쪽 팔=left, 오른팔/오른쪽 팔=right),
- otherwise "auto": the system chooses the arm and hands the object from one arm to the other
  when one arm cannot reach both places.
Objects of kind "tray" (그릇/쟁반/트레이/접시) are always carried with both arms together: pick the
tray and give a table area as place, arm "auto". Never stack a tray. To put a block into a tray
(그릇에 넣어/담아) use place "on_top:<tray id>".
Examples:
- "왼팔로 빨간 블록을 가운데로" -> {"pick": "red_0", "place": "center", "arm": "left"}
- "파란 블록을 왼쪽으로 옮겨" -> {"pick": "blue_0", "place": "left", "arm": "auto"}
- "그릇을 두 팔로 들어서 오른쪽으로 옮겨" -> {"pick": "tray_0", "place": "right", "arm": "auto"}"""


def system_prompt(arms=None):
    return SYSTEM_PROMPT + (ARMS_PROMPT if arms and len(arms) > 1 else '')


def build_user_message(blocks, command):
    scene = [dict({'id': b['id'], 'color': b['color'], 'x': round(b['x'], 3), 'y': round(b['y'], 3)},
                  **({'kind': b['kind']} if b.get('kind', 'block') != 'block' else {}))
             for b in blocks]
    return (f'Blocks on the table (x forward from robot, y to robot\'s left, metres):\n'
            f'{json.dumps(scene, ensure_ascii=False)}\n\nCommand: {command}')


def ask_ollama(host, model, blocks, command, timeout=60.0, temperature=0.0, arms=None):
    """Returns the plan with steps normalized to pick/place_mode/region/target/direction."""
    body = {
        'model': model,
        'stream': False,
        'format': build_schema([b['id'] for b in blocks], arms),
        'options': {'temperature': temperature},
        'messages': [
            {'role': 'system', 'content': system_prompt(arms)},
            {'role': 'user', 'content': build_user_message(blocks, command)},
        ],
    }
    req = urllib.request.Request(f'{host.rstrip("/")}/api/chat',
                                 data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        reply = json.loads(r.read().decode())
    plan = json.loads(reply['message']['content'])
    plan['steps'] = [dict(pick=st.get('pick'), place=st.get('place'), arm=st.get('arm', 'auto'),
                          **parse_place(st.get('place') or ''))
                     for st in plan.get('steps') or []]
    return plan


class PlanError(Exception):
    pass


def _seg_dist(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    t = 0.0 if vx == vy == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy)))
    return math.hypot(px - ax - t * vx, py - ay - t * vy)


def _tray_ends(o, handle=0.025):
    d = o.get('length', 0.0) / 2.0 - handle / 2.0
    c, s = math.cos(o['yaw']), math.sin(o['yaw'])
    return (o['x'] + d * c, o['y'] + d * s), (o['x'] - d * c, o['y'] - d * s)


def _clearance(o, x, y):
    """Distance from a point to an object's footprint centre line (a tray is a segment)."""
    if o.get('kind') == 'tray':
        (ax, ay), (bx, by) = _tray_ends(o)
        return _seg_dist(x, y, ax, ay, bx, by) - o.get('width', 0.06) / 2.0
    return math.hypot(o['x'] - x, o['y'] - y)


def resolve_plan(plan, blocks, block_height=0.025, offset=0.05, min_clearance=0.035,
                 min_reach=0.09, max_reach=0.25, region_xy=None, arms=None, tray_handle=0.025,
                 handoff_x_min=0.10, handoff_clearance=0.05, tray_plate=0.008):
    """Turn the LLM's symbolic plan into metric targets, one dict per robot action.

    arms: {name: (base_x, base_y)} in the blocks' frame; None = one arm at the origin.
    A step one arm cannot do alone becomes two pick_place actions through a hand-off
    point both arms reach (x >= handoff_x_min, so the gripper stays clear of whatever the
    arms stand on, and handoff_clearance from other objects); moving a tray becomes one
    two-arm 'carry' action. A block put on a tray ("on_top" a tray, or a region whose point
    lies on a tray) goes to that point on the tray's plate, tray_plate higher.
    Tracks where each object ends up so later steps see earlier moves.
    """
    region_xy = region_xy or DEFAULT_REGION_XY
    arms = arms or {'': (0.0, 0.0)}
    if not plan.get('feasible', False):
        raise PlanError(plan.get('reason') or 'planner marked the command infeasible')
    steps = plan.get('steps') or []
    if not steps:
        raise PlanError('planner returned no steps')

    world = {b['id']: {'x': b['x'], 'y': b['y'], 'yaw': b.get('yaw', 0.0), 'level': b.get('level', 0),
                       'kind': b.get('kind', 'block'), 'length': b.get('length', 0.0),
                       'width': b.get('width', 0.0)} for b in blocks}

    def get(bid, what):
        if bid not in world:
            raise PlanError(f'{what} "{bid}" is not a detected block (have: {sorted(world)})')
        return world[bid]

    def on_top_of(bid):
        o = world[bid]
        return [k for k, v in world.items()
                if k != bid and v['level'] > o['level'] and math.hypot(v['x'] - o['x'], v['y'] - o['y']) < 0.015]

    def reaches(name, x, y, margin=0.0):
        bx, by = arms[name]
        return min_reach + margin <= math.hypot(x - bx, y - by) <= max_reach - margin

    def r_of(x, y):
        """Distance to the nearest arm base (for messages)."""
        return min(math.hypot(x - bx, y - by) for bx, by in arms.values())

    def clear(x, y, skip, margin=min_clearance):
        return all(_clearance(v, x, y) >= margin for k, v in world.items() if k not in skip)

    def handoff_point(a, b, pick, place, skip):
        """A free point both arms reach comfortably (placing is least accurate near the
        reach limit): the largest reach margin available, then the shortest travel."""
        for margin in (0.04, 0.03, 0.02, 0.01):
            best = None
            for i in range(0, 41):
                for j in range(-50, 51):
                    x, y = handoff_x_min + 0.0075 * i, 0.0075 * j
                    if not (reaches(a, x, y, margin) and reaches(b, x, y, margin)
                            and clear(x, y, skip, handoff_clearance)):
                        continue
                    cost = math.dist(pick, (x, y)) + math.dist((x, y), place)
                    if best is None or cost < best[0]:
                        best = (cost, x, y)
            if best is not None:
                return best[1:]
        return None

    def tray_under(x, y, skip):
        """The tray whose plate holds (x, y) with room for a block between the handles."""
        for k, v in world.items():
            if k not in skip and v['kind'] == 'tray' and _clearance(v, x, y) < 0.0 and \
                    all(math.dist(e, (x, y)) >= min_clearance for e in _tray_ends(v, tray_handle)):
                return k
        return None

    out = []
    for i, s in enumerate(steps):
        tag = f'step {i + 1}'
        pick_id = s.get('pick')
        src = get(pick_id, f'{tag} pick')
        if on_top_of(pick_id):
            raise PlanError(f'{tag}: {pick_id} has a block on top of it')
        mode = s.get('place_mode')
        level = 0
        yaw = 0.0
        in_tray = None
        if mode == 'region':
            reg = s.get('region')
            if reg not in region_xy:
                raise PlanError(f'{tag}: unknown region "{reg}"')
            px, py = region_xy[reg]
            if src['kind'] != 'tray':
                in_tray = tray_under(px, py, {pick_id})
        elif mode in ('relative', 'on_top'):
            tid = s.get('target')
            if tid == pick_id:
                raise PlanError(f'{tag}: target equals the picked block')
            tgt = get(tid, f'{tag} target')
            if mode == 'on_top' and tgt['kind'] == 'tray' and src['kind'] != 'tray':
                in_tray, px, py = tid, tgt['x'], tgt['y']
            elif mode == 'on_top':
                if tgt['kind'] == 'tray' or src['kind'] == 'tray':
                    raise PlanError(f'{tag}: trays cannot be stacked')
                if on_top_of(tid):
                    raise PlanError(f'{tag}: {tid} already has a block on top')
                px, py, yaw, level = tgt['x'], tgt['y'], tgt['yaw'], tgt['level'] + 1
            elif mode == 'relative':
                d = s.get('direction')
                if d not in DIRECTION_VEC:
                    raise PlanError(f'{tag}: unknown direction "{d}"')
                dx, dy = DIRECTION_VEC[d]
                gap = offset + (tgt['length'] / 2 if tgt['kind'] == 'tray' and dx else 0.0)
                px, py = tgt['x'] + dx * gap, tgt['y'] + dy * gap
        else:
            raise PlanError(f'{tag}: unknown place_mode "{mode}"')
        if in_tray:
            yaw = world[in_tray]['yaw']

        # ---- a tray: both arms carry it, keeping its orientation
        if src['kind'] == 'tray':
            if len(arms) < 2:
                raise PlanError(f'{tag}: {pick_id} needs two arms')
            moved = dict(src, x=px, y=py)
            ends_now, ends_then = _tray_ends(src, tray_handle), _tray_ends(moved, tray_handle)
            (na, nb) = list(arms)[:2]
            ok = any(reaches(p, *ends_now[0]) and reaches(q, *ends_now[1]) and
                     reaches(p, *ends_then[0]) and reaches(q, *ends_then[1])
                     for p, q in ((na, nb), (nb, na)))
            if not ok:
                raise PlanError(f'{tag}: {pick_id} at ({px:.3f}, {py:.3f}) is out of reach of the two arms')
            for k, v in world.items():
                if k != pick_id and min(_clearance(moved, v['x'], v['y']),
                                        _clearance(v, px, py)) < min_clearance:
                    raise PlanError(f'{tag}: {pick_id} at ({px:.3f}, {py:.3f}) collides with {k}')
            out.append({'action': 'carry', 'pick_id': pick_id, 'tray_x': src['x'], 'tray_y': src['y'],
                        'tray_yaw': src['yaw'], 'tray_length': src['length'],
                        'place_x': px, 'place_y': py, 'place_yaw': src['yaw']})
            world[pick_id] = moved
            continue

        if r_of(px, py) > max_reach or r_of(px, py) < min_reach:
            raise PlanError(f'{tag}: place point ({px:.3f}, {py:.3f}) is out of reach (r={r_of(px, py):.3f} m)')
        if mode != 'on_top' or in_tray:
            for k, v in world.items():
                if k not in (pick_id, in_tray) and _clearance(v, px, py) < min_clearance:
                    raise PlanError(f'{tag}: place point ({px:.3f}, {py:.3f}) collides with {k}')

        pick, place = (src['x'], src['y']), (px, py)
        want = s.get('arm') or 'auto'
        if want != 'auto' and want not in arms:
            raise PlanError(f'{tag}: unknown arm "{want}" (have {sorted(arms)})')
        both = [n for n in arms if reaches(n, *pick) and reaches(n, *place)]
        if want != 'auto':
            if want not in both:
                raise PlanError(f'{tag}: the {want} arm cannot reach both the pick and the place point')
            legs = [(want, pick, place)]
        elif both:
            legs = [(min(both, key=lambda n: math.dist(arms[n], pick)), pick, place)]
        else:
            a = next((n for n in arms if reaches(n, *pick)), None)
            b = next((n for n in arms if n != a and reaches(n, *place)), None)
            if a is None or b is None:
                raise PlanError(f'{tag}: no arm can reach the pick point ({pick[0]:.3f}, {pick[1]:.3f})'
                                if a is None else
                                f'{tag}: place point ({px:.3f}, {py:.3f}) is out of reach')
            h = handoff_point(a, b, pick, place, skip={pick_id})
            if h is None:
                raise PlanError(f'{tag}: no free hand-off point between the {a} and {b} arms')
            legs = [(a, pick, h), (b, h, place)]

        for j, (arm, (ax, ay), (bx, by)) in enumerate(legs):
            last = j == len(legs) - 1
            out.append({'action': 'pick_place', 'arm': arm, 'pick_id': pick_id, 'handoff': len(legs) > 1,
                        'pick_x': ax, 'pick_y': ay, 'pick_yaw': src['yaw'] if j == 0 else 0.0,
                        'pick_z_offset': src['level'] * block_height if j == 0 else 0.0,
                        'place_x': bx, 'place_y': by, 'place_yaw': yaw if last else 0.0,
                        'place_z_offset': (level * block_height + (tray_plate if in_tray else 0.0))
                        if last else 0.0,
                        'below_id': s.get('target') if mode == 'on_top' and not in_tray and last else None})
        world[pick_id] = dict(src, x=px, y=py, yaw=yaw, level=level)
    return out
