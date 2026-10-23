"""Read a CS2 navigation mesh (.nav, versions 31 to 36): Valve's own areas.

    areas = navmesh.read(path_or_bytes)     # [Area(id, corners=[(x, y, z), ...])]

Each area is a convex polygon with straight edges, in the same world units
as the demos' positions. Every map ships one inside its .vpk pack
(tools/nav_extract.py pulls it out of a CS2 install). The place names
players call ("BombsiteA", "Connector") are NOT stored here as text; the
demos carry them per position (last_place_name), so tools/callout_zones.py
names each area by what the players standing in it were told.

The binary layout is ported from awpy's Rust reader (crates/awpy/src/nav.rs,
MIT licence, github.com/pnxenopoulos/awpy), which follows the layout
documented by ValveResourceFormat. Only what this project uses is read:
area ids and polygons. The embedded KV3 documents of version 36 are empty
placeholders in shipped navs and are stepped over by their header sizes.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = 0xFEEDFACE
MIN_VERSION, MAX_VERSION = 31, 36


@dataclass
class Area:
    area_id: int
    corners: list           # [(x, y, z), ...] in order around the polygon

    def centre(self):
        n = len(self.corners)
        return tuple(sum(c[i] for c in self.corners) / n for i in range(3))

    def contains(self, x: float, y: float) -> bool:
        """Even-odd ray cast in the XY plane."""
        inside = False
        pts = self.corners
        j = len(pts) - 1
        for i in range(len(pts)):
            xi, yi = pts[i][0], pts[i][1]
            xj, yj = pts[j][0], pts[j][1]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside


class _Reader:
    def __init__(self, data: bytes):
        self.d, self.p = data, 0

    def take(self, n):
        if self.p + n > len(self.d):
            raise ValueError("nav: unexpected end of data")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def u8(self):
        return self.take(1)[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def i64(self):
        return struct.unpack("<q", self.take(8))[0]

    def vec3(self):
        return struct.unpack("<fff", self.take(12))

    def skip(self, n):
        self.take(n)

    def align8(self):
        self.skip((8 - self.p % 8) % 8)

    def skip_cstring(self):
        while self.u8() != 0:
            pass


def _skip_kv3(r: _Reader):
    """Step over an embedded binary KV3 document by its header's sizes."""
    r.align8()
    magic = r.u32()
    version = magic & 0xFF
    if magic & 0xFFFFFF00 != 0x4B563300 or not 2 <= version <= 5:
        raise ValueError(f"nav: unsupported KV3 signature {magic:#010x}")
    r.skip(16)                      # format GUID
    method = r.u32()                # 0 none, 1 LZ4, 2 ZSTD
    r.skip(4)                       # dictionary id + frame size
    r.skip(16)                      # countBytes1/4/8 + countTypes
    r.skip(4)                       # countObjects + countArrays
    unc_total, cmp_total, n_blocks, n_blobs = r.i32(), r.i32(), r.i32(), r.i32()
    block_cmp = 0
    if version >= 4:
        r.skip(4)
        block_cmp = r.i32()
    if version >= 5:
        unc1, cmp1, unc2, cmp2 = r.i32(), r.i32(), r.i32(), r.i32()
        r.skip(32)
    else:
        unc1, cmp1, unc2, cmp2 = unc_total, cmp_total, 0, 0
    if method > 2 or n_blocks or n_blobs:
        raise ValueError("nav: KV3 document with data is not supported")
    on_disk = (unc1 if method == 0 else cmp1) + (unc2 if method == 0 else cmp2)
    r.skip(on_disk + block_cmp)


def read(source) -> list[Area]:
    data = source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    r = _Reader(bytes(data))
    if r.u32() != MAGIC:
        raise ValueError("nav: bad magic")
    version = r.u32()
    if not MIN_VERSION <= version <= MAX_VERSION:
        raise ValueError(f"nav: unsupported version {version}")
    r.u32()                         # sub version
    r.u32()                         # flags (analysed)
    if version >= 36:
        _skip_kv3(r)
    corners = [r.vec3() for _ in range(r.u32())]
    polygons = []
    for _ in range(r.u32()):
        n = r.u8()
        polygons.append([corners[r.u32()] for _ in range(n)])
        if version >= 35:
            r.skip(4)
    if version >= 32:
        r.skip(4)
    if version >= 35:
        for _ in range(r.u32()):
            r.skip_cstring()
            r.skip(48)
    if version >= 36:
        _skip_kv3(r)
    areas = []
    for _ in range(r.u32()):
        area_id = r.u32()
        r.i64()                     # dynamic attribute flags
        r.u8()                      # hull index
        poly = polygons[r.u32()]
        r.skip(4)
        for _ in range(len(poly)):  # one connection list per edge
            for _ in range(r.u32()):
                r.skip(8)
        r.skip(5)                   # legacy hiding spot and encounter counts
        for _ in range(2):          # ladders above, below
            for _ in range(r.u32()):
                r.skip(4)
        areas.append(Area(area_id, [tuple(c) for c in poly]))
    return areas
