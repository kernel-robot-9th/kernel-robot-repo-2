import math

import pytest

from vla_planner.llm_plan import PlanError, build_schema, resolve_plan

ARMS = {'left': (0.0, 0.165), 'right': (0.0, -0.165)}
TRAY = {'id': 'tray_0', 'color': 'purple', 'kind': 'tray', 'x': 0.13, 'y': 0.0,
        'yaw': math.pi / 2, 'length': 0.24, 'width': 0.06}
BLOCKS = [
    {'id': 'red_0', 'color': 'red', 'x': 0.17, 'y': 0.27, 'yaw': 0.0},
    {'id': 'blue_0', 'color': 'blue', 'x': 0.17, 'y': -0.27, 'yaw': 0.0},
    TRAY,
]
REGIONS = {'left': (0.15, 0.22), 'right': (0.15, -0.22), 'center': (0.13, 0.0)}


def plan(*steps):
    return {'feasible': True, 'reason': '', 'steps': list(steps)}


def resolve(*steps, blocks=BLOCKS):
    return resolve_plan(plan(*steps), blocks, arms=ARMS, region_xy=REGIONS)


def test_auto_picks_the_arm_that_reaches():
    s = resolve({'pick': 'red_0', 'place_mode': 'region', 'region': 'left', 'arm': 'auto'})
    assert [x['arm'] for x in s] == ['left'] and s[0]['action'] == 'pick_place'


def test_named_arm_that_cannot_reach_is_rejected():
    with pytest.raises(PlanError, match='right arm cannot reach'):
        resolve({'pick': 'red_0', 'place_mode': 'region', 'region': 'left', 'arm': 'right'})


def test_handoff_between_arms():
    s = resolve({'pick': 'red_0', 'place_mode': 'region', 'region': 'right', 'arm': 'auto'},
                blocks=BLOCKS[:2])
    assert [x['arm'] for x in s] == ['left', 'right'] and all(x['handoff'] for x in s)
    hx, hy = s[0]['place_x'], s[0]['place_y']
    assert (hx, hy) == (s[1]['pick_x'], s[1]['pick_y'])
    for base in ARMS.values():                      # both arms reach the hand-off point
        assert 0.09 <= math.dist(base, (hx, hy)) <= 0.25
    assert hx >= 0.10                               # clear of the board the arms stand on
    assert (s[1]['place_x'], s[1]['place_y']) == pytest.approx(REGIONS['right'])


def test_no_handoff_when_the_tray_fills_the_shared_zone():
    # both arms only reach a narrow strip around y = 0; the tray covers it
    with pytest.raises(PlanError, match='no free hand-off point'):
        resolve({'pick': 'red_0', 'place_mode': 'region', 'region': 'right', 'arm': 'auto'})


def test_tray_is_carried_by_both_arms():
    s = resolve({'pick': 'tray_0', 'place_mode': 'region', 'region': 'center', 'arm': 'auto'},
                blocks=[TRAY])
    assert s[0]['action'] == 'carry' and s[0]['tray_length'] == 0.24
    assert s[0]['place_yaw'] == pytest.approx(math.pi / 2)


def test_tray_out_of_reach():
    with pytest.raises(PlanError, match='out of reach of the two arms'):
        resolve({'pick': 'tray_0', 'place_mode': 'region', 'region': 'left', 'arm': 'auto'}, blocks=[TRAY])


def test_no_stacking_trays():
    other = dict(TRAY, id='tray_1', x=0.13, y=0.0)
    with pytest.raises(PlanError, match='trays cannot be stacked'):
        resolve({'pick': 'tray_0', 'place_mode': 'on_top', 'target': 'tray_1', 'arm': 'auto'},
                blocks=[dict(TRAY, x=0.10), other])


def test_block_goes_into_the_tray():
    for step in ({'pick': 'red_0', 'place_mode': 'on_top', 'target': 'tray_0', 'arm': 'auto'},
                 {'pick': 'red_0', 'place_mode': 'region', 'region': 'center', 'arm': 'auto'}):
        s = resolve(step)
        last = s[-1]
        assert (last['place_x'], last['place_y']) == (0.13, 0.0)
        assert last['place_z_offset'] == pytest.approx(0.008) and last['below_id'] is None
        assert last['place_yaw'] == pytest.approx(math.pi / 2)


def test_tray_spot_must_be_free():
    with pytest.raises(PlanError, match='collides with yellow_0'):
        resolve({'pick': 'red_0', 'place_mode': 'region', 'region': 'center', 'arm': 'auto'},
                blocks=BLOCKS + [{'id': 'yellow_0', 'color': 'yellow', 'x': 0.13, 'y': 0.01, 'yaw': 0.0}])


def test_block_cannot_land_on_a_handle():
    with pytest.raises(PlanError, match='collides with tray_0'):
        resolve_plan(plan({'pick': 'red_0', 'place_mode': 'region', 'region': 'center', 'arm': 'auto'}),
                     BLOCKS, arms=ARMS, region_xy=dict(REGIONS, center=(0.13, 0.10)))


def test_schema_has_arm_enum_only_for_two_arms():
    one = build_schema(['red_0'])['properties']['steps']['items']
    two = build_schema(['red_0'], ['left', 'right'])['properties']['steps']['items']
    assert 'arm' not in one['properties']
    assert two['properties']['arm']['enum'] == ['auto', 'left', 'right'] and 'arm' in two['required']
