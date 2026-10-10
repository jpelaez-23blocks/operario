import asyncio, json, time
import pytest
from packages.agent_loop.loop import AgentLoop
from packages.vnc_driver.session import VncSession
from tests.mock_rfb import serve


class FakeGw:
    """Scripted model: click, then done; verifier approves or rejects."""
    def __init__(self, script, approve=True):
        self.script, self.approve, self.calls = list(script), approve, 0

    async def chat(self, tier, system, user, images, **kw):
        self.calls += 1
        assert images and images[0][:2] == b"\xff\xd8"
        if "audit" in system:
            return json.dumps({"verificada": self.approve, "evidencia": "visible"})
        return json.dumps(self.script.pop(0))


async def run(script, approve=True):
    server, events, _ = await serve("pw")
    s = await VncSession.open(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}", "pw", attempts=1)
    out = await AgentLoop(FakeGw(script, approve), s, "t", time.monotonic() + 60).run()
    await s.close(); server.close()
    return out, events


async def test_click_then_done_verified():
    out, ev = await run([
        {"thought": "click button", "action": "click", "x": 300, "y": 160},
        {"thought": "saved", "action": "done", "estado": "terminada", "evidencia": "row shown"}])
    assert out.estado == "terminada" and any(e[0] == 5 for e in ev)


async def test_unverified_done_becomes_fallida():
    out, _ = await run([
        {"thought": "x", "action": "done", "estado": "terminada", "evidencia": "e"}] * 3, approve=False)
    assert out.estado == "fallida"


async def test_fail_with_claves():
    out, _ = await run([{"thought": "two matches", "action": "done", "estado": "fallida",
                         "razon": "ambiguo", "claves": ["111", "222"]}])
    assert out.claves == ["111", "222"]
