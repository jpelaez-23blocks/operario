#!/usr/bin/env python3
"""PoC part 2: prove VNC *input* works.

Clicks the 'Siguiente' pagination button on the Clientes list (read-only,
no state change), waits out the repaint delay, and screenshots the result.
If input works, shot2.png shows 'Página 2'.

Usage: VNC_CLICK=1 VNC_PASSWORD=... .venv/bin/python vnc_click.py
"""
import asyncio
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnc_poc import Reader, vnc_encrypt, HOST, URL  # noqa: E402

import websockets
from PIL import Image

PASSWORD = os.environ.get("VNC_PASSWORD", "")
# 'Siguiente' pagination button, from shot1.png (1280x800 space).
# Grounded by the vision model at 0-1000 (146,787) -> px (187,630).
# (Eyeball estimate (170,672) missed low — grounding beats guessing.)
CLICK_X = int(os.environ.get("CLICK_X", "187"))
CLICK_Y = int(os.environ.get("CLICK_Y", "630"))


async def framebuffer_update(r, w, h):
    await r.ws.send(struct.pack(">BBHHHH", 3, 0, 0, 0, w, h))
    mtype = (await r.read(1))[0]
    assert mtype == 0, f"expected FramebufferUpdate, got {mtype}"
    await r.read(1)
    nrects = struct.unpack(">H", await r.read(2))[0]
    return nrects


async def read_rects(r, nrects, img, bpp8, bigend, rmax, gmax, bmax, rsh, gsh, bsh):
    px = img.load()
    for _ in range(nrects):
        rx, ry, rw, rh = struct.unpack(">HHHH", await r.read(8))
        enc = struct.unpack(">i", await r.read(4))[0]
        assert enc == 0, f"non-raw encoding {enc}"
        data = await r.read(rw * rh * bpp8)
        for yy in range(rh):
            for xx in range(rw):
                off = (yy * rw + xx) * bpp8
                val = int.from_bytes(
                    data[off:off + bpp8], "big" if bigend else "little"
                )
                rr = ((val >> rsh) & rmax) * 255 // rmax if rmax else 0
                gg = ((val >> gsh) & gmax) * 255 // gmax if gmax else 0
                bb = ((val >> bsh) & bmax) * 255 // bmax if bmax else 0
                px[rx + xx, ry + yy] = (rr, gg, bb)


async def main():
    ws = await websockets.connect(
        URL, subprotocols=["binary"], max_size=64 * 1024 * 1024
    )
    r = Reader(ws)
    ver = await r.read(12)
    await ws.send(b"RFB 003.008\n")
    n = (await r.read(1))[0]
    types = await r.read(n)
    choice = 2 if 2 in types else 1
    await ws.send(bytes([choice]))
    if choice == 2:
        await ws.send(vnc_encrypt(PASSWORD, await r.read(16)))
        assert struct.unpack(">I", await r.read(4))[0] == 0
    await ws.send(b"\x01")
    w, h = struct.unpack(">HH", await r.read(4))
    pf = await r.read(16)
    bpp, bigend = pf[0], pf[2]
    rmax, gmax, bmax = struct.unpack(">HHH", pf[4:10])
    rsh, gsh, bsh = pf[10], pf[11], pf[12]
    name_len = struct.unpack(">I", await r.read(4))[0]
    await r.read(name_len)
    await ws.send(struct.pack(">BBHi", 2, 0, 1, 0))  # raw encoding
    bpp8 = bpp // 8
    fmt = dict(bigend=bigend, rmax=rmax, gmax=gmax, bmax=bmax,
               rsh=rsh, gsh=gsh, bsh=bsh)

    # press, hold >=100ms (README: shorter clicks are ignored), release
    print(f"clicking ({CLICK_X},{CLICK_Y})")
    await ws.send(struct.pack(">BBHH", 5, 1, CLICK_X, CLICK_Y))
    await asyncio.sleep(0.15)
    await ws.send(struct.pack(">BBHH", 5, 0, CLICK_X, CLICK_Y))
    # repaint takes up to 1s (README) — wait it out
    await asyncio.sleep(1.5)

    img = Image.new("RGB", (w, h))
    nrects = await framebuffer_update(r, w, h)
    await read_rects(r, nrects, img, bpp8, **fmt)
    img.save("shot2.png")
    print("saved shot2.png")
    await ws.close()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 90))
