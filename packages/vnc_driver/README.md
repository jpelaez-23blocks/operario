# vnc_driver

Cliente RFB 3.008 sobre el websocket `/websockify` del escritorio. **Validado con PoC** contra el escritorio real del reto (handshake, auth DES, screenshot 1280×800, clic verificado con grounding del modelo).

- `driver.py` — handshake, autenticación, captura de framebuffer.
- `click.py` — eventos de puntero con hold ≥120 ms.

Física del escritorio (del README oficial): hasta 1 s de repaint tras un clic; clics de <100 ms se ignoran; escribir sobre texto existente concatena (select-all antes de reemplazar).

La contraseña del escritorio llega como parámetro en cada tarea (`VNC_PASSWORD` en el PoC). Nunca hardcodeada.
