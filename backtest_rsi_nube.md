# Backtest independiente RSI + Nube — BTCUSDT (~10 años, comision 0.06%/operacion)

Metodologia propia, no la tabla interna del Pine Script. 3 variantes por
configuracion: **bolitas** (solo cruce de EMAs del RSI), **nivel** (solo
RSI>50), **combinado** (las dos a la vez -- la señal real que usa el
indicador para sus alertas).

## 1h · RSI(500) nube 36/84 nivel 50

| Sistema | Capital final | Retorno total | Buy&Hold | Sharpe | Max DD | Nº operaciones |
|---|---|---|---|---|---|---|
| bolitas | x24.96 | 2396.4% | 1611.6% | 1.03 | -54.0% | 850 |
| nivel | x30.33 | 2932.5% | 1611.6% | 1.04 | -79.3% | 1018 |
| combinado | x35.91 | 3491.0% | 1611.6% | 1.33 | -38.5% | 914 |

## 4h · RSI(89) nube 9/21 nivel 50

| Sistema | Capital final | Retorno total | Buy&Hold | Sharpe | Max DD | Nº operaciones |
|---|---|---|---|---|---|---|
| bolitas | x19.36 | 1836.2% | 596.9% | 1.04 | -54.6% | 817 |
| nivel | x25.86 | 2486.3% | 596.9% | 1.13 | -45.5% | 587 |
| combinado | x17.42 | 1641.6% | 596.9% | 1.22 | -33.1% | 705 |

_Compara el 'capital final' de cada fila contra la cifra reportada en la captura original (x25,60 en 1h, x29,72 en 4h) para ver si se sostiene con metodologia independiente. Sharpe > 1 se suele considerar bueno; > 2 muy bueno. Recuerda: esto no incluye slippage, solo comision._