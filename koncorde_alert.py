"""
Alerta Koncorde -> Telegram
============================
Se ejecuta repetidamente (cada 30 min) dentro del bucle del workflow de
GitHub Actions (.github/workflows/koncorde.yml), que se auto-relanza cada
~5h40m para funcionar de forma indefinida. Cada ejecucion de este script:

  1. Descarga velas de Binance
  2. Calcula el Koncorde (verde, marron, azul, media), el Trend Speed
     Analyzer (dyn_ema, tsa_bullish) y el ADX (fuerza de tendencia)
  3. Mira si en la ultima vela CERRADA "verde" cruzo la "media"
  4. Manda por Telegram el aviso del cruce (siempre) y, si ademas se cumplen
     el rango de valor, la confirmacion del Trend Speed Analyzer y el ADX
     indicando tendencia con fuerza suficiente, un segundo aviso de
     "entrada/salida CONFIRMADA"
  5. Guarda en state.json la ultima vela avisada de cada tipo, para no
     duplicar alertas entre ejecuciones

Variables de entorno necesarias (se configuran como Secrets en GitHub):
  TELEGRAM_TOKEN
  TELEGRAM_CHAT_ID

Nota sobre precision: reconstruccion basada en versiones abiertas del
Koncorde de Blai5 (la 2.0 oficial es codigo cerrado). Los cruces deberian
coincidir con TradingView en la gran mayoria de los casos, pero no es un
calco exacto. El Trend Speed Analyzer si es una replica fiel del Pine
Script original (Zeiierman, licencia CC BY-NC-SA 4.0). El ADX usa la
formula estandar de Wilder (ta.dmi de Pine), tambien una replica fiel, no
una aproximacion.

Los rangos de valor de "verde" (VALOR_MIN_ALZA/VALOR_MAX_ALZA/VALOR_MAX_BAJA
mas abajo) estan ajustados con datos reales, no con suposiciones: ver
analisis_valor_verde.py para el analisis completo sobre ~10 años de
historico de BTCUSDT.
"""

import os
import json
import sys

import requests
import pandas as pd
import numpy as np

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

# Sesion compartida: al revisar varias temporalidades en cada pasada se
# hacen varias peticiones seguidas al mismo host (Binance), y una Session
# reutiliza la conexion TCP/TLS entre ellas en vez de abrir una nueva por
# cada peticion.
_session = requests.Session()


# --------------------------- DATOS DE MERCADO ---------------------------
def get_klines(symbol=SYMBOL, interval=INTERVAL, limit=LOOKBACK) -> pd.DataFrame:
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = _session.get(BINANCE_KLINES_URL, params=params, timeout=15)
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
TSA_MAX_LENGTH = 118       # 'Maximum Length' -- ajustado a la config real del indicador
                           # en el grafico del usuario (no es el valor por defecto, que es 50)
TSA_ACCEL_MULT = 2.8       # 'Accelerator Multiplier' -- idem, valor por defecto es 5.0


def _wma(series: pd.Series, length: int) -> pd.Series:
    """Media movil ponderada linealmente, vectorizada (sin rolling().apply())."""
    weights = pd.Series(range(1, length + 1), dtype=float)
    weighted_sum = sum(series.shift(length - 1 - i) * w for i, w in enumerate(weights))
    return weighted_sum / weights.sum()


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
    alpha = alpha.clip(upper=1.0).to_numpy()

    # El calculo de dyn_ema es recursivo (cada valor depende del anterior),
    # asi que no se puede vectorizar del todo, pero usar arrays de numpy en
    # vez de acceder con .iloc fila a fila sobre la Series acelera bastante
    # el bucle al evitar el overhead de pandas en cada iteracion.
    close_arr = close.to_numpy()
    dyn_ema = np.empty(len(df))
    dyn_ema[0] = close_arr[0]
    for i in range(1, len(df)):
        dyn_ema[i] = alpha[i] * close_arr[i] + (1 - alpha[i]) * dyn_ema[i - 1]
    df["dyn_ema"] = dyn_ema

    df["tsa_bullish"] = _wma(close, 2) > df["dyn_ema"]
    return df


# --------------------------- ADX (fuerza de tendencia, DMI de Wilder) ---------------------------
# Replica de "EMA 50 ADX por intensidad": ta.dmi(14,14) + una EMA(3) extra
# de suavizado sobre el ADX resultante. Se usa como tercer filtro de
# confirmacion: exige que haya tendencia con fuerza suficiente, algo que ni
# el Koncorde ni el Trend Speed Analyzer miden por si solos (ambos miran
# direccion/momentum, no fuerza de tendencia).
ADX_DI_LENGTH = 14
ADX_SMOOTHING = 14
ADX_EMA_SMOOTH = 3
ADX_MEDIO = 20.0   # umbral minimo para considerar que hay tendencia


def _rma(series: pd.Series, length: int) -> pd.Series:
    """Suavizado de Wilder (equivalente a ta.rma de Pine): EMA con
    alpha = 1/length."""
    return series.ewm(alpha=1 / length, adjust=False).mean()


def compute_adx(df: pd.DataFrame, di_length: int = ADX_DI_LENGTH,
                 adx_smoothing: int = ADX_SMOOTHING, ema_smooth: int = ADX_EMA_SMOOTH) -> pd.DataFrame:
    df = df.copy()
    high, low, close = df["high"], df["low"], df["close"]
    prev_high, prev_low, prev_close = high.shift(1), low.shift(1), close.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    tr_smooth = _rma(tr, di_length)
    di_plus = 100 * _rma(plus_dm, di_length) / tr_smooth
    di_minus = 100 * _rma(minus_dm, di_length) / tr_smooth

    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus)
    adx_raw = _rma(dx, adx_smoothing)

    df["di_plus"] = di_plus
    df["di_minus"] = di_minus
    df["adx"] = adx_raw.ewm(span=ema_smooth, adjust=False).mean()
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
    r = _session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    r.raise_for_status()


# --------------------------- MAIN (revisa varias temporalidades) ---------------------------
INTERVALS = ["1h", "4h", "1d"]  # temporalidades revisadas en cada pasada

CROSS_DESC = {
    "alza": "Verde entra en la montaña (cruce al alza sobre media)",
    "baja": "Verde sale de la montaña (cruce a la baja bajo media)",
}

CONFIRMED_DESC = {
    "alza": "Entrada CONFIRMADA (3/3: cruce + valor + Trend Speed Analyzer + ADX alcista)",
    "baja": "Salida CONFIRMADA (3/3: cruce + valor + Trend Speed Analyzer + ADX bajista)",
}

PARTIAL_DESC = {
    "alza": "Entrada PARCIAL (2/3 condiciones alcistas)",
    "baja": "Salida PARCIAL (2/3 condiciones bajistas)",
}

# Rango valido del valor de "verde" en el momento del cruce.
#
# Ajustado empiricamente con analisis_valor_verde.py sobre ~10 años de
# historico de BTCUSDT 1h (todo el historico disponible en Binance),
# agrupando todos los cruces por el valor de verde y midiendo el % de
# aciertos y retorno medio a 24h. Sustituye la suposicion inicial (0-50
# alza / -50-0 baja simetrico), que los datos no respaldaban:
#
#   - Alza: el rango 25-50 fue consistentemente el mejor en 3 muestras
#     distintas (2, 6 y 10 años), con ~55-56% de aciertos sobre una
#     muestra grande (n=1352 en la de 10 años) -> señal solida.
#   - Baja: el patron resulto ser el opuesto al que se habia supuesto:
#     cruces con verde <= -25 rindieron mejor (~63-68% de aciertos,
#     consistente en las 3 muestras) que cruces cerca de 0, que rindieron
#     peor que el azar (~40%). Por eso "baja" no tiene limite inferior.
#
# Nota: la muestra de "baja" (47 casos combinando <-50 y -50/-25 en la
# medicion de 10 años) es bastante mas pequeña que la de "alza" (1352),
# asi que esta señal tiene menos respaldo estadistico aunque el patron
# sea consistente. Y como con cualquier analisis historico: rendimiento
# pasado no garantiza nada hacia adelante.
VALOR_MIN_ALZA, VALOR_MAX_ALZA = 25, 50
VALOR_MAX_BAJA = -25  # sin limite inferior


def revisar_intervalo(interval: str, state: dict) -> bool:
    """Revisa una temporalidad y actualiza 'state' in-place.
    Devuelve True si el estado cambio (para saber si hay que guardar)."""
    df = compute_koncorde(get_klines(interval=interval))
    df = compute_trend_speed(df)
    df = compute_adx(df)
    last_closed = df.iloc[-2]
    close_time_str = last_closed["close_time"].isoformat()

    direccion = detectar_cruce(df)
    if direccion is None:
        print(f"[{interval}] Sin señal nueva. Ultima vela cerrada: {close_time_str}")
        return False

    state_changed = False

    # --- Evaluar las 3 condiciones (se usan tanto en el desglose del
    # mensaje 1 como en los avisos de confirmacion parcial/total) ---
    verde_val = last_closed["verde"]
    tsa_bullish = bool(last_closed["tsa_bullish"])
    adx_val = last_closed["adx"]
    di_plus, di_minus = last_closed["di_plus"], last_closed["di_minus"]

    if direccion == "alza":
        rango_valor_txt = f"{VALOR_MIN_ALZA} a {VALOR_MAX_ALZA}"
        if VALOR_MIN_ALZA <= verde_val <= VALOR_MAX_ALZA:
            valor_estado = "dentro"
        elif verde_val > VALOR_MAX_ALZA:
            valor_estado = "extendido"   # "en pleno proceso": misma direccion, fuera del rango validado
        else:
            valor_estado = "contrario"   # por debajo del rango, ni siquiera en la misma direccion
        tsa_ok = tsa_bullish
        adx_ok = adx_val >= ADX_MEDIO and di_plus > di_minus
    else:
        rango_valor_txt = f"≤ {VALOR_MAX_BAJA}"
        if verde_val <= VALOR_MAX_BAJA:
            valor_estado = "dentro"
        elif verde_val <= 0:
            valor_estado = "extendido"   # "en pleno proceso" en el lado bajista: negativo pero no tanto
        else:
            valor_estado = "contrario"   # positivo en un cruce bajista, direccion contraria
        tsa_ok = not tsa_bullish
        adx_ok = adx_val >= ADX_MEDIO and di_minus > di_plus

    valor_ok = valor_estado in ("dentro", "extendido")  # 🟢 y 🟡 cuentan; solo 🔴 (direccion contraria) no
    n_ok = sum([valor_ok, tsa_ok, adx_ok])
    sufijo = "up" if direccion == "alza" else "down"  # se usa en las 3 claves de estado de abajo

    def _icono(ok):
        return "✅" if ok else "❌"

    ICONO_VALOR = {"dentro": "🟢", "extendido": "🟡", "contrario": "🔴"}
    TEXTO_VALOR = {
        "dentro": "dentro del rango validado",
        "extendido": "fuera de rango, en pleno proceso (sin ventaja estadistica demostrada)",
        "contrario": "direccion contraria al cruce",
    }
    desglose = (
        f"Valor verde: {verde_val:.1f} {ICONO_VALOR[valor_estado]} "
        f"({TEXTO_VALOR[valor_estado]}, rango validado {rango_valor_txt})\n"
        f"Trend Speed Analyzer: {'alcista' if tsa_bullish else 'bajista'} {_icono(tsa_ok)}\n"
        f"ADX: {adx_val:.1f} {_icono(adx_ok)} (≥{ADX_MEDIO:.0f} y DI dominante a favor)"
    )

    # --- 1) Alerta inmediata del cruce, con el desglose de las 3 condiciones ---
    state_key = f"last_alert_{sufijo}_close_time_{interval}"
    if state.get(state_key) != close_time_str:
        msg = (
            f"Koncorde {SYMBOL} {interval}\n"
            f"{CROSS_DESC[direccion]}\n"
            f"Vela cerrada: {close_time_str}\n"
            f"Precio cierre: {last_closed['close']:.2f}\n\n"
            f"{desglose}"
        )
        print(msg)
        send_telegram(msg)
        state[state_key] = close_time_str
        state_changed = True
    else:
        print(f"[{interval}] Cruce '{direccion}' ya avisado previamente. Vela cerrada: {close_time_str}")

    # --- 2) Confirmacion TOTAL (3/3) o PARCIAL (2/3), nunca las dos a la vez ---
    if n_ok == 3:
        state_key_conf = f"last_confirmed_{sufijo}_close_time_{interval}"
        if state.get(state_key_conf) != close_time_str:
            msg_conf = (
                f"Koncorde {SYMBOL} {interval}\n"
                f"{CONFIRMED_DESC[direccion]}\n"
                f"Vela cerrada: {close_time_str}\n"
                f"Precio cierre: {last_closed['close']:.2f}"
            )
            print(msg_conf)
            send_telegram(msg_conf)
            state[state_key_conf] = close_time_str
            state_changed = True
    elif n_ok == 2:
        state_key_partial = f"last_partial_{sufijo}_close_time_{interval}"
        if state.get(state_key_partial) != close_time_str:
            if not valor_ok:
                fallo = "valor (" + TEXTO_VALOR[valor_estado] + ")"
            elif not tsa_ok:
                fallo = "Trend Speed Analyzer"
            else:
                fallo = "ADX"
            msg_partial = (
                f"Koncorde {SYMBOL} {interval}\n"
                f"{PARTIAL_DESC[direccion]}\n"
                f"Falta: {fallo}\n"
                f"Vela cerrada: {close_time_str}\n"
                f"Precio cierre: {last_closed['close']:.2f}"
            )
            print(msg_partial)
            send_telegram(msg_partial)
            state[state_key_partial] = close_time_str
            state_changed = True
    else:
        print(
            f"[{interval}] Solo {n_ok}/3 condiciones cumplidas "
            f"(valor_ok={valor_ok}, tsa_ok={tsa_ok}, adx_ok={adx_ok}). Sin aviso adicional."
        )

    return state_changed


def main():
    state = load_state()
    state_changed = False

    for interval in INTERVALS:
        try:
            if revisar_intervalo(interval, state):
                state_changed = True
        except Exception as e:
            # Si falla una temporalidad (ej. un fallo puntual de red), las
            # demas se siguen revisando igualmente.
            print(f"[{interval}] [ERROR] {e}")

    if state_changed:
        save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
