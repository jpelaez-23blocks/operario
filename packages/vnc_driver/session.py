"""RFB 3.8 client over a websockify websocket.

Encodings: Raw, CopyRect, ZRLE. The pixel format is forced to 32bpp little-endian
RGB888 so decoding never depends on what the server prefers. The framebuffer is a
numpy array kept current by a background reader that requests incremental updates.

Input goes through `_send_input`. `freeze()` cuts it for good; the watchdog calls it
at ~4:30 and the instant a task reaches a terminal state.
"""
from __future__ import annotations

import asyncio
import io
import struct
import time
import zlib
from typing import Optional

import numpy as np
import websockets
from Crypto.Cipher import DES
from PIL import Image

ENC_RAW, ENC_COPYRECT, ENC_ZRLE = 0, 1, 16
# 32bpp, depth 24, little endian, true colour, max 255, shifts R16 G8 B0
PIXEL_FORMAT = struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)

# Keysyms (X11) for non-printable keys.
KEYSYMS = {
    "backspace": 0xFF08, "tab": 0xFF09, "enter": 0xFF0D, "return": 0xFF0D,
    "escape": 0xFF1B, "esc": 0xFF1B, "delete": 0xFFFF, "home": 0xFF50,
    "left": 0xFF51, "up": 0xFF52, "right": 0xFF53, "down": 0xFF54,
    "pageup": 0xFF55, "pagedown": 0xFF56, "end": 0xFF57,
    "shift": 0xFFE1, "ctrl": 0xFFE3, "control": 0xFFE3, "alt": 0xFFE9,
    "space": 0x20,
    **{f"f{i}": 0xFFBD + i for i in range(1, 13)},
}


class VncError(Exception):
    pass


class InputFrozen(VncError):
    """Raised when input is attempted after freeze()."""


def _reverse_bits(b: int) -> int:
    return int(f"{b:08b}"[::-1], 2)


def vnc_encrypt(password: str, challenge: bytes) -> bytes:
    key = password.encode("latin-1", "replace")[:8].ljust(8, b"\x00")
    key = bytes(_reverse_bits(b) for b in key)
    return DES.new(key, DES.MODE_ECB).encrypt(challenge)


def keysym_for_char(ch: str) -> int:
    cp = ord(ch)
    if ch == "\n":
        return KEYSYMS["enter"]
    if ch == "\t":
        return KEYSYMS["tab"]
    if cp < 0x100:
        return cp
    return 0x01000000 + cp


class _Reader:
    def __init__(self, ws):
        self.ws = ws
        self.buf = bytearray()

    async def read(self, n: int, timeout: float = 30) -> bytes:
        while len(self.buf) < n:
            msg = await asyncio.wait_for(self.ws.recv(), timeout)
            if isinstance(msg, str):
                continue
            self.buf += msg
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out


class VncSession:
    def __init__(self, url: str, password: str):
        self.url = url
        self._password = password
        self.width = 0
        self.height = 0
        self.fb: Optional[np.ndarray] = None
        self.last_update = 0.0
        self.updates = 0
        self._ws = None
        self._reader: Optional[_Reader] = None
        self._zdec = zlib.decompressobj()
        self._pump: Optional[asyncio.Task] = None
        self._frozen = False
        self._pump_error: Optional[BaseException] = None
        self._mouse = (0, 0)
        self._send_lock = asyncio.Lock()

    async def _send(self, data: bytes) -> None:
        async with self._send_lock:
            await self._ws.send(data)

    async def reconnect(self) -> None:
        """Re-open the connection (same desktop). Input stays frozen if it was."""
        frozen = self._frozen
        if self._pump:
            self._pump.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._pump_error = None
        self._zdec = zlib.decompressobj()
        self.updates = 0
        last = None
        for i in range(3):
            try:
                await asyncio.wait_for(self._connect(), 25)
                self._frozen = frozen
                return
            except Exception as e:  # noqa: BLE001
                last = e
                await asyncio.sleep(1.0 * (i + 1))
        raise VncError(f"no se pudo reconectar: {type(last).__name__}")

    # ---- connection -------------------------------------------------------
    @classmethod
    async def open(cls, url: str, password: str, attempts: int = 3) -> "VncSession":
        last: Optional[BaseException] = None
        for i in range(attempts):
            s = cls(url, password)
            try:
                await asyncio.wait_for(s._connect(), 25)
                return s
            except Exception as e:  # noqa: BLE001
                last = e
                await s.close()
                await asyncio.sleep(1.0 * (i + 1))
        # never echo the password
        raise VncError(f"no se pudo conectar al escritorio: {type(last).__name__}")

    async def _connect(self) -> None:
        try:
            self._ws = await websockets.connect(
                self.url, subprotocols=["binary"], max_size=64 * 1024 * 1024,
                open_timeout=15, ping_interval=None)
        except websockets.exceptions.InvalidHandshake:
            self._ws = await websockets.connect(
                self.url, max_size=64 * 1024 * 1024, open_timeout=15, ping_interval=None)
        r = self._reader = _Reader(self._ws)
        ver = await r.read(12)
        if not ver.startswith(b"RFB"):
            raise VncError("el servidor no habla RFB")
        await self._send(b"RFB 003.008\n")
        n = (await r.read(1))[0]
        if n == 0:
            ln = struct.unpack(">I", await r.read(4))[0]
            raise VncError("seguridad rechazada: " + (await r.read(ln)).decode("latin-1"))
        types = await r.read(n)
        choice = 2 if 2 in types else (1 if 1 in types else 0)
        if not choice:
            raise VncError("sin tipo de seguridad soportado")
        await self._send(bytes([choice]))
        if choice == 2:
            await self._send(vnc_encrypt(self._password, await r.read(16)))
        status = struct.unpack(">I", await r.read(4))[0]
        if status != 0:
            raise VncError("autenticación VNC rechazada")
        await self._send(b"\x01")  # shared
        self.width, self.height = struct.unpack(">HH", await r.read(4))
        await r.read(16)  # server pixel format, ignored: we set our own
        nl = struct.unpack(">I", await r.read(4))[0]
        await r.read(nl)
        self.fb = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        await self._send(struct.pack(">Bxxx", 0) + PIXEL_FORMAT)  # SetPixelFormat
        encs = [ENC_ZRLE, ENC_COPYRECT, ENC_RAW]
        await self._send(struct.pack(">BxH", 2, len(encs)) + b"".join(struct.pack(">i", e) for e in encs))
        await self._request(incremental=False)
        self._pump = asyncio.create_task(self._pump_loop())
        # wait for the first full frame
        deadline = time.monotonic() + 15
        while self.updates == 0:
            if self._pump_error:
                raise VncError(f"conexión perdida: {type(self._pump_error).__name__}")
            if time.monotonic() > deadline:
                raise VncError("sin primer frame")
            await asyncio.sleep(0.05)

    async def _request(self, incremental: bool) -> None:
        await self._send(struct.pack(">BBHHHH", 3, 1 if incremental else 0, 0, 0, self.width, self.height))

    async def close(self) -> None:
        self._frozen = True
        if self._pump:
            self._pump.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass

    @property
    def connected(self) -> bool:
        return bool(self._pump and not self._pump.done() and self._pump_error is None)

    # ---- framebuffer pump -------------------------------------------------
    async def _pump_loop(self) -> None:
        r = self._reader
        try:
            while True:
                t = (await r.read(1, timeout=3600))[0]
                if t == 0:
                    await r.read(1)
                    nrects = struct.unpack(">H", await r.read(2))[0]
                    for _ in range(nrects):
                        await self._read_rect(r)
                    self.last_update = time.monotonic()
                    self.updates += 1
                    await self._request(incremental=True)
                elif t == 1:  # SetColourMapEntries
                    await r.read(1)
                    first, n = struct.unpack(">HH", await r.read(4))
                    await r.read(n * 6)
                elif t == 2:  # Bell
                    pass
                elif t == 3:  # ServerCutText
                    await r.read(3)
                    ln = struct.unpack(">I", await r.read(4))[0]
                    await r.read(ln)
                else:
                    raise VncError(f"mensaje RFB desconocido {t}")
        except asyncio.CancelledError:
            raise
        except BaseException as e:  # noqa: BLE001
            self._pump_error = e

    async def _read_rect(self, r: _Reader) -> None:
        x, y, w, h = struct.unpack(">HHHH", await r.read(8))
        enc = struct.unpack(">i", await r.read(4))[0]
        if enc == ENC_RAW:
            data = await r.read(w * h * 4)
            a = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
            self.fb[y:y + h, x:x + w] = a[:, :, [2, 1, 0]]
        elif enc == ENC_COPYRECT:
            sx, sy = struct.unpack(">HH", await r.read(4))
            self.fb[y:y + h, x:x + w] = self.fb[sy:sy + h, sx:sx + w].copy()
        elif enc == ENC_ZRLE:
            ln = struct.unpack(">I", await r.read(4))[0]
            comp = await r.read(ln)
            self._decode_zrle(self._zdec.decompress(comp), x, y, w, h)
        else:
            raise VncError(f"codificación no soportada {enc}")

    def _decode_zrle(self, data: bytes, x: int, y: int, w: int, h: int) -> None:
        p = 0
        fb = self.fb

        def cpix(buf: bytes, off: int):
            return (buf[off + 2], buf[off + 1], buf[off])  # rgb from B,G,R

        for ty in range(y, y + h, 64):
            th = min(64, y + h - ty)
            for tx in range(x, x + w, 64):
                tw = min(64, x + w - tx)
                sub = data[p]
                p += 1
                rle = bool(sub & 0x80)
                psize = sub & 0x7F
                if not rle and psize == 0:  # raw
                    n = tw * th
                    a = np.frombuffer(data, dtype=np.uint8, count=n * 3, offset=p).reshape(th, tw, 3)
                    fb[ty:ty + th, tx:tx + tw] = a[:, :, ::-1]
                    p += n * 3
                elif not rle and psize == 1:  # solid
                    fb[ty:ty + th, tx:tx + tw] = cpix(data, p)
                    p += 3
                elif not rle:  # packed palette
                    pal = np.array([cpix(data, p + 3 * i) for i in range(psize)], dtype=np.uint8)
                    p += 3 * psize
                    bits = 1 if psize == 2 else (2 if psize <= 4 else 4)
                    rowbytes = (tw * bits + 7) // 8
                    raw = np.frombuffer(data, dtype=np.uint8, count=rowbytes * th, offset=p).reshape(th, rowbytes)
                    p += rowbytes * th
                    unp = np.unpackbits(raw, axis=1)[:, : rowbytes * 8].reshape(th, rowbytes * 8 // bits, bits)
                    idx = np.zeros(unp.shape[:2], dtype=np.uint8)
                    for b in range(bits):
                        idx = (idx << 1) | unp[:, :, b]
                    idx = idx[:, :tw]
                    fb[ty:ty + th, tx:tx + tw] = pal[idx]
                else:  # RLE
                    n = tw * th
                    out = np.empty((n, 3), dtype=np.uint8)
                    filled = 0
                    if psize == 0:  # plain RLE
                        while filled < n:
                            c = cpix(data, p)
                            p += 3
                            run = 1
                            while True:
                                b = data[p]
                                p += 1
                                run += b
                                if b != 255:
                                    break
                            out[filled:filled + run] = c
                            filled += run
                    else:  # palette RLE
                        ps = psize - 128 if psize >= 128 else psize
                        pal = [cpix(data, p + 3 * i) for i in range(ps)]
                        p += 3 * ps
                        while filled < n:
                            idx = data[p]
                            p += 1
                            run = 1
                            if idx & 0x80:
                                idx &= 0x7F
                                while True:
                                    b = data[p]
                                    p += 1
                                    run += b
                                    if b != 255:
                                        break
                            out[filled:filled + run] = pal[idx]
                            filled += run
                    fb[ty:ty + th, tx:tx + tw] = out[:n].reshape(th, tw, 3)

    # ---- screenshots ------------------------------------------------------
    async def settle(self, quiet: float = 0.35, timeout: float = 2.5, min_wait: float = 1.0) -> None:
        """Wait out the repaint: at least min_wait, then until no update for `quiet` seconds."""
        start = time.monotonic()
        await asyncio.sleep(min_wait)
        while time.monotonic() - start < timeout:
            if time.monotonic() - self.last_update >= quiet:
                return
            await asyncio.sleep(0.05)

    def screenshot(self) -> Image.Image:
        if self._pump_error:
            raise VncError(f"conexión perdida: {type(self._pump_error).__name__}")
        return Image.fromarray(self.fb.copy(), "RGB")

    def screenshot_png(self) -> bytes:
        buf = io.BytesIO()
        self.screenshot().save(buf, format="PNG", optimize=False)
        return buf.getvalue()

    def screenshot_jpeg(self, quality: int = 80) -> bytes:
        buf = io.BytesIO()
        self.screenshot().save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    # ---- input ------------------------------------------------------------
    def freeze(self) -> None:
        """Cut all further input. Irreversible."""
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    async def _send_input(self, payload: bytes) -> None:
        if self._frozen:
            raise InputFrozen("entrada VNC cortada")
        if self._pump_error:
            raise VncError(f"conexión perdida: {type(self._pump_error).__name__}")
        await self._send(payload)

    async def _pointer(self, x: int, y: int, mask: int) -> None:
        x = max(0, min(self.width - 1, int(x)))
        y = max(0, min(self.height - 1, int(y)))
        self._mouse = (x, y)
        await self._send_input(struct.pack(">BBHH", 5, mask, x, y))

    async def move(self, x: int, y: int) -> None:
        await self._pointer(x, y, 0)

    async def click(self, x: int, y: int, button: int = 1, hold: float = 0.15) -> None:
        """Press, hold >=100 ms (shorter clicks are ignored by the desktop), release."""
        mask = 1 << (button - 1)
        await self._pointer(x, y, 0)
        await asyncio.sleep(0.05)
        await self._pointer(x, y, mask)
        await asyncio.sleep(max(hold, 0.12))
        await self._pointer(x, y, 0)

    async def double_click(self, x: int, y: int) -> None:
        await self.click(x, y)
        await asyncio.sleep(0.12)
        await self.click(x, y)

    async def scroll(self, x: int, y: int, dy: int) -> None:
        """dy > 0 scrolls down, dy < 0 up, in wheel notches."""
        bit = 16 if dy > 0 else 8  # button 5 down, button 4 up
        for _ in range(abs(dy)):
            await self._pointer(x, y, bit)
            await asyncio.sleep(0.04)
            await self._pointer(x, y, 0)
            await asyncio.sleep(0.06)

    async def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        await self._pointer(x1, y1, 0)
        await asyncio.sleep(0.05)
        await self._pointer(x1, y1, 1)
        await asyncio.sleep(0.15)
        steps = 8
        for i in range(1, steps + 1):
            await self._pointer(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps, 1)
            await asyncio.sleep(0.03)
        await asyncio.sleep(0.1)
        await self._pointer(x2, y2, 0)

    async def _key(self, sym: int, down: bool) -> None:
        await self._send_input(struct.pack(">BBxxI", 4, 1 if down else 0, sym))

    async def key(self, combo: str) -> None:
        """Press a key or chord, e.g. 'enter', 'ctrl+a', 'shift+tab'."""
        syms = []
        for part in combo.lower().split("+"):
            part = part.strip()
            if part in KEYSYMS:
                syms.append(KEYSYMS[part])
            elif len(part) == 1:
                syms.append(ord(part))
            else:
                raise VncError(f"tecla desconocida: {part}")
        for s in syms:
            await self._key(s, True)
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)
        for s in reversed(syms):
            await self._key(s, False)
            await asyncio.sleep(0.02)

    async def type_text(self, text: str, delay: float = 0.02) -> None:
        for ch in text:
            sym = keysym_for_char(ch)
            await self._key(sym, True)
            await asyncio.sleep(delay)
            await self._key(sym, False)
            await asyncio.sleep(delay)

    async def select_all_and_type(self, text: str) -> None:
        """The desktop concatenates onto existing text, so select all first."""
        await self.key("ctrl+a")
        await asyncio.sleep(0.1)
        if text:
            await self.type_text(text)
        else:
            await self.key("delete")
