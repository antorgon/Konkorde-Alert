# Koncorde Alert (GitHub Actions, auto-perpetuo)

Revisa el Koncorde de BTCUSDT en 3 temporalidades (1h, 4h y 1d) cada 30
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
- Dentro, un bucle comprueba el Koncorde cada 30 minutos durante ~5h40m (el
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

## Qué avisos manda

Por cada cruce detectado (en cualquiera de las 3 temporalidades) se envían
hasta **2 mensajes**, indicando siempre a que temporalidad corresponde
(ej. "Koncorde BTCUSDT 4h"):

1. **Aviso del cruce** (siempre que hay cruce), con el desglose ✅/❌ de las
   3 condiciones en ese mismo mensaje:
   - *Verde entra en la montaña* — cruce al alza de verde sobre media.
   - *Verde sale de la montaña* — cruce a la baja de verde bajo media.
2. **Aviso adicional**, según cuántas de las 3 condiciones se cumplan:
   - **3/3 → "CONFIRMADA"**: valor + Trend Speed Analyzer + ADX, las 3 a
     favor de la misma dirección del cruce.
   - **2/3 → "PARCIAL"**: solo 2 de las 3 (indica cuál falta).
   - **0/3 o 1/3 → sin segundo mensaje** (solo queda el desglose del primero).

Las 3 condiciones:
- El valor de `verde` en el momento del cruce está entre **0 y 50** (alza)
  o entre **-50 y 0** (baja — rango simétrico asumido, el criterio
  original solo describe el caso alcista).
- El **Trend Speed Analyzer (Zeiierman)** confirma la misma dirección
  (línea dinámica alcista para entradas, bajista para salidas).
- El **ADX** (fuerza de tendencia, fórmula de Wilder) está por encima de
  20 y el DI dominante coincide con la dirección del cruce.

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

## Cambiar de par o de temporalidades

Edita en `koncorde_alert.py`:
```python
SYMBOL = "BTCUSDT"
INTERVALS = ["1h", "4h", "1d"]
```
Y en `.github/workflows/koncorde.yml`, la línea `sleep 1800` (segundos =
30 min) dentro del bucle, si quieres otra frecuencia de chequeo.

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
- Las 3 peticiones a Binance de cada pasada (una por temporalidad) reutilizan
  la misma conexión HTTPS (`requests.Session`), en vez de abrir una nueva
  por cada una.
