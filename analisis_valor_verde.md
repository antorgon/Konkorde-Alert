# Analisis del valor de 'verde' en los cruces — BTCUSDT 1h (ultimos 2 años)

Horizonte de medida: 24 velas (24h) tras el cruce.
`pct_a_favor` = % de cruces en ese rango donde el precio se movio a favor de la
direccion del cruce en ese horizonte. `retorno_medio_pct` = retorno medio a favor
(positivo = bien, negativo = el precio se movio en contra de media).

## Cruces alza

| Rango de verde | Nº cruces | % a favor | Retorno medio a favor |
|---|---|---|---|
| < -50 | 0 | nan% | nan% |
| -50 a -25 | 0 | nan% | nan% |
| -25 a 0 | 1 | 100.0% | 7.24% |
| 0 a 25 | 126 | 47.6% | -0.13% |
| 25 a 50 | 283 | 53.4% | 0.17% |
| > 50 | 643 | 49.0% | -0.01% |

## Cruces baja

| Rango de verde | Nº cruces | % a favor | Retorno medio a favor |
|---|---|---|---|
| < -50 | 5 | 80.0% | 1.39% |
| -50 a -25 | 4 | 75.0% | 0.51% |
| -25 a 0 | 37 | 37.8% | -0.57% |
| 0 a 25 | 140 | 52.9% | -0.07% |
| 25 a 50 | 229 | 46.7% | -0.03% |
| > 50 | 637 | 47.4% | -0.09% |

_Si el rango 0-50 (alza) / -50-0 (baja) es realmente el mejor, esas filas deberian tener el % a favor y el retorno medio mas altos dentro de su direccion. Si no es asi, el umbral deberia ajustarse al rango que de verdad rinda mejor en esta tabla._