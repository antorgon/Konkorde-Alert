# Independencia del Trend Speed Analyzer — BTCUSDT 1h (ultimos 5 años)

Ventana de 'cerca en el tiempo': +/- 3 velas. Horizonte de retorno: 24 velas (24h) tras el cambio de estado del TSA.

- Días analizados: **1815**
- Cambios de estado del TSA: **1923** (1.06/día)
- Cruces del Koncorde en el mismo periodo: 5508
- Cambios de veredicto Bitman en el mismo periodo: 4287

- **Redundantes** (con un cruce/cambio de Bitman cerca): 1543 (80.2%)
- **Independientes** (el TSA se mueve solo, sin nada cerca): 380 (19.8%)

## ¿El precio se mueve a favor tras esos cambios?

`z` = z-score frente al 50% esperado por azar (|z|>3 solido, |z|>2 sugerente, por debajo indistinguible del azar).

| Grupo | Nº eventos | % a favor | Retorno medio a favor | z |
|---|---|---|---|---|
| Independientes | 380 | 42.6% | -0.17% | -2.87 |
| Redundantes | 1542 | 49.7% | 0.03% | -0.25 |

_Si los 'Independientes' tienen z solido (>3) y mejor % que los 'Redundantes', avisar de los cambios aislados del TSA aportaria valor real, no solo señales distintas sino señales BUENAS. Si el z es bajo o negativo, los cambios independientes no tienen ventaja demostrada -- confirmaria que no compensa añadirlos como aviso, aunque sean tecnicamente independientes de los otros 2 sistemas._