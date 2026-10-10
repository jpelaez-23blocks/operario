"""Minimal RFB server over websocket, for driver tests. Serves a synthetic frame via ZRLE."""
import asyncio
import struct
import zlib

import numpy as np
import websockets

from packages.vnc_driver.session import vnc_encrypt

W, H = 1280, 800


def make_frame() -> np.ndarray:
    fb = np.full((H, W, 3), 255, dtype=np.uint8)
    fb[100:200, 300:500] = (10, 120, 200)
    rng = np.random.default_rng(1)
    fb[400:464, 64:128] = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
    return fb


def cpix(rgb) -> bytes:
    return bytes((rgb[2], rgb[1], rgb[0]))


def zrle_encode(fb: np.ndarray) -> bytes:
    """Encode the whole frame as ZRLE tiles: solid, raw, packed-palette, plain RLE mix."""
    out = bytearray()
    for ty in range(0, H, 64):
        for tx in range(0, W, 64):
            tile = fb[ty:ty + 64, tx:tx + 64]
            th, tw = tile.shape[:2]
            flat = tile.reshape(-1, 3)
            uniq = np.unique(flat, axis=0)
            if len(uniq) == 1:
                out += bytes([1]) + cpix(uniq[0])
            elif len(uniq) <= 4:
                pal = [tuple(u) for u in uniq]
                out += bytes([len(pal)]) + b"".join(cpix(c) for c in pal)
                bits = 1 if len(pal) == 2 else 2
                for row in tile:
                    acc, n = 0, 0
                    for px in row:
                        acc = (acc << bits) | pal.index(tuple(px))
                        n += bits
                        if n == 8:
                            out.append(acc)
                            acc, n = 0, 0
                    if n:
                        out.append(acc << (8 - n))
            elif tx % 128 == 0:  # plain RLE of runs of 1
                out += bytes([128])
                for px in flat:
                    out += cpix(px) + b"\x00"
            else:
                out += bytes([0]) + b"".join(cpix(px) for px in flat)
    return bytes(out)


async def handler(ws, events: list, fb: np.ndarray, password: str):
    await ws.send(b"RFB 003.008\n")
    await ws.recv()
    await ws.send(bytes([1, 2]))
    await ws.recv()
    ch = b"0123456789abcdef"
    await ws.send(ch)
    resp = await ws.recv()
    ok = resp == vnc_encrypt(password, ch)
    await ws.send(struct.pack(">I", 0 if ok else 1))
    if not ok:
        return
    await ws.recv()
    name = b"mock"
    await ws.send(struct.pack(">HH", W, H) + bytes(16) + struct.pack(">I", len(name)) + name)
    z = zlib.compressobj()
    first = True
    async for msg in ws:
        t = msg[0]
        if t == 3:
            if first or msg[1] == 0:
                first = False
                data = z.compress(zrle_encode(fb)) + z.flush(zlib.Z_SYNC_FLUSH)
                hdr = struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", 0, 0, W, H, 16)
                await ws.send(hdr + struct.pack(">I", len(data)) + data)
        elif t in (4, 5):
            events.append(bytes(msg))


async def serve(password="pw", port=0):
    events: list = []
    fb = make_frame()
    server = await websockets.serve(lambda ws: handler(ws, events, fb, password), "127.0.0.1", port)
    return server, events, fb
