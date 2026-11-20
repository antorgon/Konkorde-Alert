# Bot de alertas BTCUSDT: BitMan, Koncorde y ML RSI

## 1. Descripción

Este repositorio contiene un bot que consulta datos públicos de Binance para BTCUSDT, calcula indicadores y envía avisos a Telegram mediante GitHub Actions.

Los sistemas son independientes y trabajan con estas temporalidades:

- **BITMAN**: H1, H4, D1 y 1W.
- **KONCORDE**: H1, H4, D1 y 1W.
- **ML RSI**: H1.

El bot evalúa los cambios intravela en cada ejecución y resuelve los candidatos cuando la vela correspondiente cierra. El workflow repite el ciclo aproximadamente cada cinco minutos durante unas 5 horas y 40 minutos, y después solicita el siguiente ciclo.

> Importante: esta guía corresponde a la revisión corregida del script `koncorde_alert.py`. No contiene credenciales. Antes de activar el workflow, comprueba que los secretos y dependencias requeridos están configurados en el repositorio.

## 2. Archivos principales

```text
.
├── koncorde_alert.py
├── koncorde.yml
├── README.md
├── requirements.txt
├── state.json
└── signals_history.jsonl
```

- `koncorde_alert.py`: descarga los datos, calcula los indicadores, evalúa los sistemas y envía mensajes a Telegram.
- `koncorde.yml`: workflow de GitHub Actions que ejecuta el bot, conserva su estado y relanza el ciclo.
- `README.md`: documentación del proyecto.
- `requirements.txt`: dependencias Python instaladas por el workflow. El YAML espera encontrar este archivo en la raíz del repositorio.
- `state.json`: estado operativo, candidatos pendientes y referencias usadas para evitar avisos duplicados.
- `signals_history.jsonl`: histórico append-only de eventos, cambios de estado y resultados posteriores.

`state.json` y `signals_history.jsonl` se crean automáticamente si todavía no existen. No se incluyen en el paquete de actualización para evitar sustituir los datos de funcionamiento existentes.

## 3. Configuración inicial en GitHub

1. Sube `koncorde_alert.py`, `koncorde.yml` y `README.md` a la raíz del repositorio.
2. Comprueba que el workflow queda en `.github/workflows/koncorde.yml`.
3. Asegúrate de que existe `requirements.txt` en la raíz. El workflow ejecuta `pip install -r requirements.txt`; el archivo debe incluir, como mínimo, `pandas`, `numpy` y `requests`.
4. En GitHub, abre **Settings → Secrets and variables → Actions**.
5. Crea los secretos que utiliza el script:
   - `TELEGRAM_TOKEN`: token del bot de Telegram.
   - `TELEGRAM_CHAT_ID`: identificador del chat o grupo que recibirá los mensajes.
6. No publiques tokens ni identificadores privados en el código, el README o los registros.
7. Abre **Actions**, selecciona **Koncorde Alert** y ejecuta `workflow_dispatch` para una primera prueba manual.
8. Revisa los logs y confirma que el script descarga datos y puede enviar mensajes a Telegram.

### Permisos del workflow

El YAML declara estos permisos:

- `contents: write`: permite guardar en la rama los cambios de `state.json` y `signals_history.jsonl`.
- `actions: write`: permite solicitar mediante la API de GitHub el siguiente ciclo del workflow.

Comprueba que las políticas del repositorio permiten esos permisos y que `GITHUB_TOKEN` está habilitado para las acciones correspondientes.

## 4. Temporalidades y comportamiento

| Sistema | Temporalidades | Comportamiento |
|---|---|---|
| BitMan | H1, H4, D1, 1W | Evalúa COMPRAR, VENDER o ESPERAR y notifica los cambios de estado. |
| Koncorde | H1, H4, D1, 1W | Detecta entradas y salidas de la línea amarilla (media) en el área delimitada por cero y la línea marrón. |
| ML RSI | H1 | Clasifica el RSI en verde, rojo o gris y notifica los cambios de color. |

Esta revisión de TradingView es la variante **sin filtros de Koncorde**: no aplica los filtros de valor verde, TSA ni ADX/DI para decidir si se produce una alerta. Esos indicadores pueden seguir apareciendo como información, pero no generan ni bloquean el evento.

El script separa las velas cerradas de la vela en curso utilizando el `close_time` devuelto por Binance. Los avisos intravela son provisionales; la resolución se realiza al disponer del cierre de la vela correspondiente.

## 5. Alertas de Koncorde

El **evento que dispara la alerta** es exclusivamente el cambio de posición de la **línea amarilla (media)** respecto al área de volumen, delimitada por la línea marrón y el nivel cero.

Para cada vela, el área de volumen es el intervalo comprendido entre `0` y `marron`:

- Si `marron` es positivo, el área va de cero a marrón.
- Si `marron` es negativo, el área va de marrón a cero.

La posición de la línea amarilla (media) se clasifica así:

- **Dentro del área de volumen**: la media está entre los dos límites, incluidos.
- **Fuera por arriba**: la media está por encima del límite superior.
- **Fuera por abajo**: la media está por debajo del límite inferior.

La clasificación geométrica utiliza siempre ambos límites: `min(0, marron)` y `max(0, marron)`. Por ejemplo, si marrón vale -10 y media -5, la media está dentro del área; si marrón vale -10 y media 2, está fuera por arriba.

Los eventos son:

- **Entrada desde arriba**: la media pasa de estar fuera por arriba a estar dentro del área.
- **Entrada desde abajo**: la media pasa de estar fuera por abajo a estar dentro del área.
- **Salida por arriba**: la media pasa de estar dentro del área a quedar fuera por arriba.
- **Salida por abajo**: la media pasa de estar dentro del área a quedar fuera por abajo.

Permanecer dentro o fuera no genera nuevos avisos. Tampoco se considera un evento nuevo pasar de fuera por arriba a fuera por abajo sin una transición observada por el interior del área. Al iniciar el seguimiento se establece una línea base sin emitir una alerta inicial.

Si la línea marrón cambia de signo entre lecturas, el script actualiza la referencia sin generar una entrada o salida en ese ciclo. Esta protección evita atribuir a la línea amarilla un evento artificial causado por la inversión del lado de la montaña.

La línea verde **no dispara** eventos. El cruce entre la línea verde y la media amarilla tampoco dispara eventos. La línea verde puede conservarse como dato informativo, pero la decisión geométrica se basa únicamente en `media` y `marron`.

### Resolución al cierre

Cada candidato provisional guarda el estado objetivo (`dentro`, `fuera_arriba` o `fuera_abajo`) y el identificador de la vela. Al cierre:

- **CONFIRMADA**: la media amarilla termina en la misma posición objetivo que originó el candidato.
- **INVALIDADA**: la transición se revierte antes del cierre o la media no termina en la posición esperada.
- **NO VERIFICABLE**: no se puede recuperar la vela exacta del candidato para comprobar el resultado.

El histórico de la alerta y el de su resolución incluyen los valores de la media amarilla y la línea marrón, la posición calculada y los límites del área. Estos campos permiten auditar qué línea generó el evento y con qué valores, sin modificar el criterio de detección.

## 7. BitMan e indicador de volatilidad BBWP

BitMan analiza H1, H4, D1 y 1W. El veredicto se obtiene cuando se alinean estas condiciones:

- **COMPRAR**: AO alcista, ADX subiendo y valor Koncorde positivo.
- **VENDER**: AO bajista, ADX subiendo y valor Koncorde negativo.
- **ESPERAR**: las condiciones anteriores no están alineadas. El mensaje incluye el motivo detectado, por ejemplo falta de impulso del ADX, retroceso o falta de confirmación de Koncorde.

El **BBWP** se calcula como percentil de la anchura de las Bandas de Bollinger frente a su propio historial. Es exclusivamente informativo: no participa en el veredicto ni modifica las condiciones de BitMan.

Las categorías que utiliza el código son:

| BBWP | Clasificación |
|---|---|
| ≤ 2 | Compresión extrema |
| > 2 y < 25 | Volatilidad baja |
| ≥ 25 y < 75 | Volatilidad normal |
| ≥ 75 y < 98 | Volatilidad alta |
| ≥ 98 | Volatilidad extrema |

El resumen diario muestra AO como estado alcista/bajista, ADX como subiendo/no subiendo, el estado del valor Koncorde (positivo, negativo o cambio de signo) y la categoría BBWP. No muestra los valores numéricos de AO, ADX ni Koncorde en ese resumen.

BBWP describe la posición relativa de la volatilidad; no predice por sí solo la dirección del precio ni garantiza una expansión del mercado.

En el resumen BitMan, el ADX se presenta una sola vez, como `subiendo` o `sin subir`. El estado de Koncorde se expresa como **valor Koncorde positivo**, **negativo**, **neutro** o un cambio de signo. Los mensajes de transición de BitMan y Koncorde no muestran la referencia temporal ni el ID interno; ambos se conservan en el estado y el histórico para relacionar eventos y resoluciones.

## 8. ML RSI

ML RSI se ejecuta únicamente en H1. La configuración implementada es:

- RSI de longitud **27**.
- Fuente: **mínimo (LOW)**.
- Suavizado mediante **SMA de periodo 4**.
- Clasificación dinámica en tres grupos mediante k-means unidimensional.
- Ventana máxima de clasificación: hasta **3000** valores de RSI disponibles.

Los estados comunicados son **VERDE**, **ROJO** y **GRIS**. Los cambios detectados en la vela abierta se notifican como provisionales y se resuelven al cierre. El resumen diario muestra el color y el valor RSI disponible.

La implementación del bot y la configuración de TradingView deben compararse parámetro por parámetro antes de afirmar que producen resultados idénticos.

## 9. Resumen diario de las 08:00 (hora de Madrid)

El script envía una fotografía de los estados actuales una vez al día, en la primera ejecución que se realiza a partir de las **08:00 Europe/Madrid**. No es un informe de resultados del día anterior.

El mensaje contiene:

- **Cabecera**: precio actual de BTCUSDT.
- **BitMan H1/H4/D1/1W**: veredicto, motivo, estado del AO, tendencia del ADX, situación de Koncorde y volatilidad BBWP.
- **Koncorde H1/H4/D1/1W**: posición de la línea verde respecto al área de volumen, puntuación de filtros y explicación individual de los tres filtros; también indica si existe un candidato provisional pendiente.
- **ML RSI H1**: color y valor RSI; también puede indicar un candidato provisional pendiente.

Si una temporalidad no tiene datos válidos en ese ciclo, el resumen lo indica en su línea.

El workflow tiene un inicio programado diario a las **04:13 UTC** y realiza ciclos de cinco minutos durante aproximadamente 5 horas y 40 minutos. La hora local de envío del resumen depende de cuándo se ejecute el ciclo que alcanza o supera las 08:00 en Madrid.

## 10. Histórico, estado y control de duplicados

- `state.json` conserva los estados actuales, candidatos provisionales, referencias de eventos y datos necesarios para continuar entre ejecuciones.
- `signals_history.jsonl` guarda eventos en formato JSON Lines: cada línea es un registro independiente.
- El histórico es append-only: el script añade registros y no reescribe los anteriores.
- Los identificadores de evento se utilizan para evitar registrar de nuevo eventos ya procesados; el estado conserva una ventana de IDs para deduplicación.
- El bot añade también registros de ciclo, interrupciones, errores/recuperaciones de datos y seguimiento de resultados cuando corresponde.

El seguimiento de resultados registra el rendimiento observado a 1, 3, 6, 12 y 24 horas para los eventos incluidos en el seguimiento. Estos datos son observaciones históricas, no una garantía de resultados futuros.

La nueva detección de Koncorde utiliza claves de estado propias (`koncorde_live_green_volume_position_*` y `koncorde_live_green_marron_sign_*`). Así, los valores guardados por la lógica anterior basada en el cruce verde/media o en la posición de la media amarilla no se interpretan como posiciones de la línea verde respecto al área de volumen. En la primera ejecución tras actualizar, se establece una nueva línea base sin emitir una alerta inicial. Las demás claves y los registros históricos no se reinician ni se reescriben.

No borres estos archivos durante el funcionamiento normal: hacerlo puede reiniciar el seguimiento, provocar avisos repetidos o perder continuidad histórica. Antes de actualizar o reiniciar el bot, haz una copia de seguridad de ambos.

Los registros M15 antiguos, si existen en un histórico anterior, se conservan: esta versión no los procesa ni los elimina.

## 11. Diagnóstico

Si no llegan mensajes:

1. Abre **Actions → ejecución del workflow → logs**.
2. Comprueba que el workflow se ha ejecutado y que la instalación de dependencias termina correctamente.
3. Verifica que `requirements.txt` está en la raíz y contiene `pandas`, `numpy` y `requests`.
4. Comprueba que Binance devuelve velas para H1, H4, D1 y 1W.
5. Revisa que los secretos `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` existen y corresponden al bot y chat correctos.
6. Verifica que el bot tiene permiso para escribir en el chat o grupo.
7. Comprueba `state.json`: el estado guardado puede indicar que una transición ya se notificó o que todavía no hay una nueva transición.
8. Recuerda que Koncorde solo envía provisionales con al menos 2/3 filtros; los eventos 0/3 y 1/3 quedan registrados sin aviso de Telegram.
9. En la primera ejecución tras esta actualización, Koncorde establece la nueva referencia de posición de la línea verde sin enviar un aviso inicial. Por ello, no se genera una alerta retroactiva por una posición que ya existía antes de establecer la nueva línea base.

Si el workflow no puede guardar el estado, revisa los permisos de escritura, las reglas de protección de la rama y los mensajes de `git pull`, `git commit` y `git push` en los logs.

Si no se relanza el siguiente ciclo, revisa el permiso `actions: write`, el nombre del workflow (`koncorde.yml`) y el resultado del paso **Relanzar el siguiente ciclo**.

## 12. Seguridad y operación

- Mantén `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` exclusivamente en GitHub Secrets.
- No incluyas tokens ni claves en capturas de pantalla o logs compartidos.
- El acceso a Binance utiliza el endpoint público de datos de mercado; el script no necesita claves API de Binance.
- Este bot genera avisos informativos; no ejecuta órdenes de compra o venta.
- Una alerta provisional puede desaparecer antes del cierre. No debe tratarse como una confirmación.
- El BBWP es informativo y no altera las señales.
- Comprueba los logs después de actualizar el script o el workflow.

## 13. Persistencia y relanzamiento automático del workflow

El workflow utiliza el grupo de concurrencia `koncorde-loop` con `cancel-in-progress: false` para evitar que dos ejecuciones de este bucle trabajen simultáneamente.

En cada iteración:

1. Ejecuta `git pull --rebase` para sincronizar la rama.
2. Ejecuta `koncorde_alert.py`.
3. Añade `state.json` y `signals_history.jsonl` al commit si han cambiado.
4. Si hay cambios preparados, crea un commit y hace `git push` a la rama.
5. Espera 300 segundos antes del siguiente ciclo.

El bucle dura aproximadamente **20.400 segundos (5 h 40 min)**. Al terminar, el paso final solicita otra ejecución del workflow mediante `workflow_dispatch` a través de la API de GitHub. El YAML usa `GITHUB_TOKEN` y requiere permiso `actions: write`.

El `git push` se realiza en un único intento en cada iteración; el YAML actual no implementa una secuencia de tres reintentos ni una resolución automática de conflictos de push. Si falla la sincronización o el guardado, revisa el log de esa ejecución: no debe darse por persistido un cambio hasta comprobar que el push terminó correctamente.

---

**Nota de versión:** este README documenta la revisión corregida del script `koncorde_alert.py`. El disparador de Koncorde es la línea verde entrando o saliendo del área entre cero y marrón. BitMan, ML RSI, las temporalidades y el workflow se mantienen sin cambios.

## Lista de comprobación antes de activar

- [ ] `koncorde_alert.py` está en la raíz del repositorio.
- [ ] El workflow está en `.github/workflows/koncorde.yml`.
- [ ] `requirements.txt` existe y contiene las dependencias necesarias.
- [ ] Los secretos `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` están configurados.
- [ ] El workflow tiene permisos para guardar el estado y relanzarse.
- [ ] La ejecución manual termina sin errores.
- [ ] Se reciben los mensajes de Telegram.
- [ ] Se verifica que las entradas/salidas provisionales y sus resoluciones se corresponden.
- [ ] Solo se procesan BitMan/Koncorde H1, H4, D1, 1W y ML RSI H1; M15 está eliminado.
- [ ] Se conserva una copia de seguridad de `state.json` y `signals_history.jsonl`.


## Corrección de la detección de eventos Koncorde

La entrada o salida del área de volumen se determina exclusivamente con la **línea amarilla (media)** respecto al intervalo delimitado por cero y la línea marrón. La línea verde no genera estos eventos y se conserva únicamente en el filtro de valor verde y en los cálculos de filtros existentes.

- Área de volumen: entre `min(0, marron)` y `max(0, marron)`, incluidos ambos límites.
- Entrada: la línea amarilla pasa de fuera a dentro.
- Salida: la línea amarilla pasa de dentro a fuera, indicando si sale por arriba o por abajo.
- El cálculo se aplica tanto a los eventos provisionales como a la resolución de la vela cerrada.
- Se mantienen los tres filtros (valor verde, TSA y ADX/DI), sus fórmulas y umbrales, y la protección ante cambios de signo de la línea marrón.
- Se reutilizan las claves persistentes `koncorde_live_volume_position_*` y `koncorde_live_marron_sign_*`; no es necesario reiniciar ni modificar `state.json` o `signals_history.jsonl`.

---

## Revisión de cálculos respecto al Pine Script «INDICADORES DE BITMAN»

Esta versión adapta los cálculos Python a las fórmulas del Pine Script adjunto:

- **Koncorde:** OHLC4, PVI/NVI, EMA(15), ventanas 90, MFI de flujo personalizado del Pine (ratio positivo/negativo, no MFI normalizado), RSI Wilder(14), Bollinger SMA(25) con desviación poblacional ×2, estocástico (21,3) y EMA(15) de marrón.
- **ADX/DMI:** DI Length 14 y ADX Smoothing 14 con RMA de Wilder; se elimina la EMA(3) adicional que tenía Python.
- **ML RSI:** se fijan los parámetros definitivos de la fotografía: fuente `low`, RSI(27), suavizado SMA(4), 3000 datos y 1000 pasos máximos de clustering. Sigma ALMA no interviene porque la media elegida es SMA. En el Pine, `Performance Memory`, `Threshold Range Min/Max` y `Step` se declaran pero no intervienen en el cálculo de umbrales mostrado.
- **BBWP:** fuente close, SMA(13), desviación poblacional y comparación con las 252 barras anteriores, sin incluir la barra actual en el conjunto comparado.
- **AO:** SMA(HL2,5) − SMA(HL2,34), escalado por el rango de 50 barras; el color/estado sigue el signo del cambio del AO escalado, como en Pine.
- **TS/TSA:** se conserva el Trend Speed Analyzer existente porque no forma parte del Pine 5-en-1 facilitado y se utiliza en los filtros y mensajes de Koncorde.

**Nota sobre ML RSI:** el Pine adjunto inicializa los arrays de distancias y centroides con tres ceros y después añade otros valores, lo que puede romper la asignación de clusters. Python implementa el K-means 1D de tres grupos que el código parece pretender (semillas P25/P50/P75), en vez de reproducir ese defecto de arrays.

## Formato de mensajes Koncorde

- Alertas provisionales y de resolución: únicamente evento, volatilidad BBWP y TS.
- Resumen diario: únicamente posición/evento de la línea amarilla respecto al área de volumen y TS.
- Se mantienen los filtros internos existentes para decidir si se emite una alerta; no se muestran en el mensaje.

No se modifican `state.json` ni `signals_history.jsonl`. La validación realizada es sintáctica y con datos sintéticos; no equivale a una prueba live contra Binance o Telegram.


---

## Corrección definitiva de alertas Koncorde

Esta revisión sustituye cualquier descripción anterior de filtros o disparadores de Koncorde en este documento:

- El único disparador es la entrada o salida de la **media amarilla (`media`, EMA 15 de `marron`)** respecto al área delimitada por `min(0, marron)` y `max(0, marron)`.
- Se generan alertas provisionales en cuanto se detecta la transición. No se exige ningún filtro ni puntuación mínima.
- Al cierre, el evento se confirma si la media amarilla mantiene la posición objetivo; se invalida si revierte. TS y ADX/DI no intervienen en esta decisión.
- Se elimina el filtro del valor verde y toda la lógica de 2/3 filtros. La línea verde sigue calculándose para los demás usos del indicador, pero no participa en las alertas Koncorde.
- TS y ADX/DI son exclusivamente informativos. Las alertas incluyen evento, volatilidad, TS y valores ADX/DI.
- El apartado Koncorde del resumen diario muestra únicamente la posición/evento y TS.
- Se conserva la protección contra eventos artificiales cuando cambia el signo de marron, así como la línea base inicial sin alerta.
- No se modifican BitMan, ML RSI, `state.json` ni `signals_history.jsonl`.

La validación realizada incluye compilación Python y pruebas geométricas de las transiciones. No se han realizado pruebas live contra Binance o Telegram.
