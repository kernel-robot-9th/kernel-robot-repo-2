import pytest

from vla_planner.llm_plan import PlanError, resolve_plan

BLOCKS = [
    {'id': 'red_0', 'color': 'red', 'x': 0.18, 'y': 0.08, 'yaw': 0.0},
    {'id': 'blue_0', 'color': 'blue', 'x': 0.14, 'y': -0.13, 'yaw': 0.1},
    {'id': 'green_0', 'color': 'green', 'x': 0.20, 'y': -0.07, 'yaw': 0.4},
]


def plan(*steps):
    return {'feasible': True, 'reason': '', 'steps': list(steps)}


def test_region():
    s = resolve_plan(plan({'pick': 'red_0', 'place_mode': 'region', 'region': 'center'}), BLOCKS)
    assert s[0]['place_x'] == pytest.approx(0.18) and s[0]['place_y'] == pytest.approx(0.0)


def test_relative_left():
    s = resolve_plan(plan({'pick': 'red_0', 'place_mode': 'relative', 'target': 'blue_0',
                           'direction': 'left'}), BLOCKS)
    assert (s[0]['place_x'], s[0]['place_y']) == pytest.approx((0.14, -0.08))


def test_stack_then_restack_tracks_levels():
    s = resolve_plan(plan({'pick': 'red_0', 'place_mode': 'on_top', 'target': 'blue_0'},
                          {'pick': 'green_0', 'place_mode': 'on_top', 'target': 'red_0'}), BLOCKS)
    assert s[0]['place_z_offset'] == pytest.approx(0.025)
    assert s[0]['place_yaw'] == pytest.approx(0.1)
    assert (s[1]['place_x'], s[1]['place_y']) == pytest.approx((0.14, -0.13))
    assert s[1]['place_z_offset'] == pytest.approx(0.05)


def test_cannot_pick_buried_block():
    with pytest.raises(PlanError, match='on top'):
        resolve_plan(plan({'pick': 'red_0', 'place_mode': 'on_top', 'target': 'blue_0'},
                          {'pick': 'blue_0', 'place_mode': 'region', 'region': 'left'}), BLOCKS)


def test_remembered_level_sets_pick_height():
    blocks = [dict(BLOCKS[0], level=1)] + BLOCKS[1:]
    s = resolve_plan(plan({'pick': 'red_0', 'place_mode': 'region', 'region': 'back'}), blocks)
    assert s[0]['pick_z_offset'] == pytest.approx(0.025)


@pytest.mark.parametrize('step,msg', [
    ({'pick': 'purple_0', 'place_mode': 'region', 'region': 'center'}, 'not a detected block'),
    ({'pick': 'red_0', 'place_mode': 'relative', 'target': 'green_0', 'direction': 'front'},
     'out of reach'),
    ({'pick': 'blue_0', 'place_mode': 'relative', 'target': 'red_0', 'direction': 'right'},
     'collides with yellow_0'),
    ({'pick': 'red_0', 'place_mode': 'on_top', 'target': 'red_0'}, 'target equals'),
])
def test_rejections(step, msg):
    blocks = BLOCKS + [{'id': 'yellow_0', 'color': 'yellow', 'x': 0.18, 'y': 0.035, 'yaw': 0.0}]
    with pytest.raises(PlanError, match=msg):
        resolve_plan(plan(step), blocks)


def test_infeasible():
    with pytest.raises(PlanError, match='no purple'):
        resolve_plan({'feasible': False, 'reason': 'no purple block', 'steps': []}, BLOCKS)


@pytest.mark.parametrize('place,expected', [
    ('center', {'place_mode': 'region', 'region': 'center'}),
    ('on_top:red_0', {'place_mode': 'on_top', 'target': 'red_0'}),
    ('back_of:blue_0', {'place_mode': 'relative', 'direction': 'back', 'target': 'blue_0'}),
    ('nonsense', {'place_mode': None}),
])
def test_parse_place(place, expected):
    from vla_planner.llm_plan import parse_place
    assert parse_place(place) == expected


def test_schema_enums_only_real_ids():
    from vla_planner.llm_plan import build_schema
    item = build_schema(['red_0', 'blue_0'])['properties']['steps']['items']['properties']
    assert item['pick']['enum'] == ['blue_0', 'red_0']
    assert 'on_top:red_0' in item['place']['enum'] and 'left_of:blue_0' in item['place']['enum']
