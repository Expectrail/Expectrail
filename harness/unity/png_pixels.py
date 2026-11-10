"""Read the harness's frames (8-bit RGB or RGBA PNGs, not interlaced) with the standard library only,
and measure how far two frames differ: the cross-runner job runs on a bare runner with no image library.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {2: 3, 6: 4}


def read(path: Path) -> tuple[int, int, int, bytes]:
    """(width, height, channels, pixels) with the rows unfiltered, top row first."""
    data = Path(path).read_bytes()
    if not data.startswith(_SIGNATURE):
        raise ValueError(f"{path}: not a PNG")
    pos, idat, header = 8, [], None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError(f"{path}: no IHDR")
    width, height, depth, color, _, _, interlace = header
    if depth != 8 or color not in _CHANNELS or interlace:
        raise ValueError(f"{path}: only 8-bit RGB or RGBA, not interlaced (depth {depth}, color {color})")
    channels = _CHANNELS[color]
    raw = zlib.decompress(b"".join(idat))
    stride = width * channels
    out = bytearray(height * stride)
    prev = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b = prev[x]
            c = prev[x - channels] if x >= channels else 0
            if kind == 1:
                line[x] = (line[x] + a) & 0xFF
            elif kind == 2:
                line[x] = (line[x] + b) & 0xFF
            elif kind == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 0xFF
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
            elif kind != 0:
                raise ValueError(f"{path}: filter {kind} on row {y}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return width, height, channels, bytes(out)


def difference(path_a: Path, path_b: Path) -> dict:
    """How far two frames differ: pixels with any channel different, and the largest channel difference."""
    wa, ha, ca, pa = read(path_a)
    wb, hb, cb, pb = read(path_b)
    if (wa, ha) != (wb, hb):
        return {"size": [[wa, ha], [wb, hb]], "pixels": wa * ha, "differ": wa * ha, "largest": 255}
    channels = min(ca, cb, 3)
    differ, largest = 0, 0
    for i in range(wa * ha):
        da = pa[i * ca:i * ca + channels]
        db = pb[i * cb:i * cb + channels]
        if da != db:
            differ += 1
            largest = max(largest, max(abs(x - y) for x, y in zip(da, db)))
    return {"size": [[wa, ha], [wb, hb]], "pixels": wa * ha, "differ": differ, "largest": largest}
