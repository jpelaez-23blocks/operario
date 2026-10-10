import asyncio, json, time
import pytest
from packages.agent_loop.loop import AgentLoop
from packages.vnc_driver.session import VncSession
from tests.mock_rfb import serve


class FakeGw:
    """Scripted model: click, then done; verifier approves or rejects."""
    def __init__(self, script, approve=True):
        self.script, self.approve, self.calls = list(script), approve, 0

    async def jev(self, *a, **k):
        return None

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
        {"thought": "x", "action": "done", "estado": "terminada"}] * 3, approve=False)
    assert out.estado == "fallida"


async def test_persistent_claim_with_evidence_is_kept_when_verifier_cannot_see_earlier_screens():
    out, _ = await run([
        {"thought": "x", "action": "done", "estado": "terminada", "evidencia": "saved msg"}] * 3, approve=False)
    assert out.estado == "terminada"


async def test_fail_with_claves():
    out, _ = await run([{"thought": "two matches", "action": "done", "estado": "fallida",
                         "razon": "ambiguo", "claves": ["111", "222"]}])
    assert out.claves == ["111", "222"]


async def test_chained_actions_run_in_order():
    import struct
    out, ev = await run([
        {"thought": "field then text", "action": "click", "x": 300, "y": 160,
         "then": [{"action": "type", "text": "ab", "replace": False}, {"action": "key", "keys": "tab"}]},
        {"thought": "saved", "action": "done", "estado": "terminada", "evidencia": "row shown"}])
    keys = [struct.unpack(">I", e[4:8])[0] for e in ev if e[0] == 4 and e[1] == 1]
    assert out.estado == "terminada" and keys[:2] == [ord("a"), ord("b")] and keys[2] == 0xFF09


def test_chain_validation():
    import pytest
    from packages.agent_loop.schemas import Action
    base = {"thought": "t", "action": "click", "x": 1, "y": 1}
    Action.model_validate({**base, "then": [{"action": "key", "keys": "tab"}]})
    with pytest.raises(Exception):
        Action.model_validate({**base, "then": [{"action": "key", "keys": "tab"}] * 4})
    with pytest.raises(Exception):
        Action.model_validate({"thought": "t", "action": "done", "estado": "terminada",
                               "then": [{"action": "key", "keys": "tab"}]})
