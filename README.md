# Bot de alertas BTCUSDT — revisión v5

## Archivos
- `koncorde_alert.py`: programa principal.
- `koncorde.yml`: workflow de GitHub Actions.
- `README.md`: documentación de esta revisión.

## Resumen diario de las 08:00 (Europe/Madrid)
El resumen se ha simplificado para mostrar solo la información operativa:
- Cabecera con el precio actual de BTCUSDT, sin una segunda línea de fecha y hora.
- **BitMan H1/H4/D1:** veredicto y motivo; AO solo como estado, ADX solo como tendencia y Koncorde como entrada/salida de zona positiva o montaña positiva/negativa. Añade BBWP como referencia informativa de volatilidad.
- **Koncorde H1/H4/D1:** una única línea por temporalidad con posición, puntuación de filtros y explicación breve de cada filtro.
- **ML RSI H1:** color y RSI.
- Se eliminan del resumen las referencias a las velas analizadas, sus cierres, el apartado de funcionamiento y los datos repetidos de AO/ADX/Koncorde.

El BBWP se presenta únicamente como información de volatilidad. No participa en las señales ni modifica los filtros.

## Eliminación de M15
Se ha eliminado M15 del procesamiento:
- No se descargan velas de 15 minutos.
- No se calculan indicadores M15.
- No se generan nuevos registros de observación M15.
- No aparece en el resumen diario.

Los registros M15 antiguos que ya existan en `signals_history.jsonl` se conservan; no se borran ni se reescriben. Las claves antiguas M15 que pudieran existir en `state.json` se ignoran.

## Simplificación del código
- Se mantiene la eliminación de la implementación antigua duplicada y de las ramas de observación M15.
- Se retiran los auxiliares que solo servían para mostrar velas y estado de actualización en el resumen anterior.
- Se concentra el formato del resumen en funciones pequeñas y específicas.
- No se han eliminado funciones de cálculo ni de procesamiento que sigan siendo utilizadas.

## Elementos que se mantienen sin cambios
- Fórmulas de BitMan, Koncorde, Trend Speed Analyzer, ADX, BBWP y ML RSI.
- Filtros, umbrales y condiciones de señal.
- Temporalidades BitMan/Koncorde H1, H4 y D1; ML RSI H1.
- Alertas provisionales, sustituciones y resoluciones al cierre.
- `state.json` y `signals_history.jsonl`.
- Workflow de GitHub Actions y ciclo de cinco minutos.

## Validación realizada
- Compilación Python correcta.
- Comprobación de que queda una sola función `main()` y no quedan referencias activas a M15.
- Prueba simulada del nuevo resumen: precio con formato español, volatilidad BBWP, una línea por temporalidad de Koncorde y ausencia de fecha duplicada, velas y apartado de funcionamiento.
- No se han modificado las funciones de cálculo de indicadores ni los criterios de evaluación.
- ZIP comprobado.

No se ha realizado una prueba conectada a Binance ni un envío real a Telegram.

## Instalación
1. Guarda una copia de `state.json` y `signals_history.jsonl`.
2. Sustituye `koncorde_alert.py` por el incluido.
3. Conserva `koncorde.yml`; no requiere cambios.
4. No borres ni reinicies `state.json` ni `signals_history.jsonl`.
5. Comprueba el siguiente resumen diario y las alertas de las temporalidades activas.
