# Bot de alertas BTCUSDT — revisión simplificada

## Archivos
- `koncorde_alert.py`: programa principal.
- `koncorde.yml`: workflow de GitHub Actions.
- `README.md`: documentación de esta revisión.

## Cambios

### Resumen diario de las 08:00 (Europe/Madrid)
El resumen muestra el estado actual de los sistemas, no estadísticas históricas:
- **BitMan H1/H4/D1:** veredicto, motivo, AO, ADX (si sube o no) y valor de Koncorde.
- **Koncorde H1/H4/D1:** posición verde/media, valores verde y media, distancia, resultado individual de los tres filtros y puntuación total. También indica si existe un candidato provisional pendiente.
- **ML RSI H1:** color actual y valor RSI.
- Distingue la hora de consulta de la vela analizada y señala si la vela está en curso o ya cerró.
- Los errores de datos activos se muestran al final.

### Eliminación de M15
Se ha eliminado M15 del procesamiento:
- No se descargan velas de 15 minutos.
- No se calculan indicadores M15.
- No se generan nuevos registros de observación M15.
- No aparece en el resumen diario.

Los registros M15 antiguos que ya existan en `signals_history.jsonl` se conservan; no se borran ni se reescriben. Las claves antiguas M15 que pudieran existir en `state.json` se ignoran.

### Simplificación del código
- Eliminada la primera implementación antigua que contenía un `main()` duplicado y quedaba sobrescrita por la arquitectura activa.
- Retiradas funciones de alertas y resúmenes de esa implementación anterior que ya no se utilizaban.
- Eliminadas las ramas exclusivas de observación M15.
- Se conserva el flujo activo de BitMan, Koncorde y ML RSI, el estado persistente y el histórico append-only.

## Elementos que se mantienen
- Fórmulas de BitMan, Koncorde, Trend Speed Analyzer, ADX y ML RSI.
- Filtros, umbrales y condiciones de señal.
- Temporalidades BitMan/Koncorde H1, H4 y D1; ML RSI H1.
- Alertas provisionales, sustituciones y resoluciones al cierre.
- `state.json` y `signals_history.jsonl`.
- Workflow de GitHub Actions y ciclo de cinco minutos.

## Validación realizada
- Compilación Python correcta.
- Comprobación de que queda una sola función `main()`.
- Comprobación de que no quedan referencias de ejecución a M15.
- Comparación de las funciones de cálculo y evaluación: sus cuerpos permanecen idénticos a los del archivo recibido.
- Prueba simulada del resumen diario: BitMan muestra motivo y valores; Koncorde muestra los tres filtros y su puntuación; no aparece M15.

No se ha realizado una prueba conectada a Binance ni un envío real a Telegram.

## Instalación
1. Guarda una copia de `state.json` y `signals_history.jsonl`.
2. Sustituye `koncorde_alert.py` por el incluido.
3. Conserva `koncorde.yml`; no requiere cambios.
4. No borres ni reinicies `state.json` ni `signals_history.jsonl`.
5. Comprueba el siguiente resumen diario y las alertas de las temporalidades activas.
