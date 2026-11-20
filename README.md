# Bot BTCUSDT — versión corregida de Koncorde

## Cambio aplicado

Se limita a **una candidatura de evento Koncorde por vela**. La posición de la media amarilla puede oscilar alrededor del límite del área de volumen durante las consultas intravela de cinco minutos. Antes, una primera entrada podía invalidarse por una salida y, si volvía a entrar en la misma vela, el bot enviaba una segunda alerta de entrada.

Ahora:
- La primera transición válida dentro/fuera de la vela crea la candidatura provisional.
- Si la posición vuelve al estado contrario antes del cierre, la candidatura queda invalidada.
- No se genera otra entrada/salida en esa misma vela aunque la posición vuelva a cruzar el límite.
- La resolución al cierre conserva el vínculo con la candidatura original y la marca como invalidada si se revirtió.
- Se corrigen los saltos de línea del mensaje Telegram de resolución: se envían como saltos reales y no como los caracteres literales `\\n`.

## Se mantiene sin cambios

- Fórmulas de Koncorde, TS, ADX/DI, BitMan y ML RSI.
- Umbrales, filtros y temporalidades.
- Cálculo del área de volumen: límites entre cero y la línea marrón.
- Archivos persistentes `state.json` y `signals_history.jsonl`: no se incluyen ni se modifican.
- Envío provisional y resolución al cierre.

## Instalación

Sustituye el archivo Python que ejecuta el workflow por `koncorde_alert_corregido.py` (renombrándolo al nombre esperado por tu workflow, si procede). Mantén los secretos `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` y los archivos `state.json` y `signals_history.jsonl` del repositorio.

No borres ni reinicies el estado ni el histórico.

## Pruebas realizadas

- Compilación sintáctica Python: correcta.
- Prueba simulada de secuencia dentro → fuera → dentro en una misma vela: se envía una sola candidatura; la reversión la invalida y el segundo cruce no genera otra alerta.
- Revisión del bloque Telegram: saltos de línea corregidos.

No se ha ejecutado una prueba real contra Binance, GitHub Actions ni Telegram.
