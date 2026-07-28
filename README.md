# Koncorde Alert (GitHub Actions)

Revisa el Koncorde de BTCUSDT (1H) cada 30 minutos y te avisa por Telegram.
Corre gratis en los servidores de GitHub, no necesitas tener tu ordenador
encendido.

## Qué avisos manda

Por cada cruce detectado se envían hasta **2 mensajes independientes**:

1. **Aviso inmediato del cruce** (como el original):
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

1. **Crea un repositorio nuevo** en GitHub (puede ser privado).
2. Sube estos archivos manteniendo la estructura de carpetas:
   ```
   .github/workflows/koncorde.yml
   .github/workflows/backtest.yml
   koncorde_alert.py
   backtest_koncorde.py
   requirements.txt
   requirements-backtest.txt
   state.json
   ```
   (En GitHub: "Add file" -> "Upload files", arrastra la carpeta, o usa git
   desde tu ordenador si prefieres. Para archivos dentro de `.github/workflows/`
   usa "Add file" -> "Create new file" y escribe la ruta completa.)
3. Ve a **Settings -> Secrets and variables -> Actions -> New repository secret**
   y crea dos secrets:
   - `TELEGRAM_TOKEN` -> el token de tu bot
   - `TELEGRAM_CHAT_ID` -> tu chat_id
4. Ve a la pestaña **Actions** del repositorio. Si te pregunta, habilita los
   workflows.
5. Para probar sin esperar: pestaña **Actions -> Koncorde Alert -> Run
   workflow**. Ejecuta el chequeo al momento.

A partir de aquí se ejecuta solo cada 30 minutos, para siempre (o hasta que
lo pares desactivando el workflow).

## Backtest de la estrategia

Hay un segundo workflow, **Backtest Koncorde**, que se lanza a mano desde
**Actions -> Backtest Koncorde -> Run workflow**. Descarga ~2 años de
histórico, simula la estrategia (entra en el cruce alcista, sale en el
bajista, con comisión del 0.1% por operación) y deja los resultados
commiteados en el propio repo:

- `backtest_results.md` — nº de operaciones, % de aciertos, rentabilidad
  total, drawdown máximo, comparación contra comprar-y-mantener.
- `backtest_equity.png` — gráfico de la curva de capital.

Nota: el backtest actual simula solo el cruce básico, todavía no aplica el
filtro de valor 0-50 ni la confirmación del Trend Speed Analyzer.

## Cambiar de par o de intervalo

Edita en `koncorde_alert.py`:
```python
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
```
Y ajusta el cron en `.github/workflows/koncorde.yml` si cambias el intervalo
o la frecuencia de chequeo (actualmente `"*/30 * * * *"`, cada 30 minutos).

## Notas

- `state.json` guarda, por separado, la última vela ya avisada para cada uno
  de los 4 tipos de aviso (cruce alza, cruce baja, confirmado alza,
  confirmado baja), para no repetir mensajes. El propio workflow lo
  actualiza y lo commitea solo, no lo toques a mano.
- La fórmula del Koncorde usada es una reconstrucción de código abierto de
  la comunidad (la versión 2.0 oficial de Blai5 es código cerrado), así que
  puede haber pequeñas diferencias frente a TradingView, aunque los cruces
  deberían coincidir en la gran mayoría de los casos.
- El Trend Speed Analyzer sí es una réplica exacta del Pine Script original
  (Zeiierman, licencia CC BY-NC-SA 4.0), no una aproximación.
- GitHub Actions en repos públicos es gratis sin límite práctico para esto;
  en repos privados hay minutos gratis de sobra al mes para una tarea tan
  ligera (unos segundos por ejecución, 48 veces al día).
