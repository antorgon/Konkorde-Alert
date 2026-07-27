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
    ret = df["close"].pct_change().fillna(0)
    up = df["volume"] > df["volume"].shift(1)
    down = df["volume"] < df["volume"].shift(1)
    pvi, nvi = [1000.0], [1000.0]
    for i in range(1, len(df)):
        pvi.append(pvi[-1] * (1 + ret.iloc[i]) if up.iloc[i] else pvi[-1])
        nvi.append(nvi[-1] * (1 + ret.iloc[i]) if down.iloc[i] else nvi[-1])
    df["pvi"], df["nvi"] = pvi, nvi
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


def cruce_alcista(df: pd.DataFrame) -> bool:
    if len(df) < 3:
        return False
    prev, last = df.iloc[-3], df.iloc[-2]
    return prev["verde"] <= prev["media"] and last["verde"] > last["media"]


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
def main():
    df = compute_koncorde(get_klines())
    last_closed = df.iloc[-2]
    close_time_str = last_closed["close_time"].isoformat()

    state = load_state()
    already_alerted = state.get("last_alert_close_time") == close_time_str

    if cruce_alcista(df) and not already_alerted:
        msg = (
            f"Koncorde {SYMBOL} {INTERVAL}\n"
            f"Verde cruza al alza la media\n"
            f"Vela cerrada: {close_time_str}\n"
            f"Precio cierre: {last_closed['close']:.2f}"
        )
        print(msg)
        send_telegram(msg)
        state["last_alert_close_time"] = close_time_str
        save_state(state)
    else:
        print(f"Sin señal nueva. Ultima vela cerrada: {close_time_str}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
