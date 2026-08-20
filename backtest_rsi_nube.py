"""
Backtest independiente del indicador "RSI + Nube · completo"
================================================================
Reproduce, con metodologia propia (no la tabla interna del propio Pine
Script), la rentabilidad teorica de los 2 sistemas que describe el
indicador, mas la combinacion real que usa para las alertas:

  - "bolitas":    posicion = dentro mientras la nube (EMA rapida del RSI >
                  EMA lenta del RSI) este verde. Long/flat, sin filtro de
                  nivel.
  - "nivel":      posicion = dentro mientras RSI > nivel (50 por defecto).
                  Independiente de la nube.
  - "combinado":  posicion = dentro solo cuando SE CUMPLEN LAS DOS a la vez
                  (esta es la señal real que usa el indicador para sus
                  alertcondition de entrada/salida, "dentro" en el Pine).

Se prueban las 2 configuraciones "ideales" reportadas para BTC:
  - 1h: RSI(500), EMA rapida 36, EMA lenta 84, nivel 50
  - 4h: RSI(89),  EMA rapida 9,  EMA lenta 21, nivel 50

Uso:
    pip install pandas requests numpy
    python backtest_rsi_nube.py

Genera: backtest_rsi_nube.md
"""

import time
from datetime import datetime, timezone

import requests
import pandas as pd
import numpy as np

SYMBOL = "BTCUSDT"
COMISION_PCT = 0.06     # % por operacion (entrada y salida por separado), igual que el Pine
YEARS_BACK = 10         # todo el historico disponible
WARMUP_CANDLES = 1000   # velas iniciales descartadas (el RSI(500) necesita mucho warmup)

BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"

CONFIGS = [
    {"interval": "1h", "rsi_len": 500, "ema_rap": 36, "ema_len": 84, "nivel": 50, "periodos_año": 24 * 365},
    {"interval": "4h", "rsi_len": 89, "ema_rap": 9, "ema_len": 21, "nivel": 50, "periodos_año": 6 * 365},
]


# --------------------------- DESCARGA PAGINADA ---------------------------
def get_historical_klines(symbol=SYMBOL, interval="1h", years_back=YEARS_BACK) -> pd.DataFrame:
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - years_back * 365 * 24 * 60 * 60 * 1000

    all_rows = []
    cursor = start_ms
    while cursor < end_ms:
        params = {"symbol": symbol, "interval": interval, "startTime": cursor, "limit": 1000}
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=20)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_rows.extend(batch)
        cursor = batch[-1][6] + 1
        if len(batch) < 1000:
            break
        time.sleep(0.15)

    df = pd.DataFrame(all_rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df = df.drop_duplicates(subset="close_time").reset_index(drop=True)
    return df[["close_time", "open", "high", "low", "close"]]


# --------------------------- INDICADOR ---------------------------
def _rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100 - (100 / (1 + rs))


def compute_rsi_nube(df: pd.DataFrame, rsi_len: int, ema_rap: int, ema_len: int, nivel: float) -> pd.DataFrame:
    df = df.copy()
    df["rsi"] = _rsi(df["close"], rsi_len)
    df["nube_r"] = df["rsi"].ewm(span=ema_rap, adjust=False).mean()
    df["nube_l"] = df["rsi"].ewm(span=ema_len, adjust=False).mean()
    df["verde"] = df["nube_r"] > df["nube_l"]
    df["dentro_nivel"] = df["rsi"] > nivel
    return df


# --------------------------- SIMULACION ---------------------------
def simular(df: pd.DataFrame, columna_posicion: str, periodos_año: int, comision_pct: float = COMISION_PCT) -> dict:
    """Simula capital siguiendo la columna booleana de posicion (True=dentro,
    False=fuera), aplicando comision en cada cambio de posicion."""
    pos = df[columna_posicion].astype(int).to_numpy()
    close = df["close"].to_numpy()

    ret_vela = np.diff(close) / close[:-1]
    pos_previa = pos[:-1]  # la posicion de la vela anterior determina el retorno de la vela actual

    cambios = np.diff(pos) != 0
    comision = comision_pct / 100

    equity = [1.0]
    n_trades = 0
    for i in range(len(ret_vela)):
        cap = equity[-1] * (1 + pos_previa[i] * ret_vela[i])
        if i < len(cambios) and cambios[i]:
            cap *= (1 - comision)
            n_trades += 1
        equity.append(cap)

    equity = pd.Series(equity)
    ret_estrategia = equity.pct_change().dropna()

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_dd = drawdown.min()

    sharpe = 0.0
    if ret_estrategia.std() > 0:
        sharpe = (ret_estrategia.mean() / ret_estrategia.std()) * np.sqrt(periodos_año)

    buy_hold_return = (close[-1] - close[0]) / close[0]

    return {
        "retorno_total_pct": (equity.iloc[-1] - 1) * 100,
        "buy_hold_pct": buy_hold_return * 100,
        "max_drawdown_pct": max_dd * 100,
        "sharpe": sharpe,
        "n_trades": n_trades,
        "capital_final_x": equity.iloc[-1],
    }


# --------------------------- INFORME ---------------------------
def guardar_informe(resultados: list):
    lineas = [
        f"# Backtest independiente RSI + Nube — {SYMBOL} (~{YEARS_BACK} años, comision {COMISION_PCT}%/operacion)",
        "",
        "Metodologia propia, no la tabla interna del Pine Script. 3 variantes por",
        "configuracion: **bolitas** (solo cruce de EMAs del RSI), **nivel** (solo",
        "RSI>50), **combinado** (las dos a la vez -- la señal real que usa el",
        "indicador para sus alertas).",
        "",
    ]
    for cfg_label, variantes in resultados:
        lineas.append(f"## {cfg_label}")
        lineas.append("")
        lineas.append("| Sistema | Capital final | Retorno total | Buy&Hold | Sharpe | Max DD | Nº operaciones |")
        lineas.append("|---|---|---|---|---|---|---|")
        for nombre, r in variantes:
            lineas.append(
                f"| {nombre} | x{r['capital_final_x']:.2f} | {r['retorno_total_pct']:.1f}% | "
                f"{r['buy_hold_pct']:.1f}% | {r['sharpe']:.2f} | {r['max_drawdown_pct']:.1f}% | {r['n_trades']} |"
            )
        lineas.append("")

    lineas.append(
        "_Compara el 'capital final' de cada fila contra la cifra reportada en la "
        "captura original (x25,60 en 1h, x29,72 en 4h) para ver si se sostiene con "
        "metodologia independiente. Sharpe > 1 se suele considerar bueno; > 2 muy "
        "bueno. Recuerda: esto no incluye slippage, solo comision._"
    )

    with open("backtest_rsi_nube.md", "w") as f:
        f.write("\n".join(lineas))
    print("\n".join(lineas))


def main():
    resultados = []
    for cfg in CONFIGS:
        print(f"Descargando historico {cfg['interval']}...")
        df = get_historical_klines(interval=cfg["interval"])
        print(f"{len(df)} velas descargadas. Calculando RSI+Nube...")
        df = compute_rsi_nube(df, cfg["rsi_len"], cfg["ema_rap"], cfg["ema_len"], cfg["nivel"])
        df = df.iloc[WARMUP_CANDLES:].reset_index(drop=True)

        df["combinado"] = df["verde"] & df["dentro_nivel"]

        variantes = []
        for nombre, col in [("bolitas", "verde"), ("nivel", "dentro_nivel"), ("combinado", "combinado")]:
            r = simular(df, col, cfg["periodos_año"])
            variantes.append((nombre, r))

        label = (
            f"{cfg['interval']} · RSI({cfg['rsi_len']}) nube {cfg['ema_rap']}/{cfg['ema_len']} "
            f"nivel {cfg['nivel']}"
        )
        resultados.append((label, variantes))

    guardar_informe(resultados)
    print("\nListo: backtest_rsi_nube.md generado.")


if __name__ == "__main__":
    main()
