"""
Analisis de independencia del Trend Speed Analyzer
=====================================================
Pregunta a responder: si avisaramos cada vez que el TSA cambia de estado
(alcista <-> bajista) de forma independiente, ¿aportaria señales nuevas, o
casi siempre coincidiria en el tiempo con un cruce del Koncorde o un
cambio de veredicto de Bitman (y por tanto seria redundante)?

Metodo: sobre historico real, se detectan los 3 tipos de evento por
separado (flip del TSA, cruce del Koncorde, cambio de veredicto Bitman) y,
para cada flip del TSA, se mira si hay un cruce o cambio de Bitman dentro
de una ventana de +/- N velas. Se reporta que % de los flips del TSA serian
"redundantes" (acompañados) frente a "independientes" (aislados).

Uso:
    pip install pandas requests numpy
    python analisis_tsa_independencia.py

Genera: analisis_tsa_independencia.md
"""

import time
from datetime import datetime, timezone

import requests
import pandas as pd
import numpy as np

SYMBOL = "BTCUSDT"
INTERVAL = "1h"
YEARS_BACK = 5
WARMUP_CANDLES = 250   # el TSA usa rolling(200), necesita bastante warmup
VENTANA_VELAS = 3      # +/- cuantas velas se considera "cerca en el tiempo"

BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"


# --------------------------- DESCARGA PAGINADA ---------------------------
def get_historical_klines(symbol=SYMBOL, interval=INTERVAL, years_back=YEARS_BACK) -> pd.DataFrame:
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
    return df[["close_time", "open", "high", "low", "close", "volume"]]


# --------------------------- KONCORDE (igual que koncorde_alert.py) ---------------------------
def _rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = (-delta.clip(upper=0)).rolling(length).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100 - (100 / (1 + rs))


def _mfi(df, length=14):
    src = (df["high"] + df["low"] + df["close"]) / 3.0
    change = src.diff()
    pos = (df["volume"] * src.where(change > 0, 0)).rolling(length).sum()
    neg = (df["volume"] * src.where(change <= 0, 0)).rolling(length).sum()
    rs = pos / neg.replace(0, 1e-12)
    return 100 - (100 / (1 + rs))


def _stoch(series, high, low, length=21, smooth=3):
    ll, hh = low.rolling(length).min(), high.rolling(length).max()
    k = 100 * (series - ll) / (hh - ll)
    return k.rolling(smooth).mean()


def _pvi_nvi(df):
    ret = df["close"].pct_change().fillna(0)
    vol_change = df["volume"].diff()
    up = vol_change > 0
    down = vol_change < 0
    pvi_factor = (1 + ret).where(up, 1.0)
    nvi_factor = (1 + ret).where(down, 1.0)
    pvi_factor.iloc[0] = 1.0
    nvi_factor.iloc[0] = 1.0
    df["pvi"] = 1000.0 * pvi_factor.cumprod()
    df["nvi"] = 1000.0 * nvi_factor.cumprod()
    return df


def compute_koncorde(df, m=15):
    df = df.copy()
    tprice = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    df = _pvi_nvi(df)

    pvim = df["pvi"].ewm(span=m, adjust=False).mean()
    oscp = (df["pvi"] - pvim) * 100 / (pvim.rolling(90).max() - pvim.rolling(90).min())

    nvim = df["nvi"].ewm(span=m, adjust=False).mean()
    azul = (df["nvi"] - nvim) * 100 / (nvim.rolling(90).max() - nvim.rolling(90).min())

    xmf, xrsi = _mfi(df, 14), _rsi(tprice, 14)

    basis = tprice.rolling(25).mean()
    dev = 2.0 * tprice.rolling(25).std()
    ob1 = ((basis + dev) + (basis - dev)) / 2.0
    ob2 = (basis + dev) - (basis - dev)
    boll_osc = ((tprice - ob1) / ob2) * 100

    stoc = _stoch(tprice, df["high"], df["low"], 21, 3)

    marron = (xrsi + xmf + boll_osc + (stoc / 3)) / 2
    df["marron"] = marron
    df["verde"] = marron + oscp
    df["azul"] = azul
    df["media"] = marron.ewm(span=m, adjust=False).mean()
    return df


# --------------------------- TREND SPEED ANALYZER ---------------------------
def _wma(series, length):
    weights = pd.Series(range(1, length + 1), dtype=float)
    weighted_sum = sum(series.shift(length - 1 - i) * w for i, w in enumerate(weights))
    return weighted_sum / weights.sum()


def compute_trend_speed(df, max_length=118, accel_multiplier=2.8):
    df = df.copy()
    close = df["close"]
    max_abs_counts_diff = close.abs().rolling(200, min_periods=1).max()
    counts_diff_norm = (close + max_abs_counts_diff) / (2 * max_abs_counts_diff)
    dyn_length = 5 + counts_diff_norm * (max_length - 5)

    delta_counts_diff = close.diff().abs().fillna(0)
    max_delta = delta_counts_diff.rolling(200, min_periods=1).max().replace(0, 1)
    accel_factor = delta_counts_diff / max_delta

    alpha = (2 / (dyn_length + 1)) * (1 + accel_factor * accel_multiplier)
    alpha = alpha.clip(upper=1.0).to_numpy()

    close_arr = close.to_numpy()
    dyn_ema = np.empty(len(df))
    dyn_ema[0] = close_arr[0]
    for i in range(1, len(df)):
        dyn_ema[i] = alpha[i] * close_arr[i] + (1 - alpha[i]) * dyn_ema[i - 1]
    df["dyn_ema"] = dyn_ema

    df["tsa_bullish"] = _wma(close, 2) > df["dyn_ema"]
    return df


# --------------------------- ADX ---------------------------
def _rma(series, length):
    return series.ewm(alpha=1 / length, adjust=False).mean()


def compute_adx(df, di_length=14, adx_smoothing=14, ema_smooth=3):
    df = df.copy()
    high, low, close = df["high"], df["low"], df["close"]
    prev_high, prev_low, prev_close = high.shift(1), low.shift(1), close.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)

    tr_smooth = _rma(tr, di_length)
    di_plus = 100 * _rma(plus_dm, di_length) / tr_smooth
    di_minus = 100 * _rma(minus_dm, di_length) / tr_smooth

    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus)
    adx_raw = _rma(dx, adx_smoothing)

    df["di_plus"] = di_plus
    df["di_minus"] = di_minus
    df["adx"] = adx_raw.ewm(span=ema_smooth, adjust=False).mean()
    return df


# --------------------------- AO + BITMAN ---------------------------
def compute_ao(df):
    df = df.copy()
    median = (df["high"] + df["low"]) / 2
    ao = median.rolling(5).mean() - median.rolling(34).mean()
    subiendo = ao > ao.shift(1)
    es_positivo = ao >= 0
    hay_dato = ao.notna() & ao.shift(1).notna()
    condiciones = [
        hay_dato & es_positivo & subiendo,
        hay_dato & es_positivo & ~subiendo,
        hay_dato & (~es_positivo) & (~subiendo),
        hay_dato & (~es_positivo) & subiendo,
    ]
    opciones = ["alcista", "retroceso_alcista", "bajista", "retroceso_bajista"]
    df["ao"] = ao
    df["ao_estado"] = np.select(condiciones, opciones, default=None)
    return df


def compute_veredicto(df):
    df = compute_ao(df)
    mx = df[["verde", "marron"]].max(axis=1)
    mn = df[["verde", "marron"]].min(axis=1)
    df["kon_val"] = np.where(mx < 0, mn, mx)
    adx_subiendo = df["adx"] > df["adx"].shift(1)
    ko_bull = df["kon_val"] > 0
    ko_bear = df["kon_val"] < 0
    es_compra = (df["ao_estado"] == "alcista") & adx_subiendo & ko_bull
    es_venta = (df["ao_estado"] == "bajista") & adx_subiendo & ko_bear
    df["veredicto"] = np.select([es_compra, es_venta], ["COMPRAR", "VENDER"], default="ESPERAR")
    return df


# --------------------------- DETECCION DE EVENTOS ---------------------------
def detectar_eventos(df: pd.DataFrame) -> pd.DataFrame:
    df["tsa_flip"] = df["tsa_bullish"] != df["tsa_bullish"].shift(1)
    df["koncorde_cruce"] = (
        (df["verde"] > df["media"]) != (df["verde"].shift(1) > df["media"].shift(1))
    )
    df["bitman_cambio"] = df["veredicto"] != df["veredicto"].shift(1)
    return df


def analizar(df: pd.DataFrame, ventana: int = VENTANA_VELAS) -> dict:
    df = df.iloc[WARMUP_CANDLES:].reset_index(drop=True)
    df = detectar_eventos(df)

    idx_tsa_flip = df.index[df["tsa_flip"]].tolist()
    idx_koncorde = set(df.index[df["koncorde_cruce"]].tolist())
    idx_bitman = set(df.index[df["bitman_cambio"]].tolist())

    redundantes = 0
    independientes = 0
    for i in idx_tsa_flip:
        ventana_idx = range(max(0, i - ventana), min(len(df), i + ventana + 1))
        acompañado = any((j in idx_koncorde) or (j in idx_bitman) for j in ventana_idx)
        if acompañado:
            redundantes += 1
        else:
            independientes += 1

    total = len(idx_tsa_flip)
    dias_totales = (df["close_time"].iloc[-1] - df["close_time"].iloc[0]).total_seconds() / 86400

    return {
        "total_flips_tsa": total,
        "redundantes": redundantes,
        "independientes": independientes,
        "pct_redundante": round(redundantes / total * 100, 1) if total else 0,
        "pct_independiente": round(independientes / total * 100, 1) if total else 0,
        "flips_por_dia": round(total / dias_totales, 2) if dias_totales else 0,
        "dias_analizados": round(dias_totales, 0),
        "total_cruces_koncorde": len(idx_koncorde),
        "total_cambios_bitman": len(idx_bitman),
    }


def guardar_informe(r: dict):
    lineas = [
        f"# Independencia del Trend Speed Analyzer — {SYMBOL} {INTERVAL} (ultimos {YEARS_BACK} años)",
        "",
        f"Ventana de 'cerca en el tiempo': +/- {VENTANA_VELAS} velas.",
        "",
        f"- Días analizados: **{r['dias_analizados']:.0f}**",
        f"- Cambios de estado del TSA: **{r['total_flips_tsa']}** ({r['flips_por_dia']}/día)",
        f"- Cruces del Koncorde en el mismo periodo: {r['total_cruces_koncorde']}",
        f"- Cambios de veredicto Bitman en el mismo periodo: {r['total_cambios_bitman']}",
        "",
        f"- **Redundantes** (con un cruce/cambio de Bitman cerca): "
        f"{r['redundantes']} ({r['pct_redundante']}%)",
        f"- **Independientes** (el TSA se mueve solo, sin nada cerca): "
        f"{r['independientes']} ({r['pct_independiente']}%)",
        "",
        "_Si el % independiente es alto, avisar de los cambios del TSA aportaria señales "
        "nuevas que ahora mismo no se ven. Si el % redundante es alto, casi siempre "
        "coincidiria con un aviso que ya recibes por otra via, y no compensaria el ruido "
        "extra. Ojo tambien al 'flips/dia': si es muy alto, aunque fuera independiente, "
        "podria ser demasiado ruidoso para avisar en cada uno._",
    ]
    with open("analisis_tsa_independencia.md", "w") as f:
        f.write("\n".join(lineas))
    print("\n".join(lineas))


def main():
    print(f"Descargando {YEARS_BACK} años de velas {INTERVAL} de {SYMBOL}...")
    df = get_historical_klines()
    print(f"{len(df)} velas descargadas. Calculando indicadores...")
    df = compute_koncorde(df)
    df = compute_trend_speed(df)
    df = compute_adx(df)
    df = compute_veredicto(df)
    print("Analizando eventos...")
    r = analizar(df)
    guardar_informe(r)
    print("\nListo: analisis_tsa_independencia.md generado.")


if __name__ == "__main__":
    main()
