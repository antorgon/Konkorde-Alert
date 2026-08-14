# Analisis del valor de 'verde' en los cruces — BTCUSDT 1h (ultimos 6 años)

Horizonte de medida: 24 velas (24h) tras el cruce.
`pct_a_favor` = % de cruces en ese rango donde el precio se movio a favor de la
direccion del cruce en ese horizonte. `retorno_medio_pct` = retorno medio a favor
(positivo = bien, negativo = el precio se movio en contra de media).

## Cruces alza

| Rango de verde | Nº cruces | % a favor | Retorno medio a favor |
|---|---|---|---|
| < -50 | 0 | nan% | nan% |
| -50 a -25 | 0 | nan% | nan% |
| -25 a 0 | 2 | 100.0% | 4.03% |
| 0 a 25 | 323 | 48.6% | -0.17% |
| 25 a 50 | 905 | 55.4% | 0.26% |
| > 50 | 2065 | 49.1% | 0.09% |

## Cruces baja

| Rango de verde | Nº cruces | % a favor | Retorno medio a favor |
|---|---|---|---|
| < -50 | 8 | 62.5% | 0.71% |
| -50 a -25 | 16 | 81.2% | 1.8% |
| -25 a 0 | 91 | 41.8% | 0.1% |
| 0 a 25 | 415 | 44.1% | -0.22% |
| 25 a 50 | 761 | 43.9% | -0.09% |
| > 50 | 2003 | 49.0% | -0.11% |

_Si el rango 0-50 (alza) / -50-0 (baja) es realmente el mejor, esas filas deberian tener el % a favor y el retorno medio mas altos dentro de su direccion. Si no es asi, el umbral deberia ajustarse al rango que de verdad rinda mejor en esta tabla._