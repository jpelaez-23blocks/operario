#!/usr/bin/env python3
"""PoC: RFB (VNC) client over the websockify websocket.

Validates the riskiest layer of the Operario design: that we can connect to
the event desktop's wss://.../websockify endpoint, authenticate, and pull a
real framebuffer screenshot — with no DOM involved.

Usage: VNC_PASSWORD=... .venv/bin/python vnc_poc.py
Writes screenshot to ./shot1.png. Password comes from env only; never stored.
"""
import asyncio
import os
import struct
import sys

import websockets
from Crypto.Cipher import DES
from PIL import Image

HOST = "frontier-r1-tm37-production.up.railway.app"
URL = f"wss://{HOST}/websockify"
PASSWORD = os.environ.get("VNC_PASSWORD", "")


def reverse_bits(b: int) -> int:
    return int(f"{b:08b}"[::-1], 2)


class Reader:
    """Buffered RFB reader over websocket binary frames."""

    def __init__(self, ws):
        self.ws = ws
        self.buf = bytearray()

    async def read(self, n: int) -> bytes:
        while len(self.buf) < n:
            msg = await asyncio.wait_for(self.ws.recv(), 20)
            if isinstance(msg, str):
                continue
            self.buf += msg
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out


def vnc_encrypt(password: str, challenge: bytes) -> bytes:
    key = password.encode("latin-1")[:8].ljust(8, b"\x00")
    key = bytes(reverse_bits(b) for b in key)
    return DES.new(key, DES.MODE_ECB).encrypt(challenge)


async def main() -> None:
    if not PASSWORD:
        print("VNC_PASSWORD not set", file=sys.stderr)
        sys.exit(2)
    try:
        ws = await websockets.connect(
            URL, subprotocols=["binary"], max_size=64 * 1024 * 1024
        )
        print("ws: connected with binary subprotocol")
    except Exception as e:
        print(f"ws: binary subprotocol failed ({e}), retrying plain")
        ws = await websockets.connect(URL, max_size=64 * 1024 * 1024)
        print("ws: connected plain")

    r = Reader(ws)

    # 1. Version handshake
    ver = await r.read(12)
    print("server version:", ver)
    assert ver.startswith(b"RFB"), f"not RFB: {ver!r}"
    await ws.send(b"RFB 003.008\n")

    # 2. Security types
    n = (await r.read(1))[0]
    if n == 0:
        reason_len = struct.unpack(">I", await r.read(4))[0]
        raise RuntimeError("sec-types failed: " + (await r.read(reason_len)).decode())
    types = await r.read(n)
    print("security types offered:", list(types))
    choice = 2 if 2 in types else (1 if 1 in types else 0)
    await ws.send(bytes([choice]))
    print("security choice:", choice)

    # 3. VNC auth (DES challenge-response)
    if choice == 2:
        challenge = await r.read(16)
        await ws.send(vnc_encrypt(PASSWORD, challenge))
        status = struct.unpack(">I", await r.read(4))[0]
        print("auth status:", status, "(0=OK)")
        assert status == 0, "VNC auth failed"

    # 4. ClientInit + ServerInit
    await ws.send(b"\x01")  # shared flag
    w, h = struct.unpack(">HH", await r.read(4))
    pf = await r.read(16)
    bpp, depth, bigend, truecol = pf[0], pf[1], pf[2], pf[3]
    rmax, gmax, bmax = struct.unpack(">HHH", pf[4:10])
    rsh, gsh, bsh = pf[10], pf[11], pf[12]
    name_len = struct.unpack(">I", await r.read(4))[0]
    name = (await r.read(name_len)).decode("latin-1", "replace")
    print(f"framebuffer: {w}x{h} name={name!r}")
    print(f"pixel format: {bpp}bpp depth={depth} bigendian={bigend} "
          f"truecolor={truecol} max=({rmax},{gmax},{bmax}) shift=({rsh},{gsh},{bsh})")
    assert w == 1280 and h == 800, f"unexpected size {w}x{h}"

    # 5. Request raw encoding, then a full framebuffer update
    await ws.send(struct.pack(">BBHi", 2, 0, 1, 0))          # SetEncodings: raw
    await ws.send(struct.pack(">BBHHHH", 3, 0, 0, 0, w, h))   # FramebufferUpdateRequest

    mtype = (await r.read(1))[0]
    assert mtype == 0, f"expected FramebufferUpdate, got {mtype}"
    await r.read(1)  # padding
    nrects = struct.unpack(">H", await r.read(2))[0]
    print("rects:", nrects)

    img = Image.new("RGB", (w, h))
    px = img.load()
    bpp8 = bpp // 8
    for _ in range(nrects):
        rx, ry, rw, rh = struct.unpack(">HHHH", await r.read(8))
        enc = struct.unpack(">i", await r.read(4))[0]
        assert enc == 0, f"non-raw encoding {enc}"
        data = await r.read(rw * rh * bpp8)
        for yy in range(rh):
            for xx in range(rw):
                off = (yy * rw + xx) * bpp8
                chunk = data[off:off + bpp8]
                val = int.from_bytes(chunk, "big" if bigend else "little")
                rr = ((val >> rsh) & rmax) * 255 // rmax if rmax else 0
                gg = ((val >> gsh) & gmax) * 255 // gmax if gmax else 0
                bb = ((val >> bsh) & bmax) * 255 // bmax if bmax else 0
                px[rx + xx, ry + yy] = (rr, gg, bb)

    img.save("shot1.png")
    print("saved shot1.png")
    await ws.close()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 90))
