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
