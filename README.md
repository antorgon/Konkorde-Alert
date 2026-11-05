Alerta Koncorde / BitMan / ML RSI — BTCUSDT
Estado de esta documentación
Esta documentación describe la versión preparada en koncorde_alert_implemented.py y koncorde_implemented.yml. Antes de activarla en el repositorio hay que revisar los archivos, ejecutar el workflow manualmente y validar los registros y mensajes reales.

La compilación sintáctica de Python y la comprobación del archivo YAML no equivalen a una prueba integral contra Binance, Telegram y GitHub Actions.
1. Sistemas y temporalidades
La configuración está separada por sistema:
Sistema	Temporalidades	Comportamiento
BitMan	H1, H4, D1	Evalúa velas cerradas y avisa cuando cambia el veredicto
Koncorde	H1, H4, D1	Evalúa cruces en velas cerradas; avisa con 2/3 o 3/3 filtros
Koncorde — observación	M15	Registra cruces cerrados en el histórico; no envía alertas
ML RSI	H1	Vigila la vela actual y avisa al cambiar a verde o rojo; el aviso es provisional


Las configuraciones están centralizadas en:
BITMAN_INTERVALS = ("1h", "4h", "1d")
KONCORDE_INTERVALS = ("1h", "4h", "1d")
KONCORDE_OBSERVE_INTERVALS = ("15m",)
ML_RSI_INTERVALS = ("1h",)
Los sistemas mantienen estados independientes. Una transición de BitMan no modifica el estado de Koncorde ni el de ML RSI.
2. Frecuencia de ejecución y tratamiento de velas
El workflow ejecuta el script cada cinco minutos durante un ciclo de aproximadamente 5 h 40 min y después intenta relanzar el siguiente ciclo mediante la API de GitHub Actions. También conserva un schedule diario como red de seguridad.

En cada pasada se descargan las temporalidades necesarias de Binance. La clasificación de vela cerrada o en curso se realiza utilizando el close_time devuelto por Binance.
- BitMan y Koncorde: procesan únicamente velas cerradas. Una misma vela no se vuelve a procesar en cada pasada.
- ML RSI (solo H1): usa la última vela disponible, incluida la vela en curso cuando Binance la devuelve. Por tanto, una transición verde/rojo puede revertirse antes del cierre y el mensaje se marca como provisional. No se calcula ni se muestra en D1.
- Koncorde M15: registra cruces cerrados en el histórico, pero no genera mensajes de Telegram.
La ejecución cada cinco minutos no significa que todas las temporalidades generen una señal cada cinco minutos: las decisiones de BitMan y Koncorde solo se actualizan cuando hay una nueva vela cerrada en su marco temporal.
3. BitMan
BitMan se calcula independientemente en H1, H4 y D1.

El veredicto implementado utiliza:
- Awesome Oscillator (AO) 5/34 y su estado.
- ADX de Wilder y comprobación de si está subiendo.
- Valor Koncorde (kon_val): el mayor entre verde y marrón, salvo cuando ambos son negativos, caso en el que se toma el más negativo.
- BBWP como información contextual; no bloquea el veredicto. Su porcentaje y nivel (extremo bajo, bajo, medio, alto o extremo alto) se incluyen en todas las alertas BitMan H1, H4 y D1.
Reglas:
- COMPRAR: AO en estado alcista, ADX subiendo y kon_val positivo.
- VENDER: AO en estado bajista, ADX subiendo y kon_val negativo.
- ESPERAR: cualquier otro caso.
El aviso se genera cuando cambia el veredicto respecto al último estado guardado. La primera lectura establece una referencia y no genera una alerta retrospectiva.

Esta implementación mantiene el criterio BitMan ya presente en el script original; no incorpora filtros Pro de temporalidad superior, solo-largo ni asignación de capital.
4. Koncorde
Koncorde operativo se calcula en H1, H4 y D1. El sistema detecta un cambio de posición de verde respecto a media comparando velas cerradas consecutivas.

Al detectar un cruce evalúa tres condiciones:
1. Valor verde. Para alza, el rango validado es 25–50. Para baja, el rango validado es ≤ -25. Un valor fuera de ese rango pero con el signo correcto se clasifica como extendido y sigue contando como condición cumplida, igual que en la lógica previa.
2. Trend Speed Analyzer (TSA). Debe apuntar en la dirección del cruce.
3. ADX/DI. ADX debe ser ≥ 20 y el DI dominante debe coincidir con la dirección del cruce.
Resultado:
- 3/3: alerta confirmada.
- 2/3: alerta parcial.
- 0/3 o 1/3: el cruce se registra, pero no genera alerta de Telegram.
Los umbrales de valor verde proceden del análisis histórico previo documentado en la versión original. Ese análisis se realizó con cruces cerrados de BTCUSDT y no garantiza resultados futuros.
M15 en observación
M15 utiliza el mismo cálculo de Koncorde y filtros para registrar los cruces cerrados. Se guarda como observación, sin avisos a Telegram. Su finalidad es estudiar si aporta anticipación respecto a H1 antes de decidir si debe convertirse en un marco operativo.
Control del ruido
La confirmación al cierre evita las oscilaciones intravela del cruce. Esta versión no introduce todavía umbrales adicionales de histéresis, distancia mínima entre líneas ni persistencia de varias velas. Esos parámetros deben estudiarse con el histórico antes de fijarlos. Por tanto, si el cruce se produce durante la vela de las 07:00, solo se notificará al cierre de esa vela (a las 08:00), y únicamente si el cruce sigue vigente al cierre.
5. ML RSI
ML RSI funciona de forma independiente únicamente en H1.

La fórmula conservada es:
- RSI de Wilder de longitud 27 calculado sobre el mínimo de la vela.
- Suavizado SMA(4).
- K-means unidimensional con tres centroides para obtener umbrales dinámicos.
- Clasificación verde, rojo o gris.
El sistema compara la clasificación viva con el último estado guardado:
- Al cambiar a verde, envía aviso.
- Al cambiar a rojo, envía aviso.
- Al cambiar a gris, actualiza el estado, pero no envía aviso.
Los avisos verde/rojo sobre una vela abierta se identifican como PROVISIONAL. El sistema registra también la clasificación de la última vela cerrada para permitir el análisis posterior.
6. Persistencia: estado e histórico
Se utilizan dos archivos distintos:
state.json
Guarda el estado operativo, entre otros:
- Última vela procesada por sistema y temporalidad.
- Último veredicto BitMan.
- Última posición Koncorde.
- Última clasificación viva y última vela cerrada de ML RSI.
- Identificadores recientes de eventos históricos.
- Señales pendientes de completar con resultados posteriores.
Se escribe de forma atómica para reducir el riesgo de dejar un JSON incompleto durante una interrupción.
signals_history.jsonl
Es un histórico acumulativo en formato JSON Lines: cada línea es un objeto JSON independiente. Incluye:
- Sistema y temporalidad.
- Tipo de evento y señal.
- Estado confirmado, parcial, provisional u observación.
- Hora UTC y precio de referencia.
- Valores de indicadores y filtros disponibles.
- Identificador de evento para relacionar registros posteriores.
Los resultados posteriores se añaden como nuevos registros asociados al evento original; no se reescribe la línea de señal inicial.
Seguimiento a futuro
El código contempla horizontes de 1, 3, 6, 12 y 24 horas. La medición se realiza en la primera ejecución posterior en la que se alcanza o supera cada horizonte, usando el precio H1 disponible en esa pasada. Por ello, no debe interpretarse como un precio exacto del segundo en que se cumple el horizonte.

El rendimiento porcentual registrado es el cambio de precio desde el precio de referencia. Para señales alcistas y bajistas se incluye una marca de acierto direccional. No se descuentan comisiones, spread, deslizamiento ni costes de ejecución; no es un backtest de una estrategia ejecutable.
7. GitHub Actions y conservación de datos
El workflow debe versionar ambos archivos en cada ciclo:
git add state.json signals_history.jsonl
El flujo realiza git pull --rebase antes de crear el commit y después intenta subirlo a la rama del workflow. Si falla la sincronización, hay riesgo de que los cambios del runner no lleguen al siguiente ciclo; hay que revisar los logs de pull y push.

Permisos declarados por el workflow:
- contents: write, para guardar estado e histórico en el repositorio.
- actions: write, para solicitar el siguiente ciclo.
El repositorio debe tener habilitados GitHub Actions y los permisos de escritura necesarios para el GITHUB_TOKEN. La disponibilidad de minutos gratuitos depende de si el repositorio es público o privado y de las condiciones vigentes de GitHub.
8. Instalación
1. Haz una copia de seguridad del script y workflow actuales.
2. Sustituye el archivo del repositorio koncorde_alert.py por el script preparado, renombrándolo exactamente a koncorde_alert.py.
3. Sustituye .github/workflows/koncorde.yml por el workflow preparado, conservando esa ruta.
4. Comprueba que requirements.txt incluye al menos requests, pandas y numpy.
5. En GitHub, abre Settings → Secrets and variables → Actions y verifica estos secrets:
   - TELEGRAM_TOKEN
   - TELEGRAM_CHAT_ID
6. Comprueba que el workflow tiene permisos de escritura para Contents y Actions.
7. Ejecuta Actions → Koncorde Alert → Run workflow manualmente.
8. Revisa los logs, los mensajes de Telegram, y que state.json y signals_history.jsonl se creen o actualicen y queden commiteados.
9. Solo después de verificar varios ciclos, deja activa la cadena de auto-relanzamiento.
No introduzcas las credenciales de Telegram directamente en el código ni en el README.
9. Validación antes de producción
La validación pendiente debe cubrir, como mínimo:
- Descarga real de H1, H4, D1 y M15 desde Binance.
- Que las velas abiertas no se procesan como cerradas para BitMan/Koncorde.
- Que una vela cerrada no dispara el mismo evento en dos pasadas.
- Que ML RSI H1 detecta transiciones vivas y no envía alertas al pasar a gris.
- Que M15 escribe observaciones y nunca envía alertas.
- Que un reinicio recupera el estado y no duplica eventos.
- Que el histórico se conserva tras git pull/`git push`.
- Que los resultados a 1/3/6/12/24 h se añaden una sola vez.
- Que los mensajes HTML son aceptados por Telegram y conservan negritas, emojis e indicadores visuales. Telegram no permite aplicar colores arbitrarios al texto normal: la codificación cromática se representa mediante emojis (🟢 🔴 🟡 ⚪) y formato HTML.
La prueba de compilación sintáctica, por sí sola, no cubre estos casos. No debe considerarse una validación integral ni una garantía de funcionamiento en producción.
10. Reversión
Si la nueva versión presenta problemas:
1. Detén o desactiva temporalmente el workflow.
2. Restaura la copia de seguridad de koncorde_alert.py y .github/workflows/koncorde.yml.
3. Conserva una copia de signals_history.jsonl antes de revertir, para no perder los registros acumulados.
4. Revisa el último log de Actions y el estado de los commits antes de reactivar la cadena.
11. Configuración principal
Símbolo:
SYMBOL = "BTCUSDT"
Temporalidades por sistema:
BITMAN_INTERVALS = ("1h", "4h", "1d")
KONCORDE_INTERVALS = ("1h", "4h", "1d")
KONCORDE_OBSERVE_INTERVALS = ("15m",)
ML_RSI_INTERVALS = ("1h",)
La frecuencia del bucle está definida en el workflow mediante sleep 300 (cinco minutos).
