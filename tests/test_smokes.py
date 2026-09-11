"""Smoke spots: two throws at the same place are one call.

`analyse` needs a database and eleven matches; `_cluster` is the piece of new
judgement in it and needs neither.
"""
from __future__ import annotations

import numpy as np

from app import smokes


def test_two_throws_at_the_same_spot_are_one_call():
    # A jump-throw and a stand-throw off the same spot land a hundred units
    # apart. That is one smoke, thrown twice.
    pts = np.array([[0.0, 0.0, 0.0], [90.0, 40.0, 0.0]])
    assert len(set(smokes._cluster(pts))) == 1


def test_two_throws_far_apart_are_two_calls():
    pts = np.array([[0.0, 0.0, 0.0], [smokes.SPOT_RADIUS + 50, 0.0, 0.0]])
    assert len(set(smokes._cluster(pts))) == 2


def test_the_same_spot_on_two_floors_is_two_calls():
    """Nuke's bombsites sit above each other, and a smoke on one is not a smoke
    on the other however close they look from overhead."""
    pts = np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 500.0]])
    assert len(set(smokes._cluster(pts))) == 2


def test_spots_do_not_depend_on_the_order_the_smokes_arrive_in():
    pts = np.array([[0.0, 0.0, 0.0], [80.0, 0.0, 0.0], [900.0, 0.0, 0.0],
                    [960.0, 30.0, 0.0], [2000.0, 0.0, 0.0]])
    forward = len(set(smokes._cluster(pts)))
    backward = len(set(smokes._cluster(pts[::-1])))
    assert forward == backward == 3


def test_no_smokes_is_not_an_error():
    assert smokes._cluster(np.zeros((0, 3))) == []
