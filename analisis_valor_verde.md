# Analisis del valor de 'verde' en los cruces — BTCUSDT 1h (ultimos 10 años)

Horizonte de medida: 24 velas (24h) tras el cruce.
`pct_a_favor` = % de cruces en ese rango donde el precio se movio a favor de la
direccion del cruce en ese horizonte. `retorno_medio_pct` = retorno medio a favor
(positivo = bien, negativo = el precio se movio en contra de media).

## Cruces alza

| Rango de verde | Nº cruces | % a favor | Retorno medio a favor |
|---|---|---|---|
| < -50 | 0 | nan% | nan% |
| -50 a -25 | 0 | nan% | nan% |
| -25 a 0 | 5 | 60.0% | 3.75% |
| 0 a 25 | 448 | 51.1% | 0.14% |
| 25 a 50 | 1352 | 56.5% | 0.33% |
| > 50 | 3145 | 49.3% | 0.12% |

## Cruces baja

| Rango de verde | Nº cruces | % a favor | Retorno medio a favor |
|---|---|---|---|
| < -50 | 19 | 63.2% | 1.18% |
| -50 a -25 | 28 | 67.9% | 1.26% |
| -25 a 0 | 118 | 39.8% | -0.08% |
| 0 a 25 | 604 | 40.4% | -0.46% |
| 25 a 50 | 1172 | 44.7% | -0.11% |
| > 50 | 3010 | 49.2% | -0.08% |

_Si el rango 0-50 (alza) / -50-0 (baja) es realmente el mejor, esas filas deberian tener el % a favor y el retorno medio mas altos dentro de su direccion. Si no es asi, el umbral deberia ajustarse al rango que de verdad rinda mejor en esta tabla._