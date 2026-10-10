import asyncio
import struct

import numpy as np
import pytest

from packages.vnc_driver.session import InputFrozen, VncError, VncSession
from tests.mock_rfb import serve


def url(server):
    return f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"


@pytest.mark.asyncio
async def test_zrle_frame_matches_and_click_events():
    server, events, fb = await serve("secret")
    s = await VncSession.open(url(server), "secret", attempts=1)
    assert np.array_equal(s.fb, fb)
    await s.click(310, 110)
    await asyncio.sleep(0.2)
    presses = [e for e in events if e[0] == 5]
    assert presses[-1][1] == 0 and presses[-2][1] == 1
    assert struct.unpack(">HH", presses[-2][2:6]) == (310, 110)
    await s.select_all_and_type("Hé")
    await asyncio.sleep(0.3)
    keys = [struct.unpack(">I", e[4:8])[0] for e in events if e[0] == 4]
    assert 0xE9 in keys and ord("H") in keys and ord("a") in keys
    s.freeze()
    with pytest.raises(InputFrozen):
        await s.click(1, 1)
    await s.close()
    server.close()


@pytest.mark.asyncio
async def test_wrong_password_raises_without_echo():
    server, _, _ = await serve("secret")
    with pytest.raises(VncError) as ei:
        await VncSession.open(url(server), "wrong-pass", attempts=1)
    assert "wrong-pass" not in str(ei.value)
    server.close()
