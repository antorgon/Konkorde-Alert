"""
Alerta Koncorde -> Telegram (modo "un solo chequeo")
=====================================================
Pensado para ejecutarse periodicamente vía GitHub Actions (o cron), no en
bucle infinito. Cada ejecucion:

  1. Descarga velas de Binance
  2. Calcula el Koncorde (verde, marron, azul, media)
  3. Mira si en la ultima vela CERRADA "verde" cruzo al alza a "media"
  4. Si es asi Y no se ha avisado ya de esa misma vela -> manda Telegram
  5. Guarda en state.json la ultima vela avisada (para no duplicar alertas)

Variables de entorno necesarias (se configuran como Secrets en GitHub):
  TELEGRAM_TOKEN
  TELEGRAM_CHAT_ID

Nota sobre precision: reconstruccion basada en versiones abiertas del
Koncorde de Blai5 (la 2.0 oficial es codigo cerrado). Los cruces deberian
coincidir con TradingView en la gran mayoria de los casos, pero no es un
calco exacto.
"""

import os
import json
import sys

import requests
import pandas as pd

SYMBOL = "BTCUSDT"
INTERVAL = "1h"
LOOKBACK = 400
STATE_FILE = "state.json"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# data-api.binance.vision es el dominio de Binance dedicado a datos publicos
# de mercado; a diferencia de api.binance.com, no bloquea peticiones desde
# IPs de EEUU (como las que usa GitHub Actions), asi que evita el error 451.
BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"


# --------------------------- DATOS DE MERCADO ---------------------------
def get_klines(symbol=SYMBOL, interval=INTERVAL, limit=LOOKBACK) -> pd.DataFrame:
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=15)
    resp.raise_for_status()
    raw = resp.json()

    df = pd.DataFrame(raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df[["close_time", "open", "high", "low", "close", "volume"]]


# --------------------------- CALCULO KONCORDE ---------------------------
def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = (-delta.clip(upper=0)).rolling(length).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100 - (100 / (1 + rs))


def _mfi(df: pd.DataFrame, length: int = 14) -> pd.Series:
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


def _pvi_nvi(df: pd.DataFrame):
    """Positive/Negative Volume Index, vectorizado con cumprod (equivalente
    al bucle vela-a-vela, pero sin iterar en Python)."""
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


def compute_koncorde(df: pd.DataFrame, m: int = 15) -> pd.DataFrame:
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


def detectar_cruce(df: pd.DataFrame) -> str | None:
    """Devuelve 'alza' (entra en la montaña), 'baja' (sale de la montaña)
    o None si no hay cruce en la ultima vela cerrada."""
    if len(df) < 3:
        return None
    prev, last = df.iloc[-3], df.iloc[-2]
    if prev["verde"] <= prev["media"] and last["verde"] > last["media"]:
        return "alza"
    if prev["verde"] >= prev["media"] and last["verde"] < last["media"]:
        return "baja"
    return None


# --------------------------- TREND SPEED ANALYZER (Zeiierman) ---------------------------
# Replica fiel del indicador "Trend Speed Analyzer (Zeiierman)" (codigo Pine
# abierto, licencia CC BY-NC-SA 4.0), usado como confirmacion de tendencia:
# verde/alcista cuando wma(close,2) > dyn_ema, rojo/bajista en caso contrario.
TSA_MAX_LENGTH = 50        # 'Maximum Length' en el indicador original
TSA_ACCEL_MULT = 5.0       # 'Accelerator Multiplier' en el indicador original


def _wma(series: pd.Series, length: int) -> pd.Series:
    weights = pd.Series(range(1, length + 1))
    return series.rolling(length).apply(lambda x: (x * weights.values).sum() / weights.sum(), raw=True)


def compute_trend_speed(df: pd.DataFrame, max_length: int = TSA_MAX_LENGTH,
                         accel_multiplier: float = TSA_ACCEL_MULT) -> pd.DataFrame:
    df = df.copy()
    close = df["close"]

    # Longitud dinamica en funcion del nivel de precio normalizado
    max_abs_counts_diff = close.abs().rolling(200, min_periods=1).max()
    counts_diff_norm = (close + max_abs_counts_diff) / (2 * max_abs_counts_diff)
    dyn_length = 5 + counts_diff_norm * (max_length - 5)

    # Factor acelerador en funcion de la variacion de precio
    delta_counts_diff = close.diff().abs().fillna(0)
    max_delta = delta_counts_diff.rolling(200, min_periods=1).max().replace(0, 1)
    accel_factor = delta_counts_diff / max_delta

    alpha = (2 / (dyn_length + 1)) * (1 + accel_factor * accel_multiplier)
    alpha = alpha.clip(upper=1.0)

    dyn_ema = [close.iloc[0]]
    for i in range(1, len(df)):
        dyn_ema.append(alpha.iloc[i] * close.iloc[i] + (1 - alpha.iloc[i]) * dyn_ema[-1])
    df["dyn_ema"] = dyn_ema

    df["tsa_bullish"] = _wma(close, 2) > df["dyn_ema"]
    return df


# --------------------------- ESTADO (anti-duplicados) ---------------------------
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# --------------------------- TELEGRAM ---------------------------
def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[AVISO] Faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID, no se envia mensaje.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    r.raise_for_status()


# --------------------------- MAIN (una sola ejecucion) ---------------------------
CROSS_INFO = {
    "alza": ("Verde entra en la montaña (cruce al alza sobre media)", "last_alert_up_close_time"),
    "baja": ("Verde sale de la montaña (cruce a la baja bajo media)", "last_alert_down_close_time"),
}

CONFIRMED_INFO = {
    "alza": ("Entrada CONFIRMADA (cruce + valor + Trend Speed Analyzer alcista)", "last_confirmed_up_close_time"),
    "baja": ("Salida CONFIRMADA (cruce + valor + Trend Speed Analyzer bajista)", "last_confirmed_down_close_time"),
}

# Rango valido del valor de "verde" en el momento del cruce, segun el
# criterio: entrada valida si el cruce ocurre con la linea entre 0 y 50
# (si ya esta por encima de 50 el movimiento lleva mucho recorrido y
# aumenta el riesgo de "hachazo"). Para el cruce bajista se usa el rango
# simetrico -50/0 (extrapolacion propia, el criterio original solo describe
# el caso alcista).
VALOR_MIN_ALZA, VALOR_MAX_ALZA = 0, 50
VALOR_MIN_BAJA, VALOR_MAX_BAJA = -50, 0


def main():
    df = compute_koncorde(get_klines())
    df = compute_trend_speed(df)
    last_closed = df.iloc[-2]
    close_time_str = last_closed["close_time"].isoformat()

    direccion = detectar_cruce(df)
    if direccion is None:
        print(f"Sin señal nueva. Ultima vela cerrada: {close_time_str}")
        return

    state = load_state()

    # --- 1) Alerta inmediata del cruce, igual que antes de añadir filtros ---
    descripcion, state_key = CROSS_INFO[direccion]
    if state.get(state_key) != close_time_str:
        msg = (
            f"Koncorde {SYMBOL} {INTERVAL}\n"
            f"{descripcion}\n"
            f"Vela cerrada: {close_time_str}\n"
            f"Precio cierre: {last_closed['close']:.2f}"
        )
        print(msg)
        send_telegram(msg)
        state[state_key] = close_time_str
    else:
        print(f"Cruce '{direccion}' ya avisado previamente. Vela cerrada: {close_time_str}")

    # --- 2) Alerta adicional SOLO si tambien se cumplen valor + Trend Speed ---
    verde_val = last_closed["verde"]
    tsa_bullish = bool(last_closed["tsa_bullish"])

    if direccion == "alza":
        valor_ok = VALOR_MIN_ALZA <= verde_val <= VALOR_MAX_ALZA
        tsa_ok = tsa_bullish
    else:
        valor_ok = VALOR_MIN_BAJA <= verde_val <= VALOR_MAX_BAJA
        tsa_ok = not tsa_bullish

    descripcion_conf, state_key_conf = CONFIRMED_INFO[direccion]

    if valor_ok and tsa_ok and state.get(state_key_conf) != close_time_str:
        msg_conf = (
            f"Koncorde {SYMBOL} {INTERVAL}\n"
            f"{descripcion_conf}\n"
            f"Valor verde en el cruce: {verde_val:.1f}\n"
            f"Vela cerrada: {close_time_str}\n"
            f"Precio cierre: {last_closed['close']:.2f}"
        )
        print(msg_conf)
        send_telegram(msg_conf)
        state[state_key_conf] = close_time_str
    elif not (valor_ok and tsa_ok):
        print(
            f"Confirmacion NO cumplida (verde={verde_val:.1f}, valor_ok={valor_ok}, "
            f"trend_speed={'alcista' if tsa_bullish else 'bajista'}, tsa_ok={tsa_ok})."
        )

    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
