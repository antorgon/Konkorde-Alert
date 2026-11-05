# Bot de alertas BTCUSDT: BitMan, Koncorde y ML RSI

## 1. Descripción

Este repositorio contiene un bot que consulta datos de Binance para BTCUSDT, calcula indicadores y envía avisos a Telegram mediante GitHub Actions.

Los sistemas son independientes y sus mensajes se identifican por el prefijo correspondiente:

- **BITMAN**: análisis en H1, H4 y D1.
- **KONCORDE**: cruces de la línea verde respecto a la media amarilla en H1, H4 y D1.
- **KONCORDE OBS**: observación en M15, sin alertas de Telegram.
- **ML RSI**: seguimiento en H1.

El ciclo de ejecución está previsto cada cinco minutos.

> Importante: esta guía describe el comportamiento previsto del proyecto. Antes de activar el workflow, comprueba que los nombres de secretos y variables indicados en el script coinciden con los configurados en GitHub. No se incluyen credenciales en este documento.

## 2. Archivos principales

```text
.
├── koncorde_alert.py
├── koncorde.yml
├── README.md
├── state.json
└── signals_history.jsonl
```

- `koncorde_alert.py`: descarga datos, calcula indicadores, evalúa señales y envía mensajes a Telegram.
- `koncorde.yml`: workflow de GitHub Actions que ejecuta el script periódicamente.
- `state.json`: estado operativo para evitar repetir alertas y conservar el seguimiento entre ejecuciones.
- `signals_history.jsonl`: histórico de eventos y señales, una entrada JSON por línea.

Los dos últimos archivos pueden crearse durante la ejecución si todavía no existen.

## 3. Configuración inicial en GitHub

1. Sube `koncorde_alert.py` y `koncorde.yml` al repositorio.
2. Comprueba que el workflow está ubicado en `.github/workflows/koncorde.yml`. Si el archivo descargado tiene otro nombre, puedes renombrarlo a `koncorde.yml`.
3. En GitHub, abre **Settings → Secrets and variables → Actions**.
4. Añade los secretos que el script realmente espera. Para identificarlos, revisa las referencias a `os.getenv(...)`, `os.environ[...]` o equivalentes en `koncorde_alert.py`.
5. No publiques claves API, tokens de Telegram ni identificadores privados en el código, el README o los registros.
6. Abre **Actions**, selecciona el workflow y ejecuta `workflow_dispatch` para una primera prueba manual.
7. Revisa los registros de ejecución y confirma que se descargan datos y que el bot puede enviar mensajes.

### Permisos del workflow

El workflow necesita permisos de escritura si va a guardar y subir cambios de `state.json` y `signals_history.jsonl` al repositorio. Comprueba que los permisos configurados en el YAML y los permisos del repositorio permiten esos commits.

## 4. Temporalidades y comportamiento

| Sistema | Temporalidades | Comportamiento |
|---|---|---|
| BitMan | H1, H4, D1 | Evalúa cambios de estado y condiciones de entrada/salida. |
| Koncorde | H1, H4, D1 | Detecta cruces y evalúa tres filtros. |
| Koncorde OBS | M15 | Observación y registro; no envía alertas de Telegram. |
| ML RSI | H1 | Observa los cambios de estado del RSI; los avisos intravela se identifican como provisionales. |

El script trabaja con velas cerradas para las evaluaciones confirmadas y, cuando está habilitada la detección intravela, utiliza la vela en curso para los avisos provisionales.

## 5. Alertas de Koncorde

El cruce se produce cuando la línea verde de Koncorde atraviesa la media amarilla:

- **Cruce alcista**: la línea verde cruza por encima de la media.
- **Cruce bajista**: la línea verde cruza por debajo de la media.

La evaluación incluye tres filtros:

1. **Valor de la línea verde**: clasifica el valor como dentro del rango, extendido o contrario a la dirección.
2. **Trend Speed Analyzer (TSA)**: comprueba si su dirección acompaña al cruce.
3. **ADX y DI**: comprueba el nivel mínimo de ADX y que DI+ o DI− domine en la dirección evaluada.

La clasificación del valor verde distingue entre `dentro`, `extendido` y `contrario`. Un valor extendido puede seguir contando como favorable si mantiene la coherencia direccional; no debe interpretarse automáticamente como un filtro fallido.

### Estados de los avisos

- **PROVISIONAL**: se ha detectado un cruce en una vela todavía abierta. Se muestran los tres filtros y el recuento de condiciones favorables.
- **CONFIRMADA**: al cierre, el cruce sigue vigente y cumple al menos dos de los tres filtros.
- **NO CONFIRMADA**: al cierre, el cruce sigue vigente, pero cumple menos de dos filtros.
- **INVALIDADA**: el cruce provisional desaparece o se invierte antes de la resolución.

La alerta de resolución debe corresponder al evento provisional que la originó. Si se producen varios cruces intravela, cada evento debe conservar su propia referencia para evitar asociar una confirmación al cruce equivocado.

**Frecuencia de evaluación:** el workflow ejecuta el ciclo aproximadamente cada cinco minutos. La detección intravela solo puede reaccionar en los momentos en que el script vuelve a ejecutarse; no es un flujo tick a tick.

## 6. Filtros de Koncorde: interpretación

El resultado se expresa como `0/3`, `1/3`, `2/3` o `3/3`.

- `3/3`: los tres filtros son favorables.
- `2/3`: dos filtros son favorables.
- `1/3` o `0/3`: no alcanza el umbral de confirmación establecido.

Los mensajes deben mostrar el estado individual de cada filtro, también cuando sea desfavorable. Así se puede distinguir entre un cruce que aparece con fuerza y otro que todavía no tiene suficiente respaldo.

## 7. BitMan e indicador de volatilidad BBWP

BitMan analiza H1, H4 y D1. Sus mensajes identifican el cambio de estado y muestran los valores de AO, Koncorde, ADX y BBWP.

Los iconos visuales ayudan a interpretar el mensaje:

- 🟢 **COMPRAR**: estado o transición alcista.
- 🔴 **VENDER**: estado o transición bajista.
- ⏸️ **ESPERAR**: no hay una condición operativa alineada.
- 🧊 / 🔵 **BBWP bajo**: volatilidad comprimida o reducida.
- 🟡 **BBWP medio**: volatilidad intermedia.
- 🟠 **BBWP alto**: volatilidad elevada.
- 🔴 **BBWP extremo**: volatilidad muy elevada.

BBWP describe la posición relativa de la volatilidad; no predice por sí solo la dirección del precio ni garantiza que una señal sea tardía. Un valor alto o extremo advierte de que la volatilidad ya está elevada y puede justificar cautela con entradas tardías.

Los límites numéricos exactos de cada categoría deben ser los que estén implementados en el script. No deben deducirse únicamente del color del icono.

## 8. ML RSI

ML RSI se ejecuta en H1. Los avisos distinguen los estados de color y señalan explícitamente cuándo una lectura procede de una vela abierta y es provisional.

La configuración conocida del indicador es:

- RSI de longitud 27.
- Fuente `LOW`.
- Suavizado activado.
- Media de suavizado SMA de periodo 4.
- Clasificación mediante tres grupos.

La implementación del bot y la configuración de TradingView deben compararse parámetro por parámetro antes de afirmar que producen resultados idénticos.

## 9. Histórico y control de duplicados

- `state.json` conserva el estado necesario para que las ejecuciones sucesivas no repitan indiscriminadamente una misma alerta.
- `signals_history.jsonl` guarda el histórico de eventos.
- El histórico está pensado para conservar los datos de la señal y permitir evaluar su evolución posterior.

No borres estos archivos durante el funcionamiento normal: hacerlo puede reiniciar el estado de seguimiento y provocar alertas repetidas o pérdida de continuidad.

Si necesitas reiniciar el bot, haz antes una copia de seguridad de ambos archivos.

## 10. Diagnóstico

Si no llegan mensajes:

1. Abre **Actions → ejecución del workflow → logs**.
2. Comprueba que el workflow se ha ejecutado y que no hay errores de dependencias.
3. Revisa que Binance devuelve velas para las temporalidades configuradas.
4. Comprueba que los secretos de Telegram existen y corresponden al bot y chat correctos.
5. Verifica que el bot tiene permiso para escribir en el chat o grupo.
6. Comprueba `state.json`: el estado guardado puede indicar que una señal ya se notificó.
7. Revisa si el evento era provisional, confirmado o simplemente un cambio que no alcanzaba el umbral de filtros.

Si GitHub Actions no puede guardar el estado, revisa los permisos de escritura del workflow y las reglas de protección de la rama.

## 11. Seguridad y operación

- Mantén los secretos exclusivamente en GitHub Secrets.
- No incluyas tokens ni claves en capturas de pantalla o logs compartidos.
- Usa claves API de Binance con los permisos mínimos necesarios. Para lectura de mercado no se necesita habilitar operaciones de trading.
- Este bot genera avisos informativos; no ejecuta órdenes de compra o venta.
- Una alerta provisional puede desaparecer antes del cierre. No debe tratarse como una confirmación.
- Comprueba los logs después de actualizar el script o el workflow.

## 12. Lista de comprobación antes de activar

- [ ] `koncorde_alert.py` está en la raíz del repositorio.
- [ ] El workflow está en `.github/workflows/koncorde.yml`.
- [ ] Los secretos requeridos por el script están configurados en GitHub.
- [ ] El workflow tiene los permisos necesarios para persistir estado e histórico.
- [ ] La ejecución manual termina sin errores.
- [ ] Se reciben mensajes de prueba en Telegram.
- [ ] Se verifica que los avisos provisionales y sus resoluciones se corresponden.
- [ ] Se confirma que M15 permanece en modo observación.
- [ ] Se conserva una copia de seguridad de `state.json` y `signals_history.jsonl`.

---

**Nota de versión:** este README debe mantenerse sincronizado con `koncorde_alert.py` y `koncorde.yml`. Si cambian los nombres de secretos, los umbrales, los iconos o la lógica de las alertas, actualiza también esta documentación.

## 13. Persistencia y relanzamiento automático del workflow

El workflow sincroniza la rama antes de cada ciclo y, cuando hay cambios en `state.json` o `signals_history.jsonl`, crea un commit y reintenta el `push` hasta tres veces. Si el push falla, intenta actualizar la rama y reaplicar el commit antes del siguiente intento. Los conflictos que no se puedan resolver automáticamente provocan un fallo visible del job; no se consideran guardados.

Al terminar el bucle, el workflow solicita una nueva ejecución mediante la API de GitHub Actions. La respuesta HTTP se comprueba explícitamente: `204` indica que GitHub aceptó el `workflow_dispatch`. Otros códigos muestran el cuerpo de error para facilitar el diagnóstico. El relanzamiento requiere que el workflow se llame exactamente `koncorde.yml` y que `GITHUB_TOKEN` tenga permiso `actions: write`.

El grupo de concurrencia `koncorde-loop` evita que dos ejecuciones de este bucle trabajen simultáneamente. Una nueva ejecución solicitada mientras otra sigue activa puede quedar pendiente hasta que termine la actual.
