# Bot BTCUSDT — auditoría y limpieza de código

## Base revisada

Se ha utilizado como base `koncorde_alert_corregido.py`, que incluye el formato simplificado de Telegram y la protección para permitir una sola candidatura Koncorde por vela.

## Código retirado

Se eliminaron exclusivamente elementos que no tenían uso en el propio script:

1. **`_rsi()`**: función RSI basada en medias móviles simples. No tenía ninguna llamada ni referencia interna. El cálculo Koncorde activo utiliza `_rsi_wilder()`, que reproduce el RSI de Wilder requerido por la implementación.
2. **`hlc3` en `compute_koncorde()`**: variable calculada y nunca utilizada. El cálculo activo usa `tprice`.
3. **`prev_high` y `prev_low` en `compute_adx()`**: desplazamientos calculados pero no consumidos. Se conserva `prev_close`, que sí interviene en el True Range.
4. **`dx` en `compute_adx()`**: valor intermedio calculado pero no utilizado. La fórmula activa de ADX se mantiene exactamente como estaba.
5. **`icon` en `_process_ml_rsi()`**: variable asignada pero nunca utilizada en el mensaje ni en el registro del evento.

No se han eliminado funciones auxiliares que puedan ser llamadas por el propio programa, ni datos de auditoría que se escriben en `signals_history.jsonl`.

## Elementos preservados

- Fórmulas y parámetros de Koncorde, TSA, ADX/DI, AO, BBWP y ML RSI.
- Umbrales y filtros existentes.
- Temporalidades e intervalos configurados.
- Detección de eventos Koncorde y protección contra candidaturas repetidas dentro de una misma vela.
- BitMan y ML RSI.
- Formato simplificado de alertas Telegram.
- Estructura y compatibilidad de `state.json` y `signals_history.jsonl`.

No se han modificado ni incluido los archivos persistentes.

## Pruebas realizadas

- Compilación sintáctica Python: correcta.
- Comparación numérica entre el script anterior y el limpio con un conjunto sintético de 500 velas: resultados idénticos (tolerancia numérica 1e-12) en `compute_koncorde`, `compute_trend_speed`, `compute_adx`, `compute_ao`, `compute_bbwp` y `compute_ml_rsi`.
- Comparación de la cadena completa `Koncorde → TSA → ADX → veredicto`: idéntica.
- Revisión estática de variables locales asignadas sin lectura: no quedan casos detectados.

No se han realizado llamadas reales a Binance, GitHub Actions ni Telegram. Tampoco se ha ejecutado una prueba integral de producción.

## Instalación

Sustituye el script Python que ejecuta el workflow por `koncorde_alert_limpio.py`, respetando el nombre de archivo que espere el workflow. Conserva los `state.json` y `signals_history.jsonl` actuales; no los reinicies.
