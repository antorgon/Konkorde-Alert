# Koncorde Alert (GitHub Actions)

Revisa cada hora el Koncorde de BTCUSDT (1H) y te avisa por Telegram en dos
casos:
- **Verde entra en la montaña** — cruce al alza de verde sobre media.
- **Verde sale de la montaña** — cruce a la baja de verde bajo media.

Corre gratis en los servidores de GitHub, no necesitas tener tu ordenador
encendido.

## Puesta en marcha (una sola vez)

1. **Crea un repositorio nuevo** en GitHub (puede ser privado).
2. Sube estos 4 archivos manteniendo la estructura de carpetas:
   ```
   .github/workflows/koncorde.yml
   koncorde_alert.py
   requirements.txt
   state.json
   ```
   (En GitHub: "Add file" -> "Upload files", arrastra la carpeta, o usa git
   desde tu ordenador si prefieres.)
3. Ve a **Settings -> Secrets and variables -> Actions -> New repository secret**
   y crea dos secrets:
   - `TELEGRAM_TOKEN` -> el token de tu bot
   - `TELEGRAM_CHAT_ID` -> `108046855`
4. Ve a la pestaña **Actions** del repositorio. Si te pregunta, habilita los
   workflows.
5. Para probar que funciona sin esperar a que llegue la hora en punto: pestaña
   **Actions -> Koncorde Alert -> Run workflow** (botón "Run workflow" a la
   derecha). Ejecuta el chequeo al momento.

A partir de aquí se ejecuta solo, cada hora, para siempre (o hasta que lo
pares desactivando el workflow).

## Cambiar de par o de intervalo

Edita en `koncorde_alert.py`:
```python
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
```
Y ajusta el cron en `.github/workflows/koncorde.yml` si cambias el intervalo
(por ejemplo `"*/15 * * * *"` para velas de 15 minutos).

## Notas

- El archivo `state.json` guarda la ultima vela ya avisada para cada tipo
  de cruce (entrada y salida) por separado, para no mandarte el mismo aviso
  repetido; el propio workflow lo actualiza y lo commitea solo, no lo
  toques a mano.
- La formula del Koncorde usada es una reconstruccion de codigo abierto de
  la comunidad (la version 2.0 oficial de Blai5 es codigo cerrado), asi que
  puede haber pequeñas diferencias frente a TradingView, aunque los cruces
  deberian coincidir en la gran mayoria de los casos.
- GitHub Actions en repos publicos es gratis sin limite practico para esto;
  en repos privados hay minutos gratis de sobra al mes para una tarea tan
  ligera (unos segundos por ejecucion, 24 veces al dia).
