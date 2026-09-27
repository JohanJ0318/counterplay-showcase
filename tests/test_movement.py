"""Where a position is, measured on foot, and which way a death counts.

A zone used to be whatever centre was nearest in a straight line, which let a
centre on one side of a wall claim the room on the other. Distance is now
walked over ground people have stood on, so a wall is simply ground nobody
stood on and nothing crosses it.
"""
import numpy as np

from app.movement import _fights
from counterplay import zonemodel as ZM


def _room(x0, x1, y0, y1, step=16.0):
    gx, gy = np.meshgrid(np.arange(x0, x1, step), np.arange(y0, y1, step))
    return gx.ravel(), gy.ravel()


def _two_rooms():
    """Two rooms side by side, a wall between them at x 1000 to 1100, and the
    only way through a corridor 1500 units north. Every point stood on twice,
    so it clears WALK_MIN_SAMPLES."""
    parts = [_room(0, 1000, 0, 1000),          # room A
             _room(1100, 2100, 0, 1000),       # room B
             _room(0, 2100, 1500, 1700),       # the corridor
             _room(0, 200, 1000, 1500),        # A's way up to it
             _room(1900, 2100, 1000, 1500)]    # B's way up to it
    x = np.concatenate([p[0] for p in parts])
    y = np.concatenate([p[1] for p in parts])
    x, y = np.concatenate([x, x]), np.concatenate([y, y])
    return x, y, np.zeros(len(x))


def test_a_zone_does_not_reach_through_a_wall():
    x, y, z = _two_rooms()
    # A's anchor hard against the wall; B's at the far end of room B. In a
    # straight line the west half of room B is nearer A.
    anchors = [(950, 500, 0), (2050, 500, 0)]
    walk = ZM.build_walk(x, y, z, anchors)
    got = ZM.walk_assign(walk, [1150, 1300, 900], [500, 500, 500], [0, 0, 0])
    assert list(got) == [2, 2, 1]


def test_straight_line_would_have_crossed_it():
    # The same positions under the old rule, to show the test above is
    # testing something.
    zones = ZM.Zones(np.array([[950., 500, 0], [2050, 500, 0]]), None)
    got = zones.assign(np.array([1150.]), np.array([500.]), np.array([0.]))
    assert list(got) == [1]


def test_a_position_off_the_ground_is_nowhere():
    x, y, z = _two_rooms()
    walk = ZM.build_walk(x, y, z, [(500, 500, 0), (1600, 500, 0)])
    # (0, 0, 0) is room A's corner and is ground; far outside the map is not.
    got = ZM.walk_assign(walk, [0, 9000], [0, 9000], [0, 0])
    assert list(got) == [1, 0]


def test_a_floor_above_is_a_different_place():
    x, y, z = _two_rooms()
    ux, uy = _room(0, 1000, 0, 1000)
    x = np.concatenate([x, ux, ux])
    y = np.concatenate([y, uy, uy])
    z = np.concatenate([z, np.full(2 * len(ux), 400.0)])
    walk = ZM.build_walk(x, y, z, [(500, 500, 0), (500, 500, 400)])
    got = ZM.walk_assign(walk, [500, 500], [500, 500], [0, 400])
    assert list(got) == [1, 2]


def test_one_of_ours_dying_is_a_death_and_one_of_theirs_a_kill():
    # Two players, three samples. Player 0 is ours and dies between samples
    # 0 and 1; player 1 is theirs and dies between samples 1 and 2.
    alive = np.array([[1, 1], [0, 1], [0, 0]], dtype=bool)
    on_our_side = np.array([[1, 0], [1, 0], [1, 0]], dtype=bool)
    gid = np.array([[4, 7], [4, 7], [4, 7]])
    got = list(_fights(alive, on_our_side, gid))
    assert got == [(0, 4, True), (1, 7, False)]


def test_a_death_placed_nowhere_falls_back_to_the_last_live_sample():
    alive = np.array([[1], [0]], dtype=bool)
    on_our_side = np.array([[0], [0]], dtype=bool)
    gid = np.array([[5], [0]])          # the dead sample reads (0, 0, 0)
    assert list(_fights(alive, on_our_side, gid)) == [(0, 5, False)]


# ---- what each place reads, for "Where your rounds are decided"

from app.movement import PLACE_FIELDS, _place_readings  # noqa: E402


def _read(alive, ours, gid, health, traded=False, post=None, nz=3):
    alive = np.array(alive, dtype=bool)
    n = len(alive)
    secs = np.arange(n, dtype=float)            # one second a sample
    post = np.zeros(n, dtype=bool) if post is None else np.array(post, bool)
    got = _place_readings(alive, np.array(ours, dtype=bool), np.array(gid),
                          np.array(health, dtype=np.uint8), secs, post, nz,
                          lambda _p: traded)
    return {k: dict(zip(PLACE_FIELDS, v)) for k, v in got.items()}


def test_damage_is_health_lost_where_the_victim_stood():
    # Ours (column 0) in place 1 throughout. Theirs (column 1) in place 2,
    # hit for 30, then killed: 100 dealt in place 2, and it was the opening.
    got = _read(alive=[[1, 1], [1, 1], [1, 1], [1, 0]],
                ours=[[1, 0]] * 4,
                gid=[[1, 2]] * 4,
                health=[[100, 100], [100, 70], [100, 70], [100, 0]])
    p2 = got[(2, False)]
    assert (p2["dealt"], p2["kills"], p2["first_kills"]) == (100, 1, 1)
    assert got[(1, False)]["taken"] == 0


def test_a_missing_sample_is_not_a_death_or_damage():
    # Theirs vanishes for one sample (written all zero) and comes back.
    got = _read(alive=[[1, 1], [1, 0], [1, 1]],
                ours=[[1, 0]] * 3,
                gid=[[1, 2], [1, 0], [1, 2]],
                health=[[100, 100], [100, 0], [100, 100]])
    assert all(v["kills"] == 0 and v["dealt"] == 0 for v in got.values())


def test_an_untraded_death_and_who_held_the_place():
    # Ours dies in place 1, not traded. Before that, ours stood alone in
    # place 1 for two seconds and theirs alone in place 2.
    got = _read(alive=[[1, 1], [1, 1], [0, 1]],
                ours=[[1, 0]] * 3,
                gid=[[1, 2], [1, 2], [1, 2]],
                health=[[100, 100], [100, 100], [0, 100]])
    p1, p2 = got[(1, False)], got[(2, False)]
    assert (p1["deaths"], p1["traded"], p1["first_deaths"]) == (1, 0, 1)
    assert p1["taken"] == 100
    assert p1["held"] == 2 and p1["held_by_them"] == 0
    assert p2["held_by_them"] == 3 and p2["held"] == 0


def test_a_place_both_sides_stand_in_is_nobody_s():
    got = _read(alive=[[1, 1], [1, 1]], ours=[[1, 0]] * 2,
                gid=[[1, 1], [1, 1]], health=[[100, 100]] * 2)
    assert (1, False) not in got
