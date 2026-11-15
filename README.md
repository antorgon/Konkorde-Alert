# Bot de alertas BTCUSDT: BitMan, Koncorde y ML RSI

## 1. Descripción

Este repositorio contiene un bot que consulta datos públicos de Binance para BTCUSDT, calcula indicadores y envía avisos a Telegram mediante GitHub Actions.

Los sistemas son independientes y trabajan con estas temporalidades:

- **BITMAN**: H1, H4, D1 y 1W.
- **KONCORDE**: H1, H4, D1 y 1W.
- **ML RSI**: H1.

El bot evalúa los cambios intravela en cada ejecución y resuelve los candidatos cuando la vela correspondiente cierra. El workflow repite el ciclo aproximadamente cada cinco minutos durante unas 5 horas y 40 minutos, y después solicita el siguiente ciclo.

> Importante: esta guía describe la versión v6 del script y el workflow incluidos en este paquete. No contiene credenciales. Antes de activar el workflow, comprueba que los secretos y dependencias requeridos están configurados en el repositorio.

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
3. Asegúrate de que existe `requirements.txt` en la raíz. El workflow ejecuta `pip install -r requirements.txt`; el archivo debe incluir, como mínimo, las librerías importadas por el script: `pandas`, `numpy` y `requests`.
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
| Koncorde | H1, H4, D1, 1W | Detecta cruces de la línea verde respecto a la media amarilla y evalúa tres filtros. |
| ML RSI | H1 | Clasifica el RSI en verde, rojo o gris y notifica los cambios de color. |

**M15 está eliminado del procesamiento:** no se descargan velas M15, no se calculan indicadores en esa temporalidad y no se generan nuevos eventos M15.

El script separa las velas cerradas de la vela en curso utilizando el `close_time` devuelto por Binance. Los avisos intravela son provisionales; la resolución se realiza al disponer del cierre de la vela correspondiente.

## 5. Alertas de Koncorde

El **evento que dispara la alerta** es exclusivamente el cruce de la línea verde con su media amarilla:

- **Cruce alcista**: la línea verde atraviesa la media amarilla hacia arriba.
- **Cruce bajista**: la línea verde atraviesa la media amarilla hacia abajo.

La posición de la línea verde respecto al **área marrón de volumen** es una información distinta del cruce. Se clasifica como:

- **Sobre la montaña de volumen**: la línea verde está por encima del límite superior de la montaña.
- **Bajo la montaña de volumen**: está por debajo del límite inferior.
- **Dentro del área de volumen**: queda entre cero y el valor de la montaña marrón.

Estar sobre, bajo o dentro del área no genera por sí mismo una alerta. El evento sigue siendo el cruce verde/media amarilla.

Cada cruce se evalúa con tres filtros:

1. **Valor de la línea verde**: comprueba si el valor está dentro del rango de referencia, extendido pero todavía aceptado, o en dirección contraria.
2. **Trend Speed Analyzer (TSA)**: comprueba que la dirección del TSA acompañe al cruce.
3. **ADX y DI**: exige ADX igual o superior al umbral configurado y que DI+ o DI− domine en la dirección del cruce.

Los rangos implementados para el filtro del valor verde son:

- Cruce alcista: dentro del rango entre **25 y 50**; los valores extendidos no negativos también se aceptan.
- Cruce bajista: dentro del rango **≤ -25**; los valores extendidos no positivos también se aceptan.
- Un valor con signo contrario a la dirección del cruce no supera este filtro.

El filtro ADX utiliza un mínimo de **20** y exige DI+ dominante para el cruce alcista o DI− dominante para el bajista. Estos valores corresponden a las constantes actuales del script.

### Estados de los avisos

- **PROVISIONAL**: se detecta un cruce intravela que alcanza al menos 2/3 filtros. Se envía el detalle de los filtros y se guarda el candidato.
- **CONFIRMADA**: al cierre, el último cruce candidato se mantiene y conserva al menos 2/3 filtros. El mensaje identifica el cruce alcista o bajista confirmado, sin mostrar el ID interno.
- **NO CONFIRMADA**: el cruce se mantiene al cierre, pero termina con menos de 2/3 filtros.
- **INVALIDADA**: el cruce provisional desaparece, se invierte o queda reemplazado por otro cruce antes del cierre.
- **NO VERIFICABLE**: no se puede recuperar la vela exacta del candidato para comprobar su resultado.

Los cruces con **0/3 o 1/3** filtros se registran en el histórico, pero no generan un aviso provisional de Telegram. Los IDs se conservan internamente para enlazar candidatos y resoluciones, pero no se muestran en los mensajes de confirmación ni en los cambios de estado. Un cruce posterior válido puede sustituir al candidato anterior; cada candidato conserva su identificador para asociar correctamente su resolución.

## 6. Filtros de Koncorde: interpretación

El resultado se expresa como `0/3`, `1/3`, `2/3` o `3/3`:

- `3/3`: los tres filtros son favorables.
- `2/3`: dos filtros son favorables; alcanza el umbral para enviar el aviso provisional.
- `1/3` o `0/3`: no alcanza el umbral de aviso provisional; el evento queda registrado en el histórico.

El filtro de valor puede aparecer como **dentro**, **extendido** o **contrario**. La condición extendida se acepta cuando conserva coherencia con la dirección del cruce. Por tanto, “extendido” no equivale necesariamente a filtro fallido.

En el resumen diario se muestra por separado la posición de la línea verde respecto al área marrón de volumen, su posición respecto a la media amarilla y la explicación de los tres filtros. La posición no se interpreta como un cruce nuevo. El recuento de filtros del resumen es una lectura contextual según el lado actual de la media amarilla; no significa que se haya producido un nuevo cruce.

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

El resumen diario muestra AO como estado alcista/bajista, ADX como subiendo/no subiendo, la situación de Koncorde (entrada/salida de positivo o montaña positiva/negativa) y la categoría BBWP. No muestra los valores numéricos de AO, ADX ni Koncorde en ese resumen.

BBWP describe la posición relativa de la volatilidad; no predice por sí solo la dirección del precio ni garantiza una expansión del mercado.

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
- **Koncorde H1/H4/D1/1W**: posición, puntuación de filtros y explicación individual de los tres filtros; también indica si existe un candidato provisional pendiente.
- **ML RSI H1**: color y valor RSI; también puede indicar un candidato provisional pendiente.

Se han eliminado del resumen la fecha/hora en una línea independiente, las referencias a velas y cierres, los valores repetidos de los indicadores y el apartado de funcionamiento. Si una temporalidad no tiene datos válidos en ese ciclo, el resumen lo indica en su línea.

El workflow tiene un inicio programado diario a las **04:13 UTC** y realiza ciclos de cinco minutos durante aproximadamente 5 horas y 40 minutos. La hora local de envío del resumen depende de cuándo se ejecute el ciclo que alcanza o supera las 08:00 en Madrid.

## 10. Histórico, estado y control de duplicados

- `state.json` conserva los estados actuales, candidatos provisionales, referencias de eventos y datos necesarios para continuar entre ejecuciones.
- `signals_history.jsonl` guarda eventos en formato JSON Lines: cada línea es un registro independiente.
- El histórico es append-only: el script añade registros y no reescribe los anteriores.
- Los identificadores de evento se utilizan para evitar registrar de nuevo eventos ya procesados; el estado conserva una ventana de IDs para deduplicación.
- El bot añade también registros de ciclo, interrupciones, errores/recuperaciones de datos y seguimiento de resultados cuando corresponde.

El seguimiento de resultados registra el rendimiento observado a 1, 3, 6, 12 y 24 horas para los eventos incluidos en el seguimiento. Estos datos son observaciones históricas, no una garantía de resultados futuros.

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

**Nota de versión:** este README corresponde al script `koncorde_alert.py` y al workflow `koncorde.yml` incluidos en la revisión v6. Si cambian las temporalidades, secretos, umbrales, filtros, dependencias o comportamiento de las alertas, actualiza también esta documentación.

## Lista de comprobación antes de activar

- [ ] `koncorde_alert.py` está en la raíz del repositorio.
- [ ] El workflow está en `.github/workflows/koncorde.yml`.
- [ ] `requirements.txt` existe y contiene las dependencias necesarias.
- [ ] Los secretos `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` están configurados.
- [ ] El workflow tiene permisos para guardar el estado y relanzarse.
- [ ] La ejecución manual termina sin errores.
- [ ] Se reciben los mensajes de Telegram.
- [ ] Se verifica que los avisos provisionales y sus resoluciones se corresponden.
- [ ] Solo se procesan BitMan/Koncorde H1, H4, D1, 1W y ML RSI H1; M15 está eliminado.
- [ ] Se conserva una copia de seguridad de `state.json` y `signals_history.jsonl`.
