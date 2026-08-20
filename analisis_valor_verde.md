# Analisis del valor de 'verde' en los cruces — BTCUSDT 1h (ultimos 5 años)

Horizonte de medida: 24 velas (24h) tras el cruce.
`pct_a_favor` = % de cruces en ese rango donde el precio se movio a favor de la
direccion del cruce en ese horizonte. `retorno_medio_pct` = retorno medio a favor
(positivo = bien, negativo = el precio se movio en contra de media).
`z` = z-score frente al 50% esperado por azar (con n grande, |z|>3 es solido,
|z|>2 es sugerente pero no concluyente, por debajo es indistinguible del azar).

## Cruces alza

| Rango de verde | Nº cruces | % a favor | z | Retorno medio a favor |
|---|---|---|---|---|
| < -200 | 0 | - | - | - |
| -200 a -100 | 0 | - | - | - |
| -100 a -50 | 0 | - | - | - |
| -50 a -25 | 0 | - | - | - |
| -25 a 0 | 2 | 100.0% | 1.41 | 4.03% |
| 0 a 25 | 277 | 48.0% | -0.67 | -0.28% |
| 25 a 50 | 765 | 54.5% | 2.49 | 0.19% |
| 50 a 100 | 1413 | 47.8% | -1.65 | -0.02% |
| 100 a 200 | 296 | 49.7% | -0.10 | 0.32% |
| > 200 | 3 | 33.3% | -0.58 | -0.33% |

## Cruces baja

| Rango de verde | Nº cruces | % a favor | z | Retorno medio a favor |
|---|---|---|---|---|
| < -200 | 2 | 50.0% | 0.00 | 0.12% |
| -200 a -100 | 0 | - | - | - |
| -100 a -50 | 6 | 66.7% | 0.82 | 0.9% |
| -50 a -25 | 14 | 85.7% | 2.67 | 2.1% |
| -25 a 0 | 82 | 43.9% | -1.10 | 0.24% |
| 0 a 25 | 361 | 45.7% | -1.63 | -0.12% |
| 25 a 50 | 640 | 43.6% | -3.24 | -0.06% |
| 50 a 100 | 1509 | 49.6% | -0.31 | -0.06% |
| 100 a 200 | 143 | 49.0% | -0.24 | 0.04% |
| > 200 | 0 | - | - | - |

_Si el rango 25-50 (alza) / <=-25 (baja) es realmente el mejor, esas filas deberian tener el % a favor, el z-score y el retorno medio mas altos dentro de su direccion. Presta especial atencion a si las zonas extremas (50-100, 100-200, >200 / sus equivalentes negativas) rinden distinto entre si -- eso indicaria si 'moderadamente extendido' y 'muy extendido' deberian tratarse como cosas distintas en vez de un unico bucket '>50'._