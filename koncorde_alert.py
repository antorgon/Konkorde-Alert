"""
Alerta Koncorde -> Telegram
============================
Se ejecuta repetidamente (cada 5 min) dentro del bucle del workflow de
GitHub Actions (.github/workflows/koncorde.yml), que se auto-relanza cada
~5h40m para funcionar de forma indefinida. Cada ejecucion de este script:

  1. Descarga velas de Binance para 1h, 4h y 1d (incluida la vela EN CURSO,
     todavia sin cerrar, que Binance sigue actualizando en vivo)
  2. Calcula el Koncorde (verde, marron, azul, media), el Trend Speed
     Analyzer (dyn_ema, tsa_bullish), el ADX (fuerza de tendencia), el AO,
     el BBWP y el veredicto Bitman para cada temporalidad
  3. Revisa 2 sistemas de aviso independientes, AMBOS sobre la vela EN
     CURSO (no esperan al cierre, para notificar en el instante en que se
     produce el cambio, replicando el comportamiento "Una vez por barra"
     de la alerta original de TradingView):
     - Cruces (con desglose de 3 condiciones validadas con datos
       historicos: valor, Trend Speed Analyzer, ADX)
     - Bitman (COMPRAR/VENDER/ESPERAR)
  4. Manda por Telegram el aviso correspondiente, incluyendo al final un
     resumen del estado EN VIVO de las otras 2 temporalidades
  5. Guarda en state.json la ultima posicion/veredicto conocido de cada
     temporalidad, para avisar solo en los cambios reales

IMPORTANTE -- esto puede repintarse: al evaluar la vela todavia en
formacion (no cerrada), un cruce o un cambio de veredicto puede aparecer y
revertirse varias veces antes de que la vela termine, generando avisos que
se contradicen entre si dentro de la misma hora/4h/dia. Es una decision
deliberada (prioriza la inmediatez sobre la limpieza de la señal), no un
fallo.

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
historico de BTCUSDT. OJO: ese analisis se hizo sobre cruces YA CERRADOS,
no hay garantia de que los mismos umbrales se comporten igual de bien
sobre cruces intra-vela como los que genera este script ahora.

Nota sobre color: Telegram no permite texto de color en sus mensajes de
bot, asi que "alcista"/"bajista" se marcan con 🟢/🔴 como sustituto.
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


def _col(texto: str) -> str:
    """Antepone 🟢/🔴 a 'alcista'/'bajista' (Telegram no soporta color de
    texto real en sus mensajes, esto es el sustituto habitual)."""
    if "alcista" in texto:
        return f"🟢 {texto}"
    if "bajista" in texto:
        return f"🔴 {texto}"
    return texto


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
# resto del sistema, que ya revisa 1h/4h/1d de forma independiente.


def compute_ao(df: pd.DataFrame) -> pd.DataFrame:
    """Awesome Oscillator (5/34) y su estado de 4 valores."""
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


def compute_bbwp(df: pd.DataFrame, length: int = 13, lookback: int = 252) -> pd.DataFrame:
    """BBWP: percentil (0-100) de la anchura de las Bandas de Bollinger
    frente a su propio historial. Puramente informativo -- en el panel
    original tampoco participa en la logica COMPRAR/VENDER/ESPERAR (solo se
    muestra como contexto de volatilidad), asi que aqui se calcula pero no
    condiciona el veredicto."""
    df = df.copy()
    basis = df["close"].rolling(length).mean()
    dev = df["close"].rolling(length).std(ddof=0)
    width = 2 * dev / basis

    def _pct_rank(x):
        last = x[-1]
        if np.isnan(last):
            return np.nan
        valid = x[~np.isnan(x)]
        if valid.size == 0:
            return np.nan
        return (valid <= last).mean() * 100

    df["bbwp"] = width.rolling(lookback, min_periods=5).apply(_pct_rank, raw=True)
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


def compute_veredicto(df: pd.DataFrame) -> pd.DataFrame:
    """Requiere que el df ya tenga 'verde', 'marron' (de compute_koncorde) y
    'adx' (de compute_adx) calculados. Añade 'kon_val' (criterio Bitman:
    el mayor entre verde/marron, o el mas negativo si ambos son negativos),
    'bbwp' (informativo, no cuenta) y 'veredicto' (COMPRAR / VENDER / ESPERAR)."""
    df = compute_ao(df)
    df = compute_bbwp(df)
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


def resumen_otras_temporalidades_bitman(otros_ver: dict) -> str:
    """Linea por cada otra temporalidad con su veredicto EN VIVO actual
    (COMPRAR en verde, VENDER en rojo, ESPERAR sin colorear)."""
    lineas = []
    for iv, odf_ver in otros_ver.items():
        v = odf_ver.iloc[-1]["veredicto"]
        icono = "🟢" if v == "COMPRAR" else "🔴" if v == "VENDER" else "⚪"
        lineas.append(f"{iv}: {icono} {v}")
    return "Otras temporalidades:\n" + "\n".join(lineas) if lineas else ""


def revisar_veredicto(df_ver: pd.DataFrame, interval: str, state: dict, otros_ver: dict) -> bool:
    """Revisa el sistema de veredicto (2ª via, independiente del cruce) para
    una temporalidad. 'df_ver' debe venir YA con compute_veredicto aplicado.
    Mira la vela EN CURSO (iloc[-1], se sigue actualizando en vivo) para
    avisar en el instante en que el veredicto cambia, sin esperar a que la
    vela cierre -- por eso puede repintarse (el veredicto puede revertirse
    antes de que la vela termine). Devuelve True si el estado cambio."""
    if len(df_ver) < 2:
        print(f"[{interval}][veredicto] Datos insuficientes, se omite esta pasada.")
        return False

    ultima = df_ver.iloc[-1]
    veredicto_actual = ultima["veredicto"]

    state_key = f"last_veredicto_{interval}"
    veredicto_previo = state.get(state_key)

    if veredicto_previo == veredicto_actual:
        print(f"[{interval}][veredicto] Sin cambio: sigue en {veredicto_actual}.")
        return False

    state[state_key] = veredicto_actual

    if veredicto_previo is None:
        # primera vez que se evalua esta temporalidad (arranque del ciclo):
        # se guarda el veredicto base sin avisar, no es un cambio real
        print(f"[{interval}][veredicto] Veredicto inicial registrado: {veredicto_actual}")
        return True

    if veredicto_actual == "COMPRAR":
        motivo = _col("AO alcista") + " + ADX con impulso + Koncorde confirma acumulacion"
    elif veredicto_actual == "VENDER":
        motivo = _col("AO bajista") + " + ADX con impulso + Koncorde confirma distribucion"
    else:
        anterior = df_ver.iloc[-2]  # ultima vela ya cerrada, referencia para "¿el ADX esta subiendo?"
        fila = dict(ultima)
        fila["_adx_subiendo"] = ultima["adx"] > anterior["adx"]
        motivo = _col(motivo_espera(fila))

    resumen_otras = resumen_otras_temporalidades_bitman(otros_ver)

    msg = (
        f"Bitman {SYMBOL} {interval}\n"
        f"{veredicto_previo} -> {veredicto_actual}\n"
        f"{motivo}\n"
        f"AO: {ultima['ao']:.1f} ({_col(ultima['ao_estado'])})\n"
        f"Koncorde (todo el valor): {ultima['kon_val']:.1f}\n"
        f"ADX: {ultima['adx']:.1f}\n"
        f"{bbwp_texto(ultima['bbwp'])}\n"
        f"⚠️ Vela todavia en formacion, puede repintarse\n"
        f"Precio actual: {ultima['close']:.2f}"
        + (f"\n\n{resumen_otras}" if resumen_otras else "")
    )
    print(msg)
    send_telegram(msg)
    return True


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


ICONO_VALOR = {"dentro": "🟢", "extendido": "🟡", "contrario": "🔴"}
TEXTO_VALOR = {
    "dentro": "dentro del rango validado",
    "extendido": "fuera de rango, en pleno proceso (sin ventaja estadistica demostrada)",
    "contrario": "direccion contraria al cruce",
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
        elif verde_val > VALOR_MAX_ALZA:
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


def resumen_otras_temporalidades_cruce(otros_dfs: dict) -> str:
    """Linea por cada otra temporalidad: posicion EN VIVO actual (verde vs
    media, sin que haga falta cruce) y cuantas de las 3 condiciones se
    cumplen ahora mismo."""
    lineas = []
    for iv, odf in otros_dfs.items():
        ult = odf.iloc[-1]
        direccion_actual = "alza" if ult["verde"] > ult["media"] else "baja"
        c = evaluar_condiciones_koncorde(ult, direccion_actual)
        estado_txt = _col("alcista" if direccion_actual == "alza" else "bajista")
        lineas.append(f"{iv}: {estado_txt}, {c['n_ok']}/3")
    return "Otras temporalidades:\n" + "\n".join(lineas) if lineas else ""


def revisar_intervalo(df: pd.DataFrame, interval: str, state: dict, otros_dfs: dict) -> bool:
    """Revisa una temporalidad y actualiza 'state' in-place. 'df' debe traer
    ya calculados verde/marron/media (compute_koncorde), tsa_bullish
    (compute_trend_speed) y adx/di_plus/di_minus (compute_adx). 'otros_dfs'
    son los df ya calculados de las demas temporalidades, para el resumen
    al final del mensaje del cruce.
    Mira la vela EN CURSO (iloc[-1]) para avisar en el instante en que
    'verde' cruza 'media', sin esperar a que la vela cierre -- por eso
    puede repintarse (el cruce puede revertirse antes de que la vela
    termine). Devuelve True si el estado cambio (para saber si hay que
    guardar)."""
    if len(df) < 2:
        print(f"[{interval}] Datos insuficientes, se omite esta pasada.")
        return False

    ultima = df.iloc[-1]
    direccion = "alza" if ultima["verde"] > ultima["media"] else "baja"

    state_key_pos = f"last_live_pos_{interval}"
    direccion_previa = state.get(state_key_pos)

    if direccion_previa == direccion:
        print(f"[{interval}] Sin cambio de posicion (sigue {direccion}).")
        return False

    state[state_key_pos] = direccion

    if direccion_previa is None:
        # primera vez que se evalua esta temporalidad (arranque del ciclo):
        # se guarda la posicion base sin avisar, no es un cambio real
        print(f"[{interval}] Posicion inicial registrada: {direccion}")
        return True

    state_changed = True

    c = evaluar_condiciones_koncorde(ultima, direccion)
    verde_val, tsa_bullish, adx_val = c["verde_val"], c["tsa_bullish"], c["adx_val"]
    valor_estado, rango_valor_txt = c["valor_estado"], c["rango_valor_txt"]
    valor_ok, tsa_ok, adx_ok, n_ok = c["valor_ok"], c["tsa_ok"], c["adx_ok"], c["n_ok"]

    def _icono(ok):
        return "✅" if ok else "❌"

    desglose = (
        f"Valor verde: {verde_val:.1f} {ICONO_VALOR[valor_estado]} "
        f"({TEXTO_VALOR[valor_estado]}, rango validado {rango_valor_txt})\n"
        f"Trend Speed Analyzer: {_col('alcista' if tsa_bullish else 'bajista')} {_icono(tsa_ok)}\n"
        f"ADX: {adx_val:.1f} {_icono(adx_ok)} (≥{ADX_MEDIO:.0f} y DI dominante a favor)"
    )
    resumen_otras = resumen_otras_temporalidades_cruce(otros_dfs)

    # --- 1) Alerta inmediata del cruce, con el desglose de las 3 condiciones ---
    msg = (
        f"Koncorde {SYMBOL} {interval}\n"
        f"{CROSS_DESC[direccion]}\n"
        f"⚠️ Vela todavia en formacion, puede repintarse\n"
        f"Precio actual: {ultima['close']:.2f}\n\n"
        f"{desglose}"
        + (f"\n\n{resumen_otras}" if resumen_otras else "")
    )
    print(msg)
    send_telegram(msg)

    # --- 2) Confirmacion TOTAL (3/3) o PARCIAL (2/3), nunca las dos a la vez ---
    if n_ok == 3:
        msg_conf = (
            f"Koncorde {SYMBOL} {interval}\n"
            f"{CONFIRMED_DESC[direccion]}\n"
            f"Precio actual: {ultima['close']:.2f}"
        )
        print(msg_conf)
        send_telegram(msg_conf)
    elif n_ok == 2:
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
            f"Precio actual: {ultima['close']:.2f}"
        )
        print(msg_partial)
        send_telegram(msg_partial)
    else:
        print(
            f"[{interval}] Solo {n_ok}/3 condiciones cumplidas "
            f"(valor_ok={valor_ok}, tsa_ok={tsa_ok}, adx_ok={adx_ok}). Sin aviso adicional."
        )

    return state_changed


def main():
    state = load_state()
    state_changed = False

    # --- Paso 1: descargar y calcular las 3 temporalidades por adelantado.
    # Hace falta tener las 3 listas antes de revisar ninguna, porque cada
    # mensaje ahora incluye un resumen del estado de las OTRAS 2
    # temporalidades al final. ---
    dfs = {}
    dfs_ver = {}
    for interval in INTERVALS:
        try:
            df = get_klines(interval=interval)
            df = compute_koncorde(df)
            df = compute_trend_speed(df)
            df = compute_adx(df)
            dfs[interval] = df
            dfs_ver[interval] = compute_veredicto(df)
        except Exception as e:
            print(f"[{interval}] [ERROR] {e}")

    # --- Paso 2: revisar cada temporalidad, con acceso a los datos ya
    # calculados de las demas para el resumen. ---
    for interval in INTERVALS:
        if interval not in dfs:
            continue
        otros_dfs = {iv: dfs[iv] for iv in INTERVALS if iv != interval and iv in dfs}
        otros_ver = {iv: dfs_ver[iv] for iv in INTERVALS if iv != interval and iv in dfs_ver}

        try:
            if revisar_intervalo(dfs[interval], interval, state, otros_dfs):
                state_changed = True
        except Exception as e:
            # Si falla una temporalidad (ej. un fallo puntual de red), las
            # demas se siguen revisando igualmente.
            print(f"[{interval}] [ERROR] {e}")

        if interval in dfs_ver:
            try:
                if revisar_veredicto(dfs_ver[interval], interval, state, otros_ver):
                    state_changed = True
            except Exception as e:
                print(f"[{interval}][veredicto] [ERROR] {e}")

    if state_changed:
        save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
