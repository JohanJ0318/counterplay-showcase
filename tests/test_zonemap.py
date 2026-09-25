"""The zone map paints each place where its kills and deaths were counted.

Live, every shape was numbered by zone index while the counts were numbered
by name-group, so from the first repeated name on a map every shape carried
another place's numbers and another place's name. On Ancient, whose first two
zones are both "Cave", that was nearly every shape.
"""
import re

import numpy as np

from counterplay import zones as Z


def _draw(x, y, key, centres, centre_key, **kw):
    return Z.svg(np.asarray(x, float), np.asarray(y, float),
                 np.asarray(centres, float), np.ones(len(centres)),
                 stat_zones=True, sample_key=np.asarray(key),
                 centre_key=centre_key, **kw)


def _paths(svg):
    return {m.group(1): m.group(2) for m in re.finditer(
        r'<path class="zfill" data-z="(\d+)" d="([^"]*)"', svg)}


def _xs(d):
    return [float(v) for v in re.findall(r"M([\d.]+) ", d)]


def _square_of_samples(x0, x1, y0, y1, n=200):
    gx, gy = np.meshgrid(np.linspace(x0, x1, n), np.linspace(y0, y1, n))
    return gx.ravel(), gy.ravel()


def test_a_cell_belongs_where_its_samples_were_counted():
    # Left block counted as group 7, right block as group 3. The centres are
    # placed the WRONG way round, so nearest-centre would swap them.
    lx, ly = _square_of_samples(0, 900, 0, 900)
    rx, ry = _square_of_samples(1100, 2000, 0, 900)
    x = np.concatenate([lx, rx])
    y = np.concatenate([ly, ry])
    key = np.array([7] * len(lx) + [3] * len(rx))
    centres = [[1500, 450, 0], [450, 450, 0]]
    svg = _draw(x, y, key, centres, centre_key=[7, 3])
    p = _paths(svg)
    assert set(p) == {"3", "7"}
    assert max(_xs(p["7"])) < min(_xs(p["3"]))


def test_shapes_are_keyed_by_group_not_by_zone_index():
    x, y = _square_of_samples(0, 1000, 0, 1000)
    svg = _draw(x, y, np.full(len(x), 12), [[500, 500, 0]], centre_key=[12],
                first_number=1)
    assert set(_paths(svg)) == {"12"}


def test_uncounted_ground_is_drawn_but_never_painted():
    lx, ly = _square_of_samples(0, 900, 0, 900)
    rx, ry = _square_of_samples(1100, 2000, 0, 900)
    key = np.array([0] * len(lx) + [4] * len(rx))
    svg = _draw(np.concatenate([lx, rx]), np.concatenate([ly, ry]), key,
                [[450, 450, 0], [1500, 450, 0]], centre_key=[0, 4])
    assert set(_paths(svg)) == {"4"}
    assert 'class="zvoid"' in svg
    assert 'class="zedge"' in svg


def test_rows_are_as_tall_as_they_are_apart():
    # A tall narrow map, like Nuke's lower floor. Rows used to be drawn one
    # x-cell tall, which left a white stripe under every one of them.
    x, y = _square_of_samples(0, 1000, 0, 3000, n=400)
    svg = _draw(x, y, np.full(len(x), 1), [[500, 1500, 0]], centre_key=[1])
    d = _paths(svg)["1"]
    rows = re.findall(r"M[\d.]+ ([\d.]+)h[\d.]+v([\d.]+)", d)
    tops = sorted({float(t) for t, _ in rows})
    height = float(rows[0][1])
    gaps = np.diff(tops)
    assert height >= gaps.max() - 0.2
