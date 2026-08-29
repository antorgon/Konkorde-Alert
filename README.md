# Koncorde Alert (GitHub Actions, auto-perpetuo)

Revisa el Koncorde de BTCUSDT en 3 temporalidades (1h, 4h y 1d) cada 10
minutos y te avisa por Telegram.
Corre gratis en los servidores de GitHub, indefinidamente, sin que tengas
que tener tu ordenador encendido ni depender de ningún servicio externo.

## Por qué funciona así (y no con un simple `schedule`)

El `schedule` nativo de GitHub Actions (el cron estándar) resultó ser poco
fiable para este repo: se retrasaba horas o directamente se saltaba
ejecuciones (es un problema conocido de la plataforma en repos nuevos/de
bajo trafico, no de esta configuración). La solución fue un **workflow
auto-perpetuo**:

- Se arranca una vez (a mano, con "Run workflow").
- Dentro, un bucle comprueba el Koncorde cada 10 minutos durante ~5h40m (el
  máximo que permite una sola ejecución de GitHub Actions son 6h).
- Justo antes de acabar, el propio workflow se vuelve a lanzar a sí mismo
  vía la API de GitHub (usando el token que GitHub ya proporciona
  automáticamente, sin necesidad de crear ningún token ni cuenta externa).
- Así se encadena para siempre.
- Como red de seguridad, hay además un `schedule` de 1 vez al día, por si
  la cadena se llegara a romper alguna vez (fallo, cancelación, etc.). Un
  bloqueo de `concurrency` evita que esto cree una segunda cadena en
  paralelo si la anterior sigue viva.

**Importante**: el repositorio tiene que ser **público** para que esto
salga gratis. En un repo privado, tener un job corriendo casi 24/7 consume
muchísimos minutos de Actions y se agotaría el cupo gratuito del plan
(2.000 min/mes) enseguida.

## Temporalidades

Cada pasada revisa **1h, 4h y 1d** de forma independiente (cada una con su
propio calculo de Koncorde, Trend Speed Analyzer y ADX, y su propio control
anti-duplicados en `state.json`). Un cruce en una temporalidad no afecta ni
se mezcla con las demas. Para añadir o quitar temporalidades, edita la
lista al principio de `koncorde_alert.py`:
```python
INTERVALS = ["1h", "4h", "1d"]
```

**Sobre la frecuencia de chequeo (10 min)**: como la vela más corta es de
1h, revisar cada 10 min ya garantiza detectar el cierre de cada vela de las
3 temporalidades bastante antes de que llegue la siguiente -- en teoría no
debería perderse ningún cambio real por frecuencia. La única forma real de
perderse algo es que el propio workflow tenga algún hueco de inactividad
(fallo puntual, cancelación) más largo que el periodo de una vela; en ese
caso, cualquier cambio de estado que fuera y volviera dentro de ese hueco
sería invisible (solo se compara la última vela cerrada contra la
anterior, no el histórico completo). Un intervalo más corto reduce ese
riesgo marginalmente, pero la protección real viene de que el workflow no
tenga huecos (ver más arriba el sistema auto-perpetuo + red de seguridad).

## Qué avisos manda

Por cada cruce detectado (en cualquiera de las 3 temporalidades) se envían
hasta **2 mensajes**, indicando siempre a que temporalidad corresponde
(ej. "Koncorde BTCUSDT 4h"). Cada mensaje termina con un resumen del
estado actual de las **otras 2 temporalidades** (posición y nº de
condiciones cumplidas ahora mismo, aunque no tengan cruce), para tener
contexto completo sin tener que juntar varios mensajes. "Alcista"/"bajista"
llevan 🟢/🔴 delante -- Telegram no admite texto de color real en mensajes
de bot, es el sustituto habitual.

1. **Aviso del cruce** (siempre que hay cruce), con el desglose de las
   3 condiciones en ese mismo mensaje:
   - *Verde entra en la montaña* — cruce al alza de verde sobre media.
   - *Verde sale de la montaña* — cruce a la baja de verde bajo media.
2. **Aviso adicional**, según cuántas de las 3 condiciones se cumplan:
   - **3/3 → "CONFIRMADA"**: valor + Trend Speed Analyzer + ADX, las 3 a
     favor de la misma dirección del cruce.
   - **2/3 → "PARCIAL"**: solo 2 de las 3 (indica cuál falta).
   - **0/3 o 1/3 → sin segundo mensaje** (solo queda el desglose del primero).

Las 3 condiciones:
- El valor de `verde` en el momento del cruce tiene 3 estados posibles:
  🟢 **dentro** del rango validado (25-50 alza / ≤-25 baja, cuenta como
  cumplida), 🟡 **extendido** (fuera del rango pero en la misma dirección —
  sin ventaja estadística demostrada, pero también cuenta como cumplida,
  por decisión explícita de aceptar el riesgo de esa falta de evidencia),
  o 🔴 **dirección contraria** al cruce (no cuenta).
- El **Trend Speed Analyzer (Zeiierman)** confirma la misma dirección
  (línea dinámica alcista para entradas, bajista para salidas).
- El **ADX** (fuerza de tendencia, fórmula de Wilder) está por encima de
  20 y el DI dominante coincide con la dirección del cruce.

## Cómo se ajustaron los rangos de valor

El rango del filtro de `verde` empezó siendo una suposición (0-50 para alza,
venía de una formación externa; -50/0 para baja, una extrapolación propia
sin base real). Se validó con `analisis_valor_verde.py`, que descarga
histórico real de BTCUSDT y mide, para cada cruce pasado, si el precio se
movió a favor en las siguientes 24h, agrupado por rango de valor. Con casi
todo el histórico disponible de Binance (~10 años, miles de cruces):

- **Alza**: el rango 25-50 rindió consistentemente mejor (~55-56% de
  aciertos) que 0-25 o >50 (~49-51%, indistinguible del azar), en 3
  muestras de tamaño creciente (2, 6 y 10 años).
- **Baja**: resultó ser justo lo contrario a lo asumido — cruces con
  `verde <= -25` rindieron mejor (~63-68% de aciertos) que cruces cerca de
  0, que rindieron peor que el azar (~40%). Por eso "baja" no tiene límite
  inferior.

La muestra de "baja" es bastante más pequeña que la de "alza" (decenas de
casos frente a más de mil), así que esa señal tiene menos respaldo
estadístico aunque el patrón fue consistente en las 3 mediciones. Y como
con cualquier análisis histórico: rendimiento pasado no garantiza nada
hacia adelante. Para relanzar el análisis (por ejemplo si quieres probar
otro horizonte de medida, no solo 24h): **Actions -> Analisis Valor Verde
-> Run workflow**.

## Puesta en marcha (una sola vez)

1. **Crea un repositorio nuevo y público** en GitHub.
2. Sube estos archivos manteniendo la estructura de carpetas:
   ```
   .github/workflows/koncorde.yml
   koncorde_alert.py
   requirements.txt
   state.json
   ```
   (En GitHub: "Add file" -> "Upload files", arrastra la carpeta, o usa git
   desde tu ordenador si prefieres. Para el archivo dentro de
   `.github/workflows/` usa "Add file" -> "Create new file" y escribe la
   ruta completa.)
3. Ve a **Settings -> Secrets and variables -> Actions -> New repository secret**
   y crea dos secrets:
   - `TELEGRAM_TOKEN` -> el token de tu bot
   - `TELEGRAM_CHAT_ID` -> tu chat_id
4. Ve a la pestaña **Actions** del repositorio. Si te pregunta, habilita los
   workflows.
5. **Actions -> Koncorde Alert -> Run workflow**. Esto arranca la primera
   cadena, que se mantendrá viva sola de ahí en adelante (verás el círculo
   amarillo de "en curso" durante ~5h40m antes de que se relance sola).

## Comprobar que sigue viva

Entra en la pestaña Actions:
- Si hay una ejecución con el círculo amarillo girando ("en curso"), está
  funcionando.
- Si la última ejecución terminó (check verde) y hay otra nueva justo
  después, también está funcionando: se relanzó sola.
- Si la última ejecución terminó y no hay ninguna después de varias horas,
  algo falló — revisa el log del último paso ("Relanzar el siguiente
  ciclo") o simplemente vuelve a darle a "Run workflow" para reiniciar la
  cadena manualmente.

## Sistema 2: Bitman (COMPRAR / VENDER / ESPERAR)

Además de las alertas de cruce, hay un **segundo sistema de avisos totalmente
independiente** (los mensajes de Telegram empiezan por "Bitman"), basado en
un panel de trading que se compartió como referencia. A diferencia del
sistema de cruces (que avisa en el instante exacto en que `verde` cruza
`media`), este evalúa un **estado** en cada vela y solo avisa cuando ese
estado **cambia**. Sigue el criterio de 3 pasos descrito para leer las
señales de ese panel -- tendencia, impulso, confirmación:

- **COMPRAR**: **tendencia** alcista (AO, Awesome Oscillator 5/34) +
  **impulso** (ADX subiendo) + **confirmación** (Koncorde "todo el valor",
  criterio Bitman: el mayor entre `verde`/`marron`, o el más negativo si
  ambos lo son) en positivo.
- **VENDER**: lo mismo pero en negativo.
- **ESPERAR**: cualquier otro caso, con un motivo explicado (sin impulso del
  ADX, en retroceso del AO, Koncorde sin confirmar, etc.).

El **BBWP** (volatilidad, 4º punto de ese criterio) es informativo en el
panel original y no participa en la lógica COMPRAR/VENDER/ESPERAR -- por
eso aquí tampoco se usa como condición que bloquea o cuenta, pero sí se
incluye como **línea informativa** en cada mensaje de Bitman (percentil de
anchura de Bandas de Bollinger): **<25%** compresión, **25-75%** normal,
**75-98%** volatilidad alta (posible entrada tardía), **≥98%** extrema.

Igual que en el sistema de cruces, cada mensaje termina con un resumen del
veredicto actual de las otras 2 temporalidades (🟢 COMPRAR / 🔴 VENDER /
⚪ ESPERAR).

Corre en las mismas 3 temporalidades (1h/4h/1d), con su propio control
anti-duplicados en `state.json` (clave `last_veredicto_{temporalidad}`).

Es la versión "Base" de ese panel — no incluye el filtro solo-largo, el
filtro de temporalidad superior encadenado (1h exige 4h y 1d alcistas a la
vez) ni el modelo de asignación de capital de la versión "Pro" del panel
original, para mantener el alcance similar al resto del sistema.

## Cambiar de par o de temporalidades

Edita en `koncorde_alert.py`:
```python
SYMBOL = "BTCUSDT"
INTERVALS = ["1h", "4h", "1d"]
```
Y en `.github/workflows/koncorde.yml`, la línea `sleep 600` (segundos =
10 min) dentro del bucle, si quieres otra frecuencia de chequeo.

## Notas

- `state.json` guarda, por separado, la última vela ya avisada para cada
  combinación de temporalidad y tipo de aviso (cruce alza/baja + parcial
  alza/baja + confirmado alza/baja = 6 tipos × 3 temporalidades = hasta 18
  claves), para no repetir mensajes. El propio workflow lo actualiza y lo
  commitea solo, no lo toques a mano.
- La fórmula del Koncorde usada es una reconstrucción de código abierto de
  la comunidad (la versión 2.0 oficial de Blai5 es código cerrado), así que
  puede haber pequeñas diferencias frente a TradingView, aunque los cruces
  deberían coincidir en la gran mayoría de los casos.
- El Trend Speed Analyzer y el ADX sí son réplicas exactas de sus fórmulas
  originales (Trend Speed Analyzer: Zeiierman, CC BY-NC-SA 4.0; ADX: fórmula
  estándar de Wilder / `ta.dmi` de Pine), no aproximaciones.
- Las 3 peticiones a Binance de cada pasada (una por temporalidad, compartida
  entre los 2 sistemas de aviso -- antes cada sistema descargaba y calculaba
  por su cuenta, el doble de peticiones) reutilizan la misma conexión HTTPS
  (`requests.Session`).
