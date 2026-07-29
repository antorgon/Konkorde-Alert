# Koncorde Alert (GitHub Actions, auto-perpetuo)

Revisa el Koncorde de BTCUSDT (1H) cada 30 minutos y te avisa por Telegram.
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

## Qué avisos manda

Por cada cruce detectado se envían hasta **2 mensajes independientes**:

1. **Aviso inmediato del cruce**:
   - *Verde entra en la montaña* — cruce al alza de verde sobre media.
   - *Verde sale de la montaña* — cruce a la baja de verde bajo media.
2. **Aviso de confirmación** (solo si además se cumplen estas 2 condiciones):
   - El valor de `verde` en el momento del cruce está entre **0 y 50** (alza)
     o entre **-50 y 0** (baja — rango simétrico asumido, el criterio
     original solo describe el caso alcista).
   - El **Trend Speed Analyzer (Zeiierman)** confirma la misma dirección
     (línea dinámica alcista para entradas, bajista para salidas).

Si solo se cumple el cruce, llega el primer mensaje y no el segundo.

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

## Cambiar de par o de intervalo

Edita en `koncorde_alert.py`:
```python
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
```
Y en `.github/workflows/koncorde.yml`, la línea `sleep 1800` (segundos =
30 min) dentro del bucle, si quieres otra frecuencia de chequeo.

## Notas

- `state.json` guarda, por separado, la última vela ya avisada para cada
  uno de los 4 tipos de aviso (cruce alza, cruce baja, confirmado alza,
  confirmado baja), para no repetir mensajes. El propio workflow lo
  actualiza y lo commitea solo, no lo toques a mano.
- La fórmula del Koncorde usada es una reconstrucción de código abierto de
  la comunidad (la versión 2.0 oficial de Blai5 es código cerrado), así que
  puede haber pequeñas diferencias frente a TradingView, aunque los cruces
  deberían coincidir en la gran mayoría de los casos.
- El Trend Speed Analyzer sí es una réplica exacta del Pine Script original
  (Zeiierman, licencia CC BY-NC-SA 4.0), no una aproximación.
