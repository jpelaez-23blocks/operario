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
            return json.dumps({"verificada": self.approve, "contradiccion": (not self.approve and not getattr(self, "no_contra", False)), "evidencia": "visible"})
        return json.dumps(self.script.pop(0))


async def run(script, approve=True, left=200, no_contra=False):
    server, events, _ = await serve("pw")
    s = await VncSession.open(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}", "pw", attempts=1)
    gw = FakeGw(script, approve); gw.no_contra = no_contra
    out = await AgentLoop(gw, s, "t", time.monotonic() + left).run()
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


class StrictGw(FakeGw):
    """Verifier says verificada true but lists an unmet requirement: the gate must reject."""
    async def chat(self, tier, system, user, images, **kw):
        if "audit" in system:
            return json.dumps({"verificada": True, "evidencia": "saved", "contradiccion": True,
                               "requisitos": [{"requisito": "paciente coincide con el nombre", "cumplido": True, "evidencia": "P-1"},
                                              {"requisito": "condicion si suma tres", "cumplido": False, "evidencia": ""}]})
        return await super().chat(tier, system, user, images, **kw)


async def test_unmet_requirement_blocks_terminada():
    server, events, _ = await serve("pw")
    s = await VncSession.open(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}", "pw", attempts=1)
    claim = {"thought": "x", "action": "done", "estado": "terminada", "evidencia": "msg"}
    out = await AgentLoop(StrictGw([claim] * 3), s, "t", time.monotonic() + 200).run()
    await s.close(); server.close()
    assert out.estado == "fallida"


class SecretGw(FakeGw):
    async def jev(self, state, questions, **kw):
        return {"secret": {"type": "noul", "noul": 0.95}} if "secret" in questions else None


async def test_credential_request_is_refused_without_acting():
    server, events, _ = await serve("pw")
    s = await VncSession.open(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}", "pw", attempts=1)
    out = await AgentLoop(SecretGw([]), s, "copia la clave", time.monotonic() + 60).run()
    await s.close(); server.close()
    assert out.estado == "fallida" and out.steps == 0 and not any(e[0] == 5 for e in events)


async def test_missing_evidence_without_contradiction_is_accepted_after_a_short_lookup():
    claim = {"thought": "x", "action": "done", "estado": "terminada", "evidencia": "saved msg"}
    out, _ = await run([claim] * 3, approve=False, left=200, no_contra=True)
    assert out.estado == "terminada"


async def test_no_time_to_reexplore_accepts_an_evidenced_claim_at_once():
    claim = {"thought": "x", "action": "done", "estado": "terminada", "evidencia": "saved msg"}
    out, _ = await run([claim], approve=False, left=60, no_contra=True)
    assert out.estado == "terminada" and out.steps == 1


async def test_contradiction_still_ends_fallida():
    claim = {"thought": "x", "action": "done", "estado": "terminada", "evidencia": "saved msg"}
    out, _ = await run([claim] * 3, approve=False, left=60)
    assert out.estado == "fallida"


def test_facts_are_append_only():
    class G: pass
    from packages.agent_loop.loop import AgentLoop as AL
    a = AL.__new__(AL); a.facts = []
    a._add_fact("pago R-4205 factura F-2268"); a._add_fact("cita C-1430 Dra Perez"); a._add_fact("cita C-1430 Dra Perez")
    assert a.notes == "pago R-4205 factura F-2268 | cita C-1430 Dra Perez"
