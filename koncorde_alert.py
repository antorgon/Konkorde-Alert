"""
Alertas BTCUSDT: BitMan, Koncorde y ML RSI
=========================================
El workflow consulta Binance cada cinco minutos y procesa de forma
independiente H1, H4 y D1 para BitMan/Koncorde y H1 para ML RSI.

Los cambios detectados en la vela viva se notifican como provisionales y
se resuelven al cierre. Los candidatos pendientes y los avisos enviados
se conservan en state.json; signals_history.jsonl es un histórico append-only.
Las fórmulas, filtros, umbrales y condiciones originales de los indicadores
se mantienen sin cambios.

Variables de entorno: TELEGRAM_TOKEN y TELEGRAM_CHAT_ID.
"""

import os
import json
import sys
import tempfile
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import requests
import pandas as pd
import numpy as np

SYMBOL = "BTCUSDT"
LOOKBACK = 400




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
def get_klines(symbol=SYMBOL, interval="1h", limit=LOOKBACK) -> pd.DataFrame:
    if limit <= 1000:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = _session.get(BINANCE_KLINES_URL, params=params, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
    else:
        # Binance limita cada peticion a 1000 velas -- para pedir mas (el ML
        # RSI necesita hasta 3000) hay que encadenar varias yendo hacia
        # atras en el tiempo con 'endTime'.
        raw = []
        end_time = None
        restante = limit
        while restante > 0:
            lote = min(restante, 1000)
            params = {"symbol": symbol, "interval": interval, "limit": lote}
            if end_time is not None:
                params["endTime"] = end_time
            resp = _session.get(BINANCE_KLINES_URL, params=params, timeout=15)
            resp.raise_for_status()
            chunk = resp.json()
            if not chunk:
                break
            raw = chunk + raw
            end_time = chunk[0][0] - 1  # open_time de la primera vela del lote, menos 1ms
            restante -= len(chunk)
            if len(chunk) < lote:
                break

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


def _rsi_wilder(series: pd.Series, length: int) -> pd.Series:
    """RSI con suavizado de Wilder, replica exacta de ta.rsi de Pine
    (distinto del _rsi() de arriba, que usa media simple y solo se usa
    como componente interno del Koncorde)."""
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
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


def compute_koncorde(df: pd.DataFrame, m: int = 15, copy: bool = True) -> pd.DataFrame:
    if copy:
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


# --------------------------- TREND SPEED ANALYZER (Zeiierman) ---------------------------
# Replica fiel del indicador "Trend Speed Analyzer (Zeiierman)" (codigo Pine
# abierto, licencia CC BY-NC-SA 4.0), usado como confirmacion de tendencia:
# verde/alcista cuando wma(close,2) > dyn_ema, rojo/bajista en caso contrario.
TSA_MAX_LENGTH = 118       # 'Maximum Length' -- ajustado a la config real del indicador
                           # en el grafico del usuario (no es el valor por defecto, que es 50)
TSA_ACCEL_MULT = 2.8       # 'Accelerator Multiplier' -- idem, valor por defecto es 5.0


def _wma(series: pd.Series, length: int) -> pd.Series:
    """Media movil ponderada linealmente, sin rolling().apply()."""
    if length == 2:
        return (series.shift(1) + 2.0 * series) / 3.0

    weights = np.arange(1, length + 1, dtype=float)
    weighted_sum = sum(
        series.shift(length - 1 - i) * weight
        for i, weight in enumerate(weights)
    )
    return weighted_sum / weights.sum()


def compute_trend_speed(df: pd.DataFrame, max_length: int = TSA_MAX_LENGTH,
                         accel_multiplier: float = TSA_ACCEL_MULT,
                         copy: bool = True) -> pd.DataFrame:
    if copy:
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
                 adx_smoothing: int = ADX_SMOOTHING, ema_smooth: int = ADX_EMA_SMOOTH,
                 copy: bool = True) -> pd.DataFrame:
    if copy:
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


# --------------------------- SISTEMA 2: VEREDICTO (COMPRAR/VENDER/ESPERAR) ---------------------------
# Segunda via de aviso, INDEPENDIENTE del sistema de cruces de mas arriba.
# Replica el panel de trading compartido por el usuario (AO + ADX + Koncorde
# "todo el valor", criterio Bitman). Igual que el sistema de cruces, mira
# la vela EN CURSO (no espera al cierre) para avisar al instante -- la
# diferencia entre los dos sistemas no es "instantaneo vs no instantaneo"
# (los dos lo son), sino QUE disparan el aviso: el sistema de cruces avisa
# en cada cambio de posicion de verde/media, este avisa cuando cambia el
# ESTADO combinado (de ESPERAR/VENDER a COMPRAR, o de COMPRAR a
# VENDER/ESPERAR).
#
# Nota: aqui se implementa la version "Base" del panel (sin el filtro
# solo-largo ni el filtro de temporalidad superior de la version "Pro", ni
# el modelo de asignacion de capital) para mantener el alcance similar al
# resto del sistema, que ya revisa 1h/1d de forma independiente.


def compute_ao(df: pd.DataFrame, copy: bool = True) -> pd.DataFrame:
    """Awesome Oscillator (5/34) y su estado de 4 valores."""
    if copy:
        df = df.copy()
    median = (df["high"] + df["low"]) / 2
    ao = median.rolling(5).mean() - median.rolling(34).mean()
    subiendo = ao > ao.shift(1)
    es_positivo = ao >= 0
    hay_dato = ao.notna() & ao.shift(1).notna()  # evita clasificar NaN como "bajista" por False==False
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


def compute_bbwp(df: pd.DataFrame, length: int = 13, lookback: int = 252,
                 copy: bool = True) -> pd.DataFrame:
    """BBWP: percentil (0-100) de la anchura de las Bandas de Bollinger
    frente a su propio historial. Puramente informativo -- en el panel
    original tampoco participa en la logica COMPRAR/VENDER/ESPERAR (solo se
    muestra como contexto de volatilidad), asi que aqui se calcula pero no
    condiciona el veredicto."""
    if copy:
        df = df.copy()
    basis = df["close"].rolling(length).mean()
    dev = df["close"].rolling(length).std(ddof=0)
    width = 2 * dev / basis

    # Rolling.rank(pct=True) devuelve exactamente el percentil de la
    # observacion actual dentro de cada ventana. Es equivalente al
    # antiguo rolling().apply() pero ejecutado por pandas de forma
    # vectorizada, sin una funcion Python por ventana.
    df["bbwp"] = width.rolling(lookback, min_periods=5).rank(pct=True) * 100.0
    return df


def bbwp_texto(bbwp_val: float) -> str:
    """Clasificacion identica a la del panel original (5 niveles, no una
    simplificacion): <=2 Extremo bajo, <25 Baja, <75 Media, <98 Alta,
    resto Extremo alto."""
    if pd.isna(bbwp_val):
        return "BBWP: sin datos suficientes todavia"
    if bbwp_val <= 2:
        return f"BBWP: {bbwp_val:.0f}% (extremo bajo -- compresion muy fuerte, expansion probablemente inminente)"
    elif bbwp_val < 25:
        return f"BBWP: {bbwp_val:.0f}% (baja -- compresion, posible expansion proxima)"
    elif bbwp_val < 75:
        return f"BBWP: {bbwp_val:.0f}% (media -- volatilidad normal)"
    elif bbwp_val < 98:
        return f"BBWP: {bbwp_val:.0f}% (alta -- volatilidad ya elevada antes de la señal, posible entrada tardia)"
    else:
        return f"BBWP: {bbwp_val:.0f}% (extremo alto -- volatilidad extrema, alto riesgo de entrada muy tardia)"



# --------------------------- VEREDICTO BITMAN ---------------------------
def compute_veredicto(df: pd.DataFrame, copy: bool = True) -> pd.DataFrame:
    """Requiere que el df ya tenga 'verde', 'marron' (de compute_koncorde) y
    'adx' (de compute_adx) calculados. Añade 'kon_val' (criterio Bitman:
    el mayor entre verde/marron, o el mas negativo si ambos son negativos),
    'bbwp' (informativo, no cuenta) y 'veredicto' (COMPRAR / VENDER / ESPERAR)."""
    # Una sola copia para todo el pipeline Bitman cuando se usa de forma
    # independiente; el pipeline principal puede pasar copy=False.
    if copy:
        df = df.copy()
    df = compute_ao(df, copy=False)
    df = compute_bbwp(df, copy=False)
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


def motivo_espera(row) -> str:
    """Motivo granular de por que el veredicto es ESPERAR (replica
    baseVerdictAt del panel original)."""
    adx_subiendo = row.get("_adx_subiendo", False)
    if not adx_subiendo:
        return "Sin impulso: el ADX no esta subiendo"
    if row["ao_estado"] in ("retroceso_alcista", "retroceso_bajista"):
        return "En retroceso: esperando reanudacion de la tendencia"
    if row["ao_estado"] == "alcista" and not row["kon_val"] > 0:
        return "AO alcista pero Koncorde aun no confirma"
    if row["ao_estado"] == "bajista" and not row["kon_val"] < 0:
        return "AO bajista pero Koncorde aun no confirma"
    return "Señales sin alineacion clara"



# --------------------------- SISTEMA 3: ML RSI (BackQuant) ---------------------------
# Replica fiel de "Machine Learning RSI [BackQuant]" (codigo Pine v5,
# licencia MPL 2.0). RSI(27) sobre el precio MINIMO (no el cierre),
# suavizado con SMA(4), con umbrales dinamicos de compra/venta ajustados
# por k-means 1D (3 grupos, semilla en percentiles 25/50/75 de los ultimos
# 3000 valores de RSI).
#
# NOTA: el sistema se evalua solo sobre la ultima vela disponible para
# reducir calculo en produccion; esto no equivale a un backtest historico.
ML_RSI_LENGTH = 27
ML_RSI_SMOOTH_PERIOD = 4
ML_RSI_MAX_DATA = 3000
ML_RSI_MAX_ITER = 2000


def _kmeans_1d_3(values: np.ndarray, max_iter: int = ML_RSI_MAX_ITER) -> np.ndarray | None:
    """Replica exacta del bucle de k-means 1D del Pine: semilla en
    percentiles 25/50/75, reasignacion + recalculo de medias hasta
    converger o agotar max_iter. Devuelve los 3 centroides SIN ordenar
    (igual que el original, que no los ordena -- en la practica mantienen
    el orden ascendente porque la semilla ya viene ordenada)."""
    if len(values) < 4:
        return None
    centroids = np.percentile(values, [25, 50, 75])
    for _ in range(max_iter):
        dist = np.abs(values[:, None] - centroids[None, :])
        idx = np.argmin(dist, axis=1)
        nuevos = np.array([
            values[idx == k].mean() if np.any(idx == k) else centroids[k]
            for k in range(3)
        ])
        if np.array_equal(nuevos, centroids):
            break
        centroids = nuevos
    return centroids



def compute_ml_rsi(df: pd.DataFrame, rsi_length: int = ML_RSI_LENGTH,
                    smooth_period: int = ML_RSI_SMOOTH_PERIOD,
                    max_data: int = ML_RSI_MAX_DATA, max_iter: int = ML_RSI_MAX_ITER,
                    copy: bool = True) -> pd.DataFrame:
    if copy:
        df = df.copy()
    rsi = _rsi_wilder(df["low"], rsi_length)  # Calculation Source = Minimo
    rsi = rsi.rolling(smooth_period).mean()   # Smooth RSI, SMA(4)
    df["ml_rsi"] = rsi

    # Solo hace falta clasificar la vela EN CURSO (iloc[-1]) para el
    # sistema de avisos en vivo -- no hace falta reclusterizar bar a bar
    # como en un backtest, ahorra muchisimo calculo en produccion.
    rsi_arr = rsi.to_numpy()
    ventana = rsi_arr[-max_data:]
    ventana = ventana[~np.isnan(ventana)]

    df["ml_long_s"] = np.nan
    df["ml_short_s"] = np.nan
    df["ml_señal"] = None

    if len(ventana) < 4 or np.isnan(rsi_arr[-1]):
        return df

    centroids = _kmeans_1d_3(ventana, max_iter)
    short_s, long_s = centroids[0], centroids[2]

    ultimo_rsi = rsi_arr[-1]
    if ultimo_rsi > long_s:
        señal = "verde"
    elif ultimo_rsi < short_s:
        señal = "rojo"
    else:
        señal = "gris"

    df.iloc[-1, df.columns.get_loc("ml_long_s")] = long_s
    df.iloc[-1, df.columns.get_loc("ml_short_s")] = short_s
    df.iloc[-1, df.columns.get_loc("ml_señal")] = señal
    return df






# --------------------------- ESTADO (anti-duplicados) ---------------------------
def load_state() -> dict:
    """Carga el estado persistido; un JSON inválido se trata como vacío."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[AVISO] No se pudo cargar {STATE_FILE}: {exc}. Se inicia estado vacío.")
        return {}


def save_state(state: dict):
    """Guarda el estado de forma atómica para evitar un JSON incompleto."""
    state_path = Path(STATE_FILE)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{state_path.name}.", dir=str(state_path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, state_path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)




# --------------------------- TELEGRAM ---------------------------
def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[AVISO] Faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID, no se envia mensaje.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = _session.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
        timeout=10,
    )
    r.raise_for_status()


# --------------------------- MAIN (revisa varias temporalidades) ---------------------------

VALOR_MIN_ALZA, VALOR_MAX_ALZA = 25, 50
VALOR_MAX_BAJA = -25

ICONO_VALOR = {"dentro": "🟢", "extendido": "🟡", "contrario": "🔴"}
TEXTO_VALOR = {
    "dentro": "dentro del rango validado",
    "extendido": "fuera del rango validado (sin ventaja estadística demostrada)",
    "contrario": "signo contrario a la dirección del cruce",
}


def evaluar_condiciones_koncorde(vela, direccion: str) -> dict:
    """Evalua las 3 condiciones del sistema de cruces para una vela y una
    direccion dadas. 'vela' es normalmente la vela EN CURSO (nunca una
    cerrada, desde el refactor a avisos instantaneos) -- la direccion puede
    venir de un cambio de posicion real, o -- para el resumen de 'otras
    temporalidades' -- simplemente de si verde esta ahora mismo por encima
    o por debajo de media, sin que haya habido un cambio."""
    verde_val = vela["verde"]
    tsa_bullish = bool(vela["tsa_bullish"])
    adx_val = vela["adx"]
    di_plus, di_minus = vela["di_plus"], vela["di_minus"]

    if direccion == "alza":
        rango_valor_txt = f"{VALOR_MIN_ALZA} a {VALOR_MAX_ALZA}"
        if VALOR_MIN_ALZA <= verde_val <= VALOR_MAX_ALZA:
            valor_estado = "dentro"
        elif verde_val >= 0:
            valor_estado = "extendido"
        else:
            valor_estado = "contrario"
        tsa_ok = tsa_bullish
        adx_ok = adx_val >= ADX_MEDIO and di_plus > di_minus
    else:
        rango_valor_txt = f"≤ {VALOR_MAX_BAJA}"
        if verde_val <= VALOR_MAX_BAJA:
            valor_estado = "dentro"
        elif verde_val <= 0:
            valor_estado = "extendido"
        else:
            valor_estado = "contrario"
        tsa_ok = not tsa_bullish
        adx_ok = adx_val >= ADX_MEDIO and di_minus > di_plus

    valor_ok = valor_estado in ("dentro", "extendido")
    n_ok = sum([valor_ok, tsa_ok, adx_ok])

    return {
        "verde_val": verde_val, "tsa_bullish": tsa_bullish, "adx_val": adx_val,
        "valor_estado": valor_estado, "rango_valor_txt": rango_valor_txt,
        "valor_ok": valor_ok, "tsa_ok": tsa_ok, "adx_ok": adx_ok, "n_ok": n_ok,
    }














# ============================================================================
# NUEVA ARQUITECTURA INDEPENDIENTE (BitMan / Koncorde / ML RSI)
# ============================================================================
# Se conservan las funciones de cálculo existentes. Esta sección sustituye
# el main anterior y separa temporalidades, cierres de vela e histórico.
STATE_FILE = "state.json"
HISTORY_FILE = "signals_history.jsonl"
LOOKBACK = 1000

BITMAN_INTERVALS = ("1h", "4h", "1d")
KONCORDE_INTERVALS = ("1h", "4h", "1d")
ML_RSI_INTERVALS = ("1h",)

INTERVAL_MS = {
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}
OUTCOME_HORIZONS_MS = {
    "1h": 60 * 60 * 1000,
    "3h": 3 * 60 * 60 * 1000,
    "6h": 6 * 60 * 60 * 1000,
    "12h": 12 * 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
}


def _utc_now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _iso_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _candle_id(row) -> str:
    return str(int(pd.Timestamp(row["close_time"]).timestamp() * 1000))


def split_closed_live(df: pd.DataFrame, interval: str):
    """Devuelve (cerradas, viva). Usa close_time de Binance, no el reloj local
    del runner, para no tratar una vela en formación como cerrada."""
    if df.empty:
        raise ValueError(f"Binance no devolvió velas para {interval}")
    now = pd.Timestamp.now(tz="UTC")
    closed_mask = df["close_time"] < now
    closed = df.loc[closed_mask].copy().reset_index(drop=True)
    live = df.loc[~closed_mask].copy().reset_index(drop=True)
    return closed, live


def _append_history(record: dict):
    """Append-only, con fsync para reducir el riesgo de perder eventos."""
    path = Path(HISTORY_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def _event_id(system: str, interval: str, kind: str, event_time_ms: int, signal: str) -> str:
    raw = f"{SYMBOL}|{system}|{interval}|{kind}|{event_time_ms}|{signal}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _record_event(state: dict, *, system: str, interval: str, kind: str,
                  signal: str, price: float, event_time_ms: int,
                  status: str, indicators: dict | None = None,
                  telegram_sent: bool = False,
                  candle_time_ms: int | None = None) -> str:
    event_id = _event_id(system, interval, kind, event_time_ms, signal)
    seen = state.setdefault("history_event_ids", [])
    if event_id not in seen:
        record = {
            "record_type": "signal",
            "event_id": event_id,
            "symbol": SYMBOL,
            "system": system,
            "interval": interval,
            "kind": kind,
            "signal": signal,
            "status": status,
            "event_time_ms": int(event_time_ms),
            "event_time_utc": _iso_utc(int(event_time_ms)),
            "detected_time_ms": _utc_now_ms(),
            "sent_time_ms": _utc_now_ms() if telegram_sent else None,
            "candle_time_ms": int(candle_time_ms) if candle_time_ms is not None else None,
            "price": float(price),
            "telegram_sent": bool(telegram_sent),
            "indicators": indicators or {},
        }
        _append_history(record)
        seen.append(event_id)
        # Mantener state acotado: los IDs históricos completos permanecen en
        # JSONL; en state basta una ventana amplia para deduplicar reinicios.
        if len(seen) > 5000:
            del seen[:-5000]
    return event_id


def _safe_float(value):
    try:
        v = float(value)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _track_outcomes(state: dict, current_price: float, now_ms: int):
    """Añade resultados como nuevos registros; nunca reescribe eventos."""
    events = state.setdefault("tracked_events", {})
    for event_id, item in list(events.items()):
        outcomes = item.setdefault("outcomes", {})
        for label, horizon_ms in OUTCOME_HORIZONS_MS.items():
            if label in outcomes or now_ms < item["event_time_ms"] + horizon_ms:
                continue
            entry = float(item["price"])
            if entry <= 0:
                continue
            ret = (float(current_price) / entry - 1.0) * 100.0
            outcome = {
                "record_type": "outcome",
                "event_id": event_id,
                "symbol": SYMBOL,
                "system": item["system"],
                "interval": item["interval"],
                "horizon": label,
                "target_time_ms": item["event_time_ms"] + horizon_ms,
                "observed_time_ms": int(now_ms),
                "entry_price": entry,
                "observed_price": float(current_price),
                "return_pct": round(ret, 6),
                "directional_success": (
                    ret > 0 if item["direction"] == "bullish"
                    else ret < 0 if item["direction"] == "bearish"
                    else None
                ),
            }
            _append_history(outcome)
            outcomes[label] = {
                "observed_time_ms": int(now_ms),
                "observed_price": float(current_price),
                "return_pct": round(ret, 6),
            }
        if all(label in outcomes for label in OUTCOME_HORIZONS_MS):
            events.pop(event_id, None)






def _indicators_for_history(row, include_koncorde=True):
    fields = ("close", "verde", "marron", "media", "tsa_bullish",
              "adx", "di_plus", "di_minus", "ao", "ao_estado",
              "kon_val", "bbwp", "ml_rsi", "ml_long_s", "ml_short_s",
              "ml_señal")
    result = {}
    for key in fields:
        if key in row.index:
            value = row[key]
            if isinstance(value, (np.bool_, bool)):
                result[key] = bool(value)
            elif isinstance(value, (str,)) or value is None:
                result[key] = value
            else:
                result[key] = _safe_float(value)
    return result




def _format_event_id(eid: str) -> str:
    return eid[:8].upper()


def _send_transition(system: str, interval: str, label: str, old: str,
                     new: str, row, indicators: dict, state: dict,
                     kind: str, status: str, event_ms: int | None = None):
    """Registra y envía una transición; el ID permite enlazar su resolución."""
    event_ms = int(event_ms or _utc_now_ms())
    price = float(row["close"])
    eid = _record_event(
        state, system=system, interval=interval, kind=kind,
        signal=str(new), price=price, event_time_ms=event_ms,
        status=status, indicators=indicators, telegram_sent=False,
        candle_time_ms=int(pd.Timestamp(row["close_time"]).timestamp() * 1000)
        if "close_time" in row.index else None,
    )
    upper_new = str(new).upper()
    icon = "🟢" if any(x in upper_new for x in ("COMPRAR", "VERDE", "ALZA", "ALCISTA")) else \
           "🔴" if any(x in upper_new for x in ("VENDER", "ROJO", "BAJA", "BAJISTA")) else "⚪"
    block = (
        f"<b>{label} {SYMBOL} {interval.upper()}</b>\n"
        f"<b>{status.upper()} · {old} → {icon} {new}</b>\n"
        f"Precio: {price:.2f}\n"
        f"Referencia: {_iso_utc(event_ms)}\n"
        f"ID: <code>{_format_event_id(eid)}</code>"
    )
    if indicators:
        block += "\n" + "\n".join(
            f"{k}: {v:.2f}" if isinstance(v, (float, np.floating)) else f"{k}: {v}"
            for k, v in indicators.items() if v is not None
        )
    send_telegram(block)
    _record_event(
        state, system=system, interval=interval, kind="telegram_sent",
        signal=f"{new}:{eid}", price=price, event_time_ms=event_ms,
        status=status, indicators={"source_event_id": eid}, telegram_sent=True,
    )
    return eid


def _resolve_pending(system: str, interval: str, row, state: dict,
                     final_signal: str, valid: bool = True,
                     final_filter_count: int = 3):
    """Resuelve una única candidatura pendiente cuando cierra su vela."""
    key = f"pending_{system}_{interval}"
    pending = state.get(key)
    candle = _candle_id(row)
    if not pending or pending.get("candle") != candle:
        return
    candidate = pending.get("candidate")
    if candidate:
        if candidate.get("invalidated") or (valid and final_signal != candidate.get("signal")):
            outcome = "INVALIDADA"
            detail = (f"El cruce provisional {candidate.get('signal')} desapareció o terminó "
                      "con la dirección contraria al cierre.")
        elif not valid:
            outcome = "NO VERIFICABLE"
            detail = ("No se pudo recuperar la vela exacta del candidato; "
                      "no es posible determinar si se mantuvo al cierre.")
        elif int(final_filter_count) < 2:
            outcome = "NO CONFIRMADA"
            detail = "El cruce se mantuvo, pero terminó con menos de 2/3 filtros válidos."
        else:
            outcome = "CONFIRMADA"
            detail = "El último candidato válido se mantuvo al cierre y conservó al menos 2/3 filtros."
        event_ms = int(pd.Timestamp(row["close_time"]).timestamp() * 1000)
        eid = candidate.get("event_id", "")
        block = (
            f"<b>{system.upper()} {SYMBOL} {interval.upper()}</b>\n"
            f"<b>{outcome}</b> · ID <code>{_format_event_id(eid)}</code>\n"
            f"{detail}\nPrecio de cierre: {float(row['close']):.2f}"
        )
        send_telegram(block)
        _record_event(
            state, system=system, interval=interval, kind="candle_resolution",
            signal=outcome, price=float(row["close"]), event_time_ms=event_ms,
            status=outcome.lower().replace(" ", "_"),
            indicators={"source_event_id": eid, "final_signal": final_signal},
            telegram_sent=True,
        )
    state.pop(key, None)



def _pending_close_row(system: str, interval: str, df_closed: pd.DataFrame,
                       state: dict):
    """Busca la vela pendiente aunque el bot haya estado varias velas parado."""
    if df_closed.empty:
        return None, True
    pending = state.get(f"pending_{system}_{interval}")
    if not pending:
        return df_closed.iloc[-1], True
    target = str(pending.get("candle"))
    matches = df_closed[df_closed["close_time"].map(
        lambda value: str(int(pd.Timestamp(value).timestamp() * 1000)) == target
    )]
    if not matches.empty:
        return matches.iloc[-1], True
    latest = df_closed.iloc[-1]
    latest_id = int(pd.Timestamp(latest["close_time"]).timestamp() * 1000)
    if latest_id >= int(target):
        return latest, False
    return None, True

def _process_bitman(interval: str, df_live: pd.DataFrame, df_closed: pd.DataFrame,
                    state: dict):
    """BitMan intravela: avisa cambios una vez y resuelve al cierre."""
    if len(df_live) < 2:
        return
    row = df_live.iloc[-1]
    candle = _candle_id(row)
    key = f"pending_bitman_{interval}"
    last_key = f"bitman_live_signal_{interval}"
    previous = state.get(last_key)
    signal = str(row["veredicto"])

    # Resolver la vela anterior cuando aparece su cierre en los datos.
    if not df_closed.empty:
        pending_close, pending_valid = _pending_close_row("bitman", interval, df_closed, state)
        if pending_close is not None:
            _resolve_pending("bitman", interval, pending_close, state,
                            str(pending_close["veredicto"]), pending_valid)
        closed_row = df_closed.iloc[-1]
        closed_candle_key = f"bitman_last_closed_{interval}"
        if state.get(closed_candle_key) != _candle_id(closed_row):
            state[closed_candle_key] = _candle_id(closed_row)
            _record_event(
                state, system="bitman", interval=interval,
                kind="closed_bar_state", signal=str(closed_row["veredicto"]),
                price=float(closed_row["close"]),
                event_time_ms=int(pd.Timestamp(closed_row["close_time"]).timestamp()*1000),
                status="closed", indicators=_indicators_for_history(closed_row),
                telegram_sent=False,
            )

    if previous is None:
        state[last_key] = signal
        state[f"bitman_live_candle_{interval}"] = candle
        print(f"[BITMAN {interval}] Línea base: {signal}; sin aviso inicial.")
        return

    if state.get(f"bitman_live_candle_{interval}") != candle:
        state[f"bitman_live_candle_{interval}"] = candle
        # Al cambiar de vela, el estado previo sirve como referencia; no se
        # genera una transición artificial por el mero cambio de timestamp.

    if signal != previous:
        old_pending = state.get(key, {}).get("candidate")
        if signal == "ESPERAR":
            eid = old_pending.get("event_id", "") if old_pending else ""
            event_kind = "signal_withdrawn" if old_pending else "state_transition"
            title = "SEÑAL RETIRADA" if old_pending else "CAMBIO DE ESTADO"
            detail = (f"La señal provisional {old_pending.get('signal')} vuelve a ESPERAR."
                      if old_pending else f"El estado {previous} pasa a ESPERAR.")
            suffix = f" ID <code>{_format_event_id(eid)}</code>" if eid else ""
            send_telegram(
                f"<b>BITMAN {SYMBOL} {interval.upper()}</b>\n"
                f"<b>{title}</b> · {previous} → ESPERAR\n{detail}{suffix}\n"
                f"Precio: {float(row['close']):.2f} · Referencia: {_iso_utc(_utc_now_ms())}"
            )
            _record_event(
                state, system="bitman", interval=interval, kind=event_kind,
                signal="ESPERAR", price=float(row["close"]), event_time_ms=_utc_now_ms(),
                status="withdrawn" if old_pending else "state_change",
                indicators={"source_event_id": eid or None}, telegram_sent=True,
            )
            if old_pending:
                state[key]["candidate"] = None
        else:
            old = previous
            indicators = {
                "AO": _safe_float(row.get("ao")),
                "AO estado": str(row.get("ao_estado")),
                "Koncorde": _safe_float(row.get("kon_val")),
                "ADX": _safe_float(row.get("adx")),
                "BBWP": (f"{_safe_float(row.get('bbwp')):.1f} · {bbwp_texto(row.get('bbwp'))}"
                         if _safe_float(row.get("bbwp")) is not None else None),
            }
            eid = _send_transition(
                "bitman", interval, "BITMAN", old, signal, row, indicators,
                state, "intrabar_transition", "provisional",
            )
            if old_pending:
                _record_event(
                    state, system="bitman", interval=interval,
                    kind="candidate_superseded", signal=signal,
                    price=float(row["close"]), event_time_ms=_utc_now_ms(),
                    status="superseded", indicators={"previous_event_id": old_pending.get("event_id"),
                                                        "new_event_id": eid},
                    telegram_sent=False,
                )
            state[key] = {"candle": candle, "candidate": {
                "signal": signal, "event_id": eid, "detected_ms": _utc_now_ms()
            }}
        state[last_key] = signal

    # If the provisional state remains active, do not repeat it.
    if state.get(key, {}).get("candle") == candle and state[key].get("candidate"):
        state[key]["final_filter_count"] = 3 if signal == state[key]["candidate"].get("signal") else 0


def _process_koncorde(interval: str, df_live: pd.DataFrame, df_closed: pd.DataFrame,
                      state: dict):
    """Registra cruces; solo envía candidatos con al menos 2/3 filtros."""
    if len(df_live) < 3:
        return
    row = df_live.iloc[-1]
    candle = _candle_id(row)
    key = f"pending_koncorde_{interval}"
    pos_key = f"koncorde_live_position_{interval}"
    pos = "alza" if float(row["verde"]) > float(row["media"]) else "baja"

    if not df_closed.empty:
        pending_close, pending_valid = _pending_close_row("koncorde", interval, df_closed, state)
        if pending_close is not None:
            pending_pos = "alza" if float(pending_close["verde"]) > float(pending_close["media"]) else "baja"
            pending_filters = evaluar_condiciones_koncorde(pending_close, pending_pos)
            _resolve_pending("koncorde", interval, pending_close, state,
                             pending_pos, pending_valid, int(pending_filters["n_ok"]))
        closed_row = df_closed.iloc[-1]
        closed_pos = "alza" if float(closed_row["verde"]) > float(closed_row["media"]) else "baja"
        cclose = evaluar_condiciones_koncorde(closed_row, closed_pos)
        closed_key = f"koncorde_last_closed_{interval}"
        closed_id = _candle_id(closed_row)
        if state.get(closed_key) != closed_id:
            state[closed_key] = closed_id
            _record_event(
                state, system="koncorde", interval=interval,
                kind="closed_bar_position", signal=closed_pos,
                price=float(closed_row["close"]),
                event_time_ms=int(pd.Timestamp(closed_row["close_time"]).timestamp() * 1000),
                status="closed",
                indicators={**_indicators_for_history(closed_row),
                            "filters": int(cclose["n_ok"]),
                            "green_yellow_distance": abs(float(closed_row["verde"]) - float(closed_row["media"])),
                            "cross_persisted_at_close": bool(
                                len(df_closed) >= 2 and
                                ((float(df_closed.iloc[-2]["verde"]) <= float(df_closed.iloc[-2]["media"]) and closed_pos == "alza") or
                                 (float(df_closed.iloc[-2]["verde"]) >= float(df_closed.iloc[-2]["media"]) and closed_pos == "baja"))
                            )},
                telegram_sent=False,
            )

    previous = state.get(pos_key)
    if previous is None:
        state[pos_key] = pos
        print(f"[KONCORDE {interval}] Línea base: {pos}; sin aviso inicial.")
        return
    if pos == previous:
        return

    c = evaluar_condiciones_koncorde(row, pos)
    n_ok = int(c["n_ok"])
    direction = "alcista" if pos == "alza" else "bajista"
    event_ms = _utc_now_ms()
    filters = {
        "value_ok": bool(c["valor_ok"]), "tsa_ok": bool(c["tsa_ok"]),
        "adx_ok": bool(c["adx_ok"]), "n_ok": n_ok,
        "value_state": c["valor_estado"],
    }
    _record_event(
        state, system="koncorde", interval=interval, kind="intrabar_cross",
        signal=direction, price=float(row["close"]), event_time_ms=event_ms,
        status="candidate" if n_ok >= 2 else "weak",
        indicators={**_indicators_for_history(row), "filters": filters,
                    "green_yellow_distance": abs(float(row["verde"]) - float(row["media"]))},
        telegram_sent=False,
    )

    pending = state.get(key)
    old_candidate = pending.get("candidate") if pending and pending.get("candle") == candle else None
    if n_ok >= 2:
        if not (old_candidate and old_candidate.get("signal") == pos and not old_candidate.get("invalidated")):
            value_text = f"{c['verde_val']:.1f} {ICONO_VALOR[c['valor_estado']]} ({TEXTO_VALOR[c['valor_estado']]})"
            indicators = {
                "Valor verde": value_text,
                "Rango de referencia del valor verde": c["rango_valor_txt"],
                "Valor verde (dato capturado)": _safe_float(row["verde"]),
                "Media verde": _safe_float(row["media"]),
                "Trend Speed Analyzer": f"{'alcista' if c['tsa_bullish'] else 'bajista'} {'✅' if c['tsa_ok'] else '❌'}",
                "ADX": f"{c['adx_val']:.1f} {'✅' if c['adx_ok'] else '❌'} (DI+ {float(row['di_plus']):.1f} / DI- {float(row['di_minus']):.1f})",
                "Filtros": f"{n_ok}/3",
            }
            new_eid = _send_transition(
                "koncorde", interval, "KONCORDE", previous, direction,
                row, indicators, state, "intrabar_candidate", "provisional", event_ms,
            )
            if old_candidate:
                _record_event(
                    state, system="koncorde", interval=interval,
                    kind="candidate_superseded", signal=direction,
                    price=float(row["close"]), event_time_ms=event_ms,
                    status="superseded", indicators={
                        "previous_event_id": old_candidate.get("event_id"),
                        "new_event_id": new_eid,
                    }, telegram_sent=False,
                )
            state[key] = {"candle": candle, "candidate": {
                "signal": pos, "direction": direction, "event_id": new_eid,
                "filters": n_ok, "detected_ms": event_ms,
            }}
    elif old_candidate and old_candidate.get("signal") != pos:
        state[key]["candidate"]["invalidated"] = True
        _record_event(
            state, system="koncorde", interval=interval,
            kind="candidate_invalidated", signal=direction,
            price=float(row["close"]), event_time_ms=event_ms,
            status="invalidated", indicators={
                "previous_event_id": old_candidate.get("event_id"),
                "weak_filters": n_ok,
            }, telegram_sent=False,
        )
    state[pos_key] = pos


def _process_ml_rsi(interval: str, df_live: pd.DataFrame, df_closed: pd.DataFrame,
                    state: dict, is_provisional: bool = True):
    if df_live.empty or len(df_live) < 5:
        return
    row = df_live.iloc[-1]
    signal = row.get("ml_señal")
    if signal not in ("verde", "rojo", "gris"):
        return
    if any(_safe_float(row.get(name)) is None
           for name in ("ml_rsi", "ml_long_s", "ml_short_s", "close")):
        print(f"[ML RSI {interval}] Indicadores incompletos; se omite esta pasada.")
        return
    candle = _candle_id(row)
    key = f"pending_ml_rsi_{interval}"
    live_key = f"ml_rsi_live_signal_{interval}"

    if not df_closed.empty:
        closed_row = df_closed.iloc[-1]
        closed_signal = str(closed_row.get("ml_señal"))
        _resolve_pending("ml_rsi", interval, closed_row, state, closed_signal, True)
        closed_key = f"ml_rsi_last_closed_candle_{interval}"
        closed_candle = _candle_id(closed_row)
        if state.get(closed_key) != closed_candle:
            state[closed_key] = closed_candle
            _record_event(
                state, system="ml_rsi", interval=interval,
                kind="closed_bar_classification", signal=closed_signal,
                price=float(closed_row["close"]),
                event_time_ms=int(pd.Timestamp(closed_row["close_time"]).timestamp()*1000),
                status="closed", indicators=_indicators_for_history(closed_row),
                telegram_sent=False,
            )

    previous = state.get(live_key)
    if previous is None:
        state[live_key] = signal
        return
    if previous != signal:
        event_ms = _utc_now_ms()
        if signal in ("verde", "rojo"):
            icon = "🟢" if signal == "verde" else "🔴"
            indicators = {
                "RSI(27, mínimo, SMA4)": _safe_float(row.get("ml_rsi")),
                "Umbral verde": _safe_float(row.get("ml_long_s")),
                "Umbral rojo": _safe_float(row.get("ml_short_s")),
            }
            eid = _send_transition(
                "ml_rsi", interval, "ML RSI", previous,
                signal.upper(), row, indicators, state,
                "intrabar_transition", "provisional", event_ms,
            )
            previous_candidate = state.get(key, {}).get("candidate")
            if previous_candidate:
                _record_event(
                    state, system="ml_rsi", interval=interval,
                    kind="candidate_superseded", signal=signal,
                    price=float(row["close"]), event_time_ms=event_ms,
                    status="superseded", indicators={
                        "previous_event_id": previous_candidate.get("event_id"),
                        "new_event_id": eid,
                    }, telegram_sent=False,
                )
            state[key] = {"candle": candle, "candidate": {
                "signal": signal, "event_id": eid, "detected_ms": event_ms
            }}
        elif signal == "gris":
            pending = state.get(key, {}).get("candidate")
            eid = pending.get("event_id", "") if pending else ""
            title = "SEÑAL PROVISIONAL RETIRADA" if pending else "CAMBIO DE ESTADO"
            suffix = f" · ID <code>{_format_event_id(eid)}</code>" if eid else ""
            send_telegram(
                f"<b>ML RSI {SYMBOL} {interval.upper()}</b>\n"
                f"<b>{title}</b> · {previous} → GRIS{suffix}\n"
                f"RSI(27, mínimo, SMA4): {float(row['ml_rsi']):.1f} · "
                f"Precio: {float(row['close']):.2f}"
            )
            if pending:
                state[key]["candidate"] = None
            _record_event(
                state, system="ml_rsi", interval=interval,
                kind="signal_withdrawn" if pending else "state_transition",
                signal="gris", price=float(row["close"]), event_time_ms=event_ms,
                status="withdrawn" if pending else "state_change",
                indicators={"source_event_id": eid or None}, telegram_sent=True,
            )
        state[live_key] = signal




def _log_data_error(state: dict, interval: str, exc: Exception, now_ms: int):
    key = f"data_error_{interval}"
    item = state.get(key, {})
    first_ms = item.get("first_ms", now_ms)
    count = int(item.get("count", 0)) + 1
    state[key] = {"first_ms": first_ms, "last_ms": now_ms, "count": count,
                  "message": str(exc)[:500]}
    _append_history({
        "record_type": "data_error", "symbol": SYMBOL, "interval": interval,
        "event_time_ms": now_ms, "message": str(exc)[:500], "consecutive_count": count,
    })
    if count == 3:
        send_telegram(
            f"<b>AVISO DE DATOS · {SYMBOL} {interval.upper()}</b>\n"
            f"Tres ciclos consecutivos sin datos válidos. Se omiten señales de esta temporalidad.\n"
            f"Error: {str(exc)[:300]}"
        )


def _clear_data_error(state: dict, interval: str):
    key = f"data_error_{interval}"
    item = state.pop(key, None)
    if item:
        now_ms = _utc_now_ms()
        _append_history({
            "record_type": "data_recovery", "interval": interval,
            "event_time_ms": now_ms, "first_error_ms": item.get("first_ms"),
            "last_error_ms": item.get("last_ms"),
            "duration_ms": now_ms - int(item.get("first_ms", now_ms)),
            "failed_cycles": item.get("count", 0),
        })


def _hora_vela(row, interval: str, en_curso: bool) -> str:
    """Describe la vela utilizada, separada de la hora de consulta del bot."""
    cierre = pd.Timestamp(row["close_time"]).to_pydatetime().astimezone(
        ZoneInfo("Europe/Madrid")
    ).strftime("%d/%m %H:%M")
    return f"en curso (cierre {cierre})" if en_curso else f"última cerrada ({cierre})"


def _estado_intervalo(interval: str, market: dict, state: dict) -> tuple[str, str]:
    """Devuelve el estado de datos y la hora de la última lectura válida."""
    last_ok = state.get(f"last_data_ok_{interval}")
    updated = (
        datetime.fromtimestamp(int(last_ok) / 1000, tz=timezone.utc)
        .astimezone(ZoneInfo("Europe/Madrid")).strftime("%H:%M:%S")
        if last_ok else "sin registro"
    )
    error = state.get(f"data_error_{interval}")
    if market.get(interval) is None:
        if error:
            return f"⚠️ SIN DATOS VÁLIDOS · {str(error.get('message', 'error'))[:100]}", updated
        return "⚠️ SIN DATOS EN ESTE CICLO", updated
    return "", updated


def _bitman_resumen(interval: str, item: dict, state: dict) -> str:
    df = item["live"]
    row = df.iloc[-1]
    previous_row = df.iloc[-2]
    signal = str(row["veredicto"])
    ao_state = str(row.get("ao_estado") or "sin clasificación")
    adx_rising = float(row["adx"]) > float(previous_row["adx"])
    kon_value = float(row["kon_val"])
    if signal == "COMPRAR":
        reason = "Condiciones alineadas: AO alcista, ADX subiendo y Koncorde positivo"
        icon = "🟢"
    elif signal == "VENDER":
        reason = "Condiciones alineadas: AO bajista, ADX subiendo y Koncorde negativo"
        icon = "🔴"
    else:
        reason = motivo_espera({**dict(row), "_adx_subiendo": adx_rising})
        icon = "⚪"
    pending = state.get(f"pending_bitman_{interval}", {}).get("candidate")
    if pending:
        reason += f" · provisional pendiente: {pending.get('signal', 'sin detalle')}"
    vela = _hora_vela(row, interval, bool(item.get("has_live")))
    return (
        f"{interval.upper()}: {icon} <b>{signal}</b> · {reason}\n"
        f"   AO: {float(row['ao']):.2f} ({ao_state}) · "
        f"ADX: {float(row['adx']):.1f} ({'subiendo' if adx_rising else 'no sube'}) · "
        f"Koncorde: {kon_value:.2f} ({'positivo' if kon_value > 0 else 'negativo' if kon_value < 0 else 'neutro'})\n"
        f"   Vela analizada: {vela}"
    )


def _koncorde_resumen(interval: str, item: dict, state: dict) -> str:
    df = item["live"]
    row = df.iloc[-1]
    position = "alza" if float(row["verde"]) > float(row["media"]) else "baja"
    c = evaluar_condiciones_koncorde(row, position)
    value_icon = "✅" if c["valor_ok"] else "❌"
    tsa_icon = "✅" if c["tsa_ok"] else "❌"
    adx_icon = "✅" if c["adx_ok"] else "❌"
    value_label = {
        "dentro": "dentro del rango",
        "extendido": "extendido (filtro aceptado)",
        "contrario": "signo contrario",
    }[c["valor_estado"]]
    tsa_label = "alcista" if c["tsa_bullish"] else "bajista"
    di_label = "DI+ dominante" if float(row["di_plus"]) > float(row["di_minus"]) else "DI- dominante"
    candidate = state.get(f"pending_koncorde_{interval}", {}).get("candidate")
    if candidate:
        direction = "alcista" if candidate.get("signal") == "alza" else "bajista"
        pending_text = f" · CANDIDATO PENDIENTE: {direction} {candidate.get('filters', '?')}/3"
        if candidate.get("invalidated"):
            pending_text += " (marcado para invalidación al cierre)"
    else:
        pending_text = " · Sin candidato provisional pendiente"
    vela = _hora_vela(row, interval, bool(item.get("has_live")))
    return (
        f"{interval.upper()}: <b>posición {position.upper()} · filtros {c['n_ok']}/3</b>{pending_text}\n"
        f"   Verde: {float(row['verde']):.2f} · Media: {float(row['media']):.2f} · "
        f"Distancia: {abs(float(row['verde']) - float(row['media'])):.2f}\n"
        f"   Valor: {value_icon} {value_label} ({c['rango_valor_txt']}) · "
        f"TSA: {tsa_icon} {tsa_label} · "
        f"ADX: {adx_icon} {float(row['adx']):.1f}, {di_label}\n"
        f"   Vela analizada: {vela}"
    )


def _send_daily_summary(state: dict, now_ms: int, market: dict):
    """Envía a las 08:00 una fotografía de los estados actuales en español."""
    madrid = ZoneInfo("Europe/Madrid")
    now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).astimezone(madrid)
    if now.hour < 8:
        return
    day_key = now.date().isoformat()
    if state.get("daily_summary_sent") == day_key:
        return

    lines = [
        f"<b>ESTADO ACTUAL DE LOS SISTEMAS · {SYMBOL}</b>",
        f"{now.strftime('%d/%m/%Y · %H:%M:%S')} (hora de Madrid)",
        "",
        "<b>BITMAN · ESTADO Y MOTIVO</b>",
    ]
    for interval in BITMAN_INTERVALS:
        item = market.get(interval)
        if item is None:
            status, updated = _estado_intervalo(interval, market, state)
            lines.append(f"{interval.upper()}: {status} · Último dato válido: {updated}")
        else:
            lines.append(_bitman_resumen(interval, item, state))

    lines.extend(["", "<b>KONCORDE · POSICIÓN Y FILTROS</b>"])
    for interval in KONCORDE_INTERVALS:
        item = market.get(interval)
        if item is None:
            status, updated = _estado_intervalo(interval, market, state)
            lines.append(f"{interval.upper()}: {status} · Último dato válido: {updated}")
        else:
            lines.append(_koncorde_resumen(interval, item, state))

    lines.extend(["", "<b>ML RSI</b>"])
    for interval in ML_RSI_INTERVALS:
        item = market.get(interval)
        if item is None or item.get("ml_live") is None or item["ml_live"].empty:
            status, updated = _estado_intervalo(interval, market, state)
            lines.append(f"{interval.upper()}: {status} · Último dato válido: {updated}")
            continue
        row = item["ml_live"].iloc[-1]
        signal = str(row.get("ml_señal", "sin clasificación"))
        icon = "🟢" if signal == "verde" else "🔴" if signal == "rojo" else "⚪"
        candidate = state.get(f"pending_ml_rsi_{interval}", {}).get("candidate")
        suffix = f" · Provisional pendiente: {candidate.get('signal')}" if candidate else ""
        vela = _hora_vela(row, interval, bool(item.get("has_live")))
        lines.append(
            f"{interval.upper()}: {icon} <b>{signal.upper()}</b>{suffix} · "
            f"RSI: {_safe_float(row.get('ml_rsi')):.1f} · Vela: {vela}"
            if _safe_float(row.get("ml_rsi")) is not None
            else f"{interval.upper()}: {icon} <b>{signal.upper()}</b>{suffix} · Vela: {vela}"
        )

    active_errors = []
    for interval in sorted(set(BITMAN_INTERVALS + KONCORDE_INTERVALS + ML_RSI_INTERVALS),
                           key=lambda x: INTERVAL_MS[x]):
        error = state.get(f"data_error_{interval}")
        if error:
            active_errors.append(
                f"{interval.upper()}: {error.get('count', 0)} ciclos · "
                f"{str(error.get('message', 'error'))[:100]}"
            )
    lines.extend(["", "<b>FUNCIONAMIENTO</b>"])
    lines.append(f"Último ciclo del bot: {now.strftime('%H:%M:%S')} (Madrid)")
    if active_errors:
        lines.append("⚠️ Problemas activos: " + " | ".join(active_errors))
    else:
        lines.append("✅ Sin errores de datos activos en este ciclo.")

    send_telegram("\n".join(lines))
    state["daily_summary_sent"] = day_key
    _append_history({
        "record_type": "daily_status_snapshot_sent", "event_time_ms": now_ms,
        "day": day_key,
        "snapshot": {"market_intervals": sorted(market.keys()),
                     "active_data_errors": active_errors},
    })


def main():
    state = load_state()
    Path(HISTORY_FILE).touch(exist_ok=True)
    now_ms = _utc_now_ms()
    previous_cycle = state.get("last_cycle_ms")
    if previous_cycle is not None and now_ms - int(previous_cycle) > 10 * 60 * 1000:
        _append_history({
            "record_type": "interruption", "event_time_ms": now_ms,
            "gap_start_ms": int(previous_cycle),
            "gap_duration_ms": now_ms - int(previous_cycle),
        })
    state["last_cycle_ms"] = now_ms
    _append_history({"record_type": "bot_cycle", "event_time_ms": now_ms})
    current_price = None
    required = sorted(set(BITMAN_INTERVALS + KONCORDE_INTERVALS + ML_RSI_INTERVALS),
                      key=lambda x: INTERVAL_MS[x])
    market = {}

    for interval in required:
        try:
            fetch_limit = ML_RSI_MAX_DATA if interval in ML_RSI_INTERVALS else LOOKBACK
            raw = get_klines(interval=interval, limit=fetch_limit)
            closed_raw, live_raw = split_closed_live(raw, interval)
            if len(closed_raw) < 100:
                raise ValueError(f"Solo {len(closed_raw)} velas cerradas válidas")
            # Indicadores calculados sobre la misma serie que incluye la vela viva.
            combined = pd.concat([closed_raw, live_raw], ignore_index=True) if not live_raw.empty else closed_raw.copy()
            df_all = compute_koncorde(combined.copy())
            df_all = compute_trend_speed(df_all)
            df_all = compute_adx(df_all)
            df_all = compute_veredicto(df_all)
            required_values = ["close", "verde", "media", "tsa_bullish", "adx",
                               "di_plus", "di_minus", "ao", "kon_val", "bbwp", "veredicto"]
            last_values = df_all.iloc[-1]
            invalid = [name for name in required_values
                       if name not in last_values.index or
                       (name != "veredicto" and pd.isna(last_values[name]))]
            if invalid:
                raise ValueError("Indicadores incompletos en última vela: " + ", ".join(invalid))
            # La clasificación ML RSI usa el histórico largo original, también con la viva.
            df_ml_all = compute_ml_rsi(combined.copy()) if interval in ML_RSI_INTERVALS else None
            n_closed = len(closed_raw)
            df_closed = df_all.iloc[:n_closed].copy().reset_index(drop=True)
            df_live = df_all.copy().reset_index(drop=True)
            df_ml_closed = None
            df_ml_live = None
            if df_ml_all is not None:
                df_ml_closed = df_ml_all.iloc[:n_closed].copy().reset_index(drop=True)
                df_ml_live = df_ml_all.copy().reset_index(drop=True)
            market[interval] = {"closed": df_closed, "live": df_live,
                                "ml_closed": df_ml_closed, "ml_live": df_ml_live,
                                "has_live": not live_raw.empty}
            state[f"last_data_ok_{interval}"] = now_ms
            _clear_data_error(state, interval)
            if interval == "1h":
                current_price = float((live_raw if not live_raw.empty else closed_raw).iloc[-1]["close"])
        except Exception as exc:
            print(f"[{interval}] [ERROR] No se procesa esta temporalidad: {exc}")
            _log_data_error(state, interval, exc, now_ms)

    for interval in BITMAN_INTERVALS:
        if interval in market:
            try:
                _process_bitman(interval, market[interval]["live"], market[interval]["closed"], state)
            except Exception as exc:
                print(f"[BITMAN {interval}] [ERROR] {exc}")
                _append_history({"record_type": "processing_error", "system": "bitman",
                                 "interval": interval, "event_time_ms": _utc_now_ms(), "message": str(exc)[:500]})

    for interval in KONCORDE_INTERVALS:
        if interval in market:
            try:
                _process_koncorde(interval, market[interval]["live"], market[interval]["closed"], state)
            except Exception as exc:
                print(f"[KONCORDE {interval}] [ERROR] {exc}")
                _append_history({"record_type": "processing_error", "system": "koncorde",
                                 "interval": interval, "event_time_ms": _utc_now_ms(), "message": str(exc)[:500]})

    for interval in ML_RSI_INTERVALS:
        if interval in market:
            try:
                _process_ml_rsi(interval, market[interval]["ml_live"],
                                market[interval]["ml_closed"], state,
                                is_provisional=market[interval]["has_live"])
            except Exception as exc:
                print(f"[ML RSI {interval}] [ERROR] {exc}")
                _append_history({"record_type": "processing_error", "system": "ml_rsi",
                                 "interval": interval, "event_time_ms": _utc_now_ms(), "message": str(exc)[:500]})

    if current_price is not None:
        _track_outcomes(state, current_price, now_ms)
    _send_daily_summary(state, now_ms, market)
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR FATAL] {e}")
        sys.exit(1)
