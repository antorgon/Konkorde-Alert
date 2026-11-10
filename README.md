BOT DE ALERTAS BTCUSDT — VERSIÓN ACTUALIZADA
Archivos del paquete
koncorde_alert.py: script principal actualizado.
koncorde.yml: workflow de GitHub Actions; se conserva sin cambios.
README.md: estas instrucciones.
Cambios de esta revisión
Resumen de las 08:00 (Europe/Madrid)
Ya no presenta recuentos del día anterior ni porcentajes de disponibilidad
calculados a partir de ciclos históricos.
Muestra una fotografía del estado disponible en el momento del envío:
BitMan H1/H4/D1, Koncorde H1/H4/D1, ML RSI H1 y observación Koncorde M15.
Indica la hora de la última lectura válida por temporalidad, los candidatos
provisionales pendientes y los errores de datos que sigan activos.
Todo el texto visible del resumen está en español.
Resolución de candidatos Koncorde
INVALIDADA: el cruce se marcó como invalidado o la dirección final es
contraria a la del candidato.
NO CONFIRMADA: el cruce se mantuvo, pero terminó con menos de 2/3 filtros.
NO VERIFICABLE: no se pudo recuperar la vela exacta del candidato tras
un hueco de datos; no se afirma que la señal haya sido invalidada.
CONFIRMADA: el candidato se mantuvo y conservó al menos 2/3 filtros.
Valor verde Koncorde
Se conserva el valor numérico capturado en el instante de detección.
Se muestra también el rango de referencia aplicable a la dirección.
La descripción de un valor contrario se precisa como “signo contrario a
la dirección del cruce”. No se cambian rangos, filtros ni cálculos.
Se mantienen sin cambios
Fórmulas de los indicadores, filtros, umbrales y condiciones de estrategia.
Temporalidades: BitMan y Koncorde H1/H4/D1; ML RSI H1; observación M15.
Frecuencia del workflow: ciclo de cinco minutos.
Histórico append-only y estado persistente.
Koncorde M15 continúa siendo observacional y no envía alertas operativas.
Pruebas realizadas en esta revisión
Compilación del script Python: correcta.
Pruebas simuladas de resolución: INVALIDADA, NO CONFIRMADA y NO VERIFICABLE.
Prueba simulada del resumen: muestra estados actuales en español, sin
estadísticas históricas en inglés ni porcentaje de disponibilidad.
No se ha realizado una prueba conectada a Binance ni un envío real a Telegram.
Antes de desplegar
Guarda una copia de state.json y signals_history.jsonl.
Sustituye koncorde_alert.py por el incluido en este paquete.
Conserva koncorde.yml; no necesita cambios.
No borres ni reinicies state.json ni signals_history.jsonl.
Comprueba el primer resumen y las siguientes resoluciones de Koncorde.
Nota
El resumen muestra el estado que el bot puede leer en el ciclo que coincide con
las 08:00 o el primer ciclo posterior. “Último dato válido” indica cuándo se
obtuvo correctamente la última lectura de esa temporalidad. Las pruebas son
sintéticas; no sustituyen la observación en producción.
