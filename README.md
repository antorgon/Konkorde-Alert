# Bot de alertas BTCUSDT — BitMan, Koncorde y ML RSI

**Documento reconstruido a partir del script vigente `koncorde_alert_limpio.py` y de las versiones anteriores del README disponibles.** Cuando una especificación histórica contradice el código actual, prevalece el comportamiento implementado en el script vigente y la contradicción queda señalada en este documento.

> Este bot genera avisos informativos. No ejecuta órdenes de compra ni de venta.

## 1. Descripción general

El bot consulta datos públicos de mercado de Binance para `BTCUSDT`, calcula indicadores y envía notificaciones a Telegram. Los tres sistemas son independientes:

| Sistema | Temporalidades | Función |
|---|---|---|
| BitMan | H1, H4, D1, 1W | Veredicto `COMPRAR`, `VENDER` o `ESPERAR`. |
| Koncorde | H1, H4, D1, 1W | Detecta transiciones de la media amarilla respecto al área de volumen. |
| ML RSI | H1 | Clasifica el RSI suavizado en verde, rojo o gris mediante K-means 1D. |

El script separa las velas cerradas de la vela en curso usando los tiempos de Binance. Las transiciones detectadas en la vela viva pueden notificarse como provisionales y se resuelven cuando se dispone del cierre de esa vela.

## 2. Archivos del repositorio

Estructura esperada documentada en las versiones anteriores:

```text
.
├── koncorde_alert.py              # script ejecutado (nombre esperado por el workflow antiguo)
├── .github/workflows/koncorde.yml # workflow de GitHub Actions
├── requirements.txt               # dependencias Python
├── README.md                      # este documento
├── state.json                     # estado persistente
└── signals_history.jsonl          # histórico append-only
```

En este paquete el script se entrega como `koncorde_alert_limpio.py`. Si el workflow del repositorio sigue invocando `koncorde_alert.py`, renombra el archivo al nombre esperado o actualiza la ruta del workflow de forma coherente.

- **Script Python:** descarga velas, calcula indicadores, procesa BitMan/Koncorde/ML RSI, gestiona candidaturas y envía mensajes.
- **Workflow:** ejecuta el script, sincroniza y persiste los ficheros de estado/histórico y, según la documentación previa, relanza ciclos.
- **`requirements.txt`:** la documentación previa indica `pandas`, `numpy` y `requests` como dependencias mínimas.
- **`state.json`:** conserva estado operativo, últimas posiciones, candidaturas pendientes, deduplicación y referencias necesarias entre ciclos.
- **`signals_history.jsonl`:** histórico JSON Lines; cada línea es un registro independiente. Se añade al final y no debe reescribirse durante la operación normal.

`state.json` y `signals_history.jsonl` no forman parte del ZIP de actualización. **No los sustituyas ni reinicies al actualizar el script.** Haz una copia de seguridad antes de cualquier cambio manual.

## 3. Configuración y credenciales

El script lee estas variables de entorno:

- `TELEGRAM_TOKEN`: token del bot de Telegram.
- `TELEGRAM_CHAT_ID`: chat o grupo destinatario.

Guárdalas como GitHub Actions Secrets; no las escribas en el código, README ni logs compartidos. El código utiliza el endpoint público de klines de Binance `https://data-api.binance.vision/api/v3/klines`; no necesita claves API privadas de Binance.

La documentación histórica del repositorio indica que el workflow instala dependencias con `pip install -r requirements.txt` y que el archivo debe estar en la raíz. También indica permisos `contents: write` para guardar el estado/histórico y `actions: write` para solicitar el siguiente ciclo mediante `workflow_dispatch`.

**Importante:** el archivo YAML del workflow no estaba entre los archivos inspeccionados para esta reconstrucción. Por tanto, el nombre real del workflow, sus permisos, horario `schedule`, grupo de concurrencia y estrategia de reintentos deben contrastarse con el `koncorde.yml` que esté actualmente en GitHub antes de dar esos detalles por vigentes.

## 4. Obtención de datos y temporalidades

- Símbolo: `BTCUSDT`.
- Endpoint: Binance public market data, klines.
- El código define inicialmente `LOOKBACK = 400` como valor predeterminado de `get_klines()` y posteriormente establece `LOOKBACK = 1000` para el ciclo principal.
- Binance limita cada petición de klines a 1000 velas. Para solicitudes superiores, `get_klines()` encadena lotes hacia atrás mediante `endTime`.
- BitMan y Koncorde procesan H1, H4, D1 y 1W.
- ML RSI procesa H1 y solicita hasta 3000 velas.
- Se exige un mínimo de 100 velas cerradas válidas para procesar una temporalidad.

Las velas cerradas y la vela viva se separan por `close_time`. Los indicadores se calculan sobre la serie que incluye la vela viva cuando está disponible.

## 5. Koncorde: cálculo y disparador vigente

### 5.1 Qué línea genera el evento

El único disparador de las alertas Koncorde es la **media amarilla (`media`)** cuando cambia de posición respecto al área de volumen delimitada por cero y la línea marrón (`marron`). La línea verde (`verde`) no dispara eventos y el cruce verde/media tampoco es un disparador.

El área se calcula geométricamente como:

```python
limite_inferior = min(0, marron)
limite_superior = max(0, marron)
```

La posición de la media amarilla se clasifica en:

- `dentro`: está entre ambos límites, incluidos.
- `fuera_arriba`: está por encima del límite superior.
- `fuera_abajo`: está por debajo del límite inferior.

### 5.2 Eventos

| Transición | Texto de alerta |
|---|---|
| Fuera por arriba → dentro | **Entrada en el área de volumen desde arriba** |
| Fuera por abajo → dentro | **Entrada en el área de volumen desde abajo** |
| Dentro → fuera por arriba | **Salida del área de volumen por arriba** |
| Dentro → fuera por abajo | **Salida del área de volumen por abajo** |

Permanecer dentro o fuera no genera eventos nuevos. Un cambio directo de `fuera_arriba` a `fuera_abajo` (o viceversa) sin transición observada por el interior no genera una entrada/salida.

Al iniciar el seguimiento, si no existe posición anterior guardada, el bot establece una línea base y no emite una alerta inicial. Si la línea marrón cambia de signo, se actualiza la referencia sin generar un evento artificial por inversión de la montaña.

### 5.3 Candidatura por vela y prevención de duplicados

Una misma vela puede generar como máximo una candidatura de evento Koncorde. Si la posición intravela revierte después de la primera transición:

1. La candidatura se marca como invalidada en el estado/histórico.
2. Se actualiza la posición viva observada.
3. No se permite generar una segunda candidatura en esa misma vela, aunque la posición vuelva a cruzar el límite.

Esta protección evita alertas repetidas por oscilaciones intravela alrededor de un límite móvil (incluido el movimiento de la línea marrón).

### 5.4 Resolución al cierre

La candidatura guarda el identificador de la vela, la posición objetivo, el evento, el lado y el ID del evento original.

- **CONFIRMADA:** la media amarilla termina al cierre en la posición objetivo de la candidatura y esta no fue invalidada.
- **INVALIDADA:** la candidatura se revirtió intravela o la media no terminó en la posición esperada.
- **NO VERIFICABLE:** no se pudo recuperar la vela exacta para comprobar el resultado.

TS y ADX/DI son informativos: no intervienen en la decisión de confirmar o invalidar el evento.

### 5.5 Filtros: especificación histórica y comportamiento actual

En documentación intermedia existieron referencias a tres filtros (valor verde, TSA y ADX/DI), así como a una puntuación de 2/3 filtros. Otras revisiones posteriores especificaron expresamente la eliminación de esos filtros como condición de disparo.

**En el script vigente inspeccionado, `_process_koncorde()` no aplica filtros ni una puntuación mínima para generar el evento.** La transición geométrica de la media amarilla es suficiente. TSA, ADX/DI y BBWP se calculan y se muestran como información, pero no bloquean ni generan la alerta Koncorde. La línea verde se calcula como parte del indicador y se conserva para los demás usos del pipeline/BitMan, pero no dispara el evento Koncorde.

### 5.6 Mensajes Telegram y precio

Las alertas provisionales y las resoluciones Koncorde contienen:

- Cabecera `KONCORDE BTCUSDT` y temporalidad.
- Descripción explícita de entrada/salida y lado.
- Precio en negrita.
- Volatilidad BBWP.
- TS alcista/bajista.
- Interpretación textual de ADX/DI.

Precio:

- **Provisional:** `Precio en detección`, tomado del `close` de la vela viva en el ciclo que detecta la transición. Es el último precio disponible en esa vela en ese instante, no necesariamente el precio de cierre definitivo.
- **Confirmada/invalidada/no verificable:** `Precio de cierre`, tomado del `close` de la vela cerrada que resuelve la candidatura.

La interpretación ADX/DI implementada es:

| Condición | Texto |
|---|---|
| ADX < 20 | `Tendencia débil: sin dirección clara.` |
| 20 ≤ ADX < 25 y DI+ > DI− | `Tendencia moderada: alcista.` |
| 20 ≤ ADX < 25 y DI− > DI+ | `Tendencia moderada: bajista.` |
| ADX ≥ 25 y DI+ > DI− | `Tendencia fuerte: alcista.` |
| ADX ≥ 25 y DI− > DI+ | `Tendencia fuerte: bajista.` |
| DI+ = DI− con ADX ≥ 20 | `sin dirección definida` |

Si faltan datos, se muestra `Tendencia: datos no disponibles`. TS es un indicador separado y se comunica como `TS: alcista` o `TS: bajista`; no debe confundirse con la interpretación ADX/DI.

## 6. Fórmulas e indicadores

Los parámetros siguientes se leen del script vigente. Las referencias al Pine original proceden de la documentación técnica anterior del proyecto.

### 6.1 Koncorde

El código implementa:

- Precio típico `OHLC4`.
- PVI/NVI.
- EMA de periodo 15 para suavizar PVI/NVI y obtener la media amarilla de marrón.
- Ventanas rolling de 90 para máximos/mínimos de PVI/NVI suavizados.
- MFI de flujo personalizado del Pine, con longitud 14.
- RSI Wilder de OHLC4, longitud 14.
- Bollinger sobre OHLC4: SMA(25), desviación poblacional (`ddof=0`) ×2.
- Estocástico (21, 3).
- Línea marrón como combinación de RSI, MFI, oscilador Bollinger y estocástico; línea verde como marrón más oscilador PVI; línea azul como oscilador NVI; media amarilla como EMA(15) de marrón.

### 6.2 Trend Speed Analyzer (TS/TSA)

El script mantiene el Trend Speed Analyzer documentado como adaptación del indicador de Zeiierman. Parámetros configurados:

- `TSA_MAX_LENGTH = 118`.
- `TSA_ACCEL_MULT = 2.8`.
- La clasificación es alcista cuando `WMA(close, 2) > dyn_ema`; en caso contrario es bajista.

TS se presenta como información separada y no interviene en la confirmación de eventos Koncorde.

### 6.3 ADX/DMI

- DI Length: 14.
- ADX Smoothing: 14.
- Suavizado Wilder/RMA.
- Sin EMA(3) adicional.
- `ADX_MEDIO = 20` se conserva como constante del script.

ADX expresa fuerza de tendencia; DI+ frente a DI− determina la dirección interpretada en el texto de las alertas. La implementación de BitMan usa además si ADX está subiendo, que es una condición distinta.

### 6.4 AO y BitMan

AO se calcula como `SMA(HL2, 5) - SMA(HL2, 34)`. El código lo escala con el rango de 50 barras y determina el estado alcista/bajista según el signo del cambio del AO escalado.

El valor Koncorde usado por BitMan se obtiene del mayor valor entre verde y marrón; si ambos son negativos, toma el más negativo.

Veredicto:

- **COMPRAR:** AO alcista, ADX subiendo y valor Koncorde positivo.
- **VENDER:** AO bajista, ADX subiendo y valor Koncorde negativo.
- **ESPERAR:** cualquier otra combinación. El resumen explica el motivo, por ejemplo falta de impulso del ADX, retroceso, falta de confirmación Koncorde o señales no alineadas.

BitMan es un sistema independiente de las alertas de transición de Koncorde.

### 6.5 BBWP / volatilidad

BBWP se calcula sobre `close`, con SMA(13), desviación poblacional y comparación percentil con las 252 barras anteriores; la barra actual no se incluye en la muestra de comparación.

Categorías mostradas en los resúmenes:

| BBWP | Clasificación |
|---|---|
| ≤ 2 | Compresión extrema |
| > 2 y < 25 | Volatilidad baja |
| ≥ 25 y < 75 | Volatilidad normal |
| ≥ 75 y < 98 | Volatilidad alta |
| ≥ 98 | Volatilidad extrema |

BBWP es informativo; no determina dirección ni bloquea las señales.

### 6.6 ML RSI

ML RSI se ejecuta solo en H1:

- Fuente: mínimo (`low`).
- RSI Wilder de longitud 27.
- Suavizado SMA(4).
- K-means unidimensional de tres grupos.
- Semillas iniciales en percentiles 25, 50 y 75.
- Hasta 3000 valores RSI disponibles y hasta 1001 iteraciones del bucle (parámetro máximo 1000 más la iteración inclusiva del código).
- RSI por encima del centroide superior: `verde`.
- RSI por debajo del centroide inferior: `rojo`.
- Entre ambos centroides: `gris`.

La clasificación dinámica se calcula para la última vela disponible en producción, no como reclustering histórico completo de cada barra. La implementación Python corrige una inicialización defectuosa de arrays descrita en el Pine aportado anteriormente; por tanto, no se debe afirmar identidad bit a bit con ese Pine sin una comparación específica.

## 7. Resumen diario Telegram

El script envía una fotografía del estado actual una vez al día, en la primera ejecución que alcanza o supera las 08:00 en la zona `Europe/Madrid`. No es un informe de rendimiento del día anterior.

Contenido implementado:

- Precio actual BTCUSDT.
- BitMan H1/H4/D1/1W: veredicto, motivo, AO, ADX subiendo/sin subir, estado positivo/negativo/neutro o cruce de Koncorde y BBWP.
- Koncorde H1/H4/D1/1W: posición de la media amarilla respecto al área de volumen y TS.
- ML RSI H1: color, RSI y posible candidatura provisional pendiente.
- Si faltan datos de una temporalidad, se informa en esa línea.

El resumen Koncorde actual **no** presenta puntuación de filtros ni desglose de tres filtros; esa descripción pertenece a una versión anterior y está superada por el código vigente.

La documentación anterior del workflow mencionaba un `schedule` diario a las 04:13 UTC y ciclos de cinco minutos. Como no se ha inspeccionado el YAML actual, el horario real de disparo y la duración del bucle deben comprobarse directamente en `.github/workflows/koncorde.yml`.

## 8. Estado, histórico, deduplicación y resultados

### `state.json`

Guarda estado operativo entre ejecuciones, entre otros:

- Posición viva de la media amarilla Koncorde por temporalidad (`koncorde_live_volume_position_*`).
- Signo de marrón por temporalidad (`koncorde_live_marron_sign_*`).
- Candidaturas pendientes por sistema/temporalidad y su vela asociada.
- Identificadores y marcas de tiempo necesarios para evitar duplicados y resolver eventos.
- Último ciclo, errores/recuperaciones de datos y marca de resumen diario.

El script carga y guarda este archivo para mantener continuidad entre ejecuciones.

### `signals_history.jsonl`

Es un histórico append-only. El código añade registros de ciclos, eventos, transiciones, envíos Telegram, posiciones de velas cerradas, invalidaciones, resoluciones, interrupciones, errores/recuperaciones y seguimiento de resultados cuando corresponde. No debe editarse ni regenerarse como parte de una actualización normal.

El seguimiento de resultados registra variaciones observadas a 1, 3, 6, 12 y 24 horas para eventos incluidos en ese seguimiento. Son datos históricos, no una predicción ni garantía de resultados futuros.

**No borres ni sustituyas los dos archivos persistentes.** Borrarlos puede reiniciar líneas base/candidaturas, provocar avisos repetidos o perder continuidad histórica. La versión actual utiliza las claves `koncorde_live_volume_position_*` y `koncorde_live_marron_sign_*`; referencias a claves antiguas `koncorde_live_green_*` pertenecen a una iteración previa y no describen el código vigente.

Los registros M15 históricos pueden permanecer en un JSONL antiguo; la versión actual del script no procesa M15 ni elimina registros antiguos.

## 9. Workflow y operación programada

La documentación histórica describe un ciclo aproximado cada cinco minutos, un bucle de unas 5 h 40 min (20 400 segundos), sincronización Git, persistencia de cambios y relanzamiento mediante `workflow_dispatch`. También describe `contents: write`, `actions: write`, `GITHUB_TOKEN` y un grupo de concurrencia `koncorde-loop` con `cancel-in-progress: false`.

Estos detalles son **referencias de la documentación previa**, no una verificación del YAML actualmente desplegado. Antes de confiar en ellos, inspecciona el workflow real y comprueba:

1. Ruta `.github/workflows/koncorde.yml` y nombre del archivo ejecutado.
2. Evento `schedule` y zona/horario UTC.
3. Permisos `contents: write` y `actions: write`.
4. Instalación de `requirements.txt`.
5. Sincronización Git, commit/push de `state.json` y `signals_history.jsonl`.
6. Pausa entre ciclos, duración del bucle y mecanismo de relanzamiento.
7. Política de concurrencia y tratamiento de fallos de push.

No des por persistido un cambio hasta comprobar en los logs que el `git push` finalizó correctamente.

## 10. Diagnóstico

Si no llegan mensajes:

1. Abre GitHub → Actions → ejecución del workflow → logs.
2. Comprueba que se instaló `pandas`, `numpy` y `requests`.
3. Verifica que Binance devuelve velas válidas para las temporalidades esperadas.
4. Comprueba `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` en GitHub Secrets.
5. Confirma que el bot tiene permiso para escribir en el chat/grupo.
6. Revisa `state.json`: la transición puede no ser nueva, ya estar procesada o existir una candidatura pendiente.
7. Recuerda que la primera lectura de Koncorde establece una línea base sin alerta retroactiva.
8. Revisa los registros `processing_error`, `data_error` o `data_recovered` en logs/histórico cuando corresponda.
9. Comprueba que el workflow guardó los cambios persistentes y no falló el `git push`.

Una alerta provisional no equivale a una confirmación. Puede invalidarse antes del cierre.

## 11. Seguridad y límites

- Mantén credenciales exclusivamente en GitHub Secrets.
- No publiques tokens ni datos privados en logs.
- El bot usa datos públicos de mercado Binance y no ejecuta órdenes.
- Los indicadores son herramientas descriptivas; no garantizan resultados.
- BBWP no predice por sí solo la dirección del precio.
- No se han realizado pruebas live contra Binance, Telegram o GitHub Actions como parte de esta reconstrucción documental.

## 12. Historial de cambios funcionales documentados

Este apartado conserva la evolución relevante y aclara qué especificación prevalece:

1. **Sistemas y temporalidades:** BitMan H1/H4/D1/1W, Koncorde H1/H4/D1/1W y ML RSI H1. M15 dejó de formar parte del procesamiento activo; los registros históricos M15 no se borran.
2. **Disparador Koncorde:** se consolidó en la transición de la media amarilla respecto al área entre cero y marrón. Referencias anteriores a la línea verde como disparador están obsoletas.
3. **Filtros Koncorde:** versiones anteriores documentaron filtro verde, TSA, ADX/DI y puntuaciones 2/3. La especificación posterior y el script actual no aplican esos filtros como requisito de alerta. TS, ADX/DI y BBWP son informativos.
4. **Cambio de signo de marrón:** se mantiene la protección para evitar eventos artificiales al invertirse el lado de la montaña.
5. **Eventos intravela:** se conserva una sola candidatura por vela; si se revierte, se invalida y no se crea otra candidatura en esa misma vela.
6. **Mensajes:** se retiraron valores de media amarilla, línea marrón y posición detallada de los avisos Telegram; se simplificó ADX/DI a una explicación textual.
7. **Precio:** provisional = precio disponible al detectar el evento; resolución = precio de cierre de la vela correspondiente. Ambos se muestran en negrita.
8. **Persistencia:** `state.json` y `signals_history.jsonl` deben conservarse entre versiones.

## 13. Lista de comprobación de actualización

- [ ] Confirmar qué nombre de script invoca el workflow y ajustar el nombre/ruta si es necesario.
- [ ] Conservar `state.json` y `signals_history.jsonl` existentes.
- [ ] Mantener `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` como secretos.
- [ ] Confirmar `requirements.txt` y permisos del workflow.
- [ ] Ejecutar primero una ejecución manual controlada.
- [ ] Revisar logs de Binance, cálculos, Telegram y persistencia.
- [ ] Comprobar una alerta provisional y su resolución al cierre.
- [ ] Verificar que una reversión intravela no genera una segunda alerta en la misma vela.
- [ ] Verificar que no se generan alertas iniciales por la línea base.

---

## Nota de alcance de esta reconstrucción

Se contrastó este documento con `koncorde_alert_limpio.py`, el README breve más reciente y los README históricos `README_koncorde_tradingview_corregido.md` y `README_koncorde_alert_corregido.md`. No se dispuso del YAML de GitHub Actions ni del Pine Script original en esta revisión; por eso, los detalles del workflow se identifican como históricos pendientes de comprobación y las fórmulas Pine se describen en la medida en que están reflejadas en el código y en la documentación técnica anterior.
