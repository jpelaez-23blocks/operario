from packages.summary_composer.composer import Scrubber, compose


def test_scrubs_password_token_and_key_shapes():
    sc = Scrubber(["hunter22", "tok-abcdef"])
    out = compose("fallida", scrub=sc, razon="La contraseña: hunter22 falló, token tok-abcdef, clave sk-or-v1-" + "a" * 30)
    assert "hunter22" not in out and "tok-abcdef" not in out and "sk-or-v1" not in out


def test_respuesta_first_line_and_only_on_terminada():
    sc = Scrubber([])
    assert compose("terminada", scrub=sc, respuesta="45", hizo="x").splitlines()[0] == "respuesta: 45"
    assert "respuesta:" not in compose("fallida", scrub=sc, respuesta="45", razon="no")
    assert "respuesta:" not in compose("terminada", scrub=sc, respuesta="", hizo="x")
