# Analisis del valor de 'verde' en los cruces — BTCUSDT 1h (ultimos 10 años)

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
| -25 a 0 | 5 | 60.0% | 0.45 | 3.75% |
| 0 a 25 | 449 | 51.2% | 0.51 | 0.14% |
| 25 a 50 | 1353 | 56.5% | 4.78 | 0.33% |
| 50 a 100 | 2595 | 49.7% | -0.31 | 0.09% |
| 100 a 200 | 556 | 47.3% | -1.27 | 0.26% |
| > 200 | 4 | 50.0% | 0.00 | 1.05% |

## Cruces baja

| Rango de verde | Nº cruces | % a favor | z | Retorno medio a favor |
|---|---|---|---|---|
| < -200 | 2 | 50.0% | 0.00 | 0.12% |
| -200 a -100 | 3 | 66.7% | 0.58 | 0.99% |
| -100 a -50 | 14 | 64.3% | 1.07 | 1.37% |
| -50 a -25 | 28 | 67.9% | 1.89 | 1.26% |
| -25 a 0 | 118 | 39.8% | -2.22 | -0.08% |
| 0 a 25 | 607 | 40.4% | -4.73 | -0.46% |
| 25 a 50 | 1173 | 44.8% | -3.56 | -0.11% |
| 50 a 100 | 2740 | 49.3% | -0.73 | -0.06% |
| 100 a 200 | 278 | 47.1% | -0.97 | -0.37% |
| > 200 | 0 | - | - | - |

_Si el rango 25-50 (alza) / <=-25 (baja) es realmente el mejor, esas filas deberian tener el % a favor, el z-score y el retorno medio mas altos dentro de su direccion. Presta especial atencion a si las zonas extremas (50-100, 100-200, >200 / sus equivalentes negativas) rinden distinto entre si -- eso indicaria si 'moderadamente extendido' y 'muy extendido' deberian tratarse como cosas distintas en vez de un unico bucket '>50'._