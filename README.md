BOT BTCUSDT - VERSION REVISADA
Contenido
koncorde_alert.py: script actualizado.
koncorde.yml: workflow original, sin modificaciones.
Cambios principales
Koncorde H1/H4/D1: seguimiento intravela; solo avisos provisionales 2/3 y
3/3; sustitución del candidato válido; resolución única al cierre.
BitMan H1/H4/D1: cambios provisionales, retirada al volver a ESPERAR,
sustitución por dirección opuesta y resolución al cierre.
ML RSI H1: transiciones provisionales de color, retirada al volver a gris
y resolución al cierre.
M15: observación sin Telegram; histórico de cruces, filtros, distancia
verde-media y persistencia del cruce al cierre.
Histórico append-only, IDs de evento, marcas de detección/envío/cierre,
recuperación de candidatos pendientes y deduplicación mediante state.json.
Registro de errores, recuperación e interrupciones; resumen diario a las
08:00 Europe/Madrid del día natural anterior.
Se mantiene el ciclo de cinco minutos del workflow.
No se han modificado las fórmulas de los indicadores, los filtros ni los
umbrales. El workflow y su programación tampoco se han modificado.
Pruebas realizadas
Compilación Python: correcta.
Simulación Koncorde: provisional y resolución NO CONFIRMADA correctas.
Simulación BitMan: provisional y confirmación al cierre correctas.
Simulación ML RSI: transición provisional correcta.
Ejecución integral con datos sintéticos para 15m/1h/4h/1d: completada.
Comparación de bloques de cálculo originales: idénticos en las funciones
de cálculo comprobadas.
Antes de desplegar
Haz una copia de seguridad de state.json y signals_history.jsonl.
Sustituye el script del repositorio por koncorde_alert.py.
Conserva el workflow koncorde.yml actual.
No borres ni reinicies state.json ni signals_history.jsonl.
Observa primero las alertas y los registros; la distancia mínima
verde-media queda registrada para calibración futura, pero NO se aplica
como filtro activo.
Nota
Las pruebas se han hecho con datos sintéticos y no envían mensajes reales a
Telegram ni escriben consignas en equipos externos.
