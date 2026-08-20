"""
Analisis del valor de "verde" en los cruces del Koncorde
===========================================================
Pregunta a responder: el filtro de valor (0-50 para cruces alcistas, -50/0
para bajistas, este segundo rango era una suposicion propia sin base en
los criterios originales) ¿tiene sentido empiricamente?

Metodo: coge TODOS los cruces (alcistas y bajistas) del historico, agrupa
por el valor de "verde" en el momento del cruce, y mide el movimiento del
precio en las siguientes N horas. Si el rango 0-50 (alza) / -50-0 (baja)
realmente identifica entradas "tempranas" y de mejor calidad, los cruces
dentro de ese rango deberian tener, de media, mejor retorno a favor de la
direccion que los que caen fuera.

Uso:
    pip install pandas requests
    python analisis_valor_verde.py

Genera: analisis_valor_verde.md
"""

import time
from datetime import datetime, timezone

import requests
import pandas as pd
import numpy as np

SYMBOL = "BTCUSDT"
INTERVAL = "1h"
YEARS_BACK = 10
HORIZONTE_VELAS = 24   # cuantas velas hacia adelante se mide el retorno (24 = 1 dia en 1h)
WARMUP_CANDLES = 150   # velas iniciales descartadas (indicadores inestables)

BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"

# Rangos de valor de "verde" a comparar (mismos limites para ambas
# direcciones, para que la comparacion alza vs baja sea simetrica).
# Desglose mas fino en las zonas extremas (>50 / <-50) para comprobar si
# "moderadamente alto/bajo" (posible tendencia todavia en marcha) rinde
# distinto que "extremo" (posible agotamiento / entrada tardia).
BUCKETS = [
    (-float("inf"), -200, "< -200"),
    (-200, -100, "-200 a -100"),
    (-100, -50, "-100 a -50"),
    (-50, -25, "-50 a -25"),
    (-25, 0, "-25 a 0"),
    (0, 25, "0 a 25"),
    (25, 50, "25 a 50"),
    (50, 100, "50 a 100"),
    (100, 200, "100 a 200"),
    (200, float("inf"), "> 200"),
]


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
        time.sleep(0.2)

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


# --------------------------- CALCULO KONCORDE (igual que koncorde_alert.py) ---------------------------
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


def detectar_cruces(df: pd.DataFrame) -> pd.Series:
    cruza_arriba = (df["verde"].shift(1) <= df["media"].shift(1)) & (df["verde"] > df["media"])
    cruza_abajo = (df["verde"].shift(1) >= df["media"].shift(1)) & (df["verde"] < df["media"])
    señal = pd.Series(None, index=df.index, dtype=object)
    señal[cruza_arriba] = "alza"
    señal[cruza_abajo] = "baja"
    return señal


# --------------------------- ANALISIS ---------------------------
def analizar(df: pd.DataFrame, horizonte: int = HORIZONTE_VELAS) -> pd.DataFrame:
    df = df.iloc[WARMUP_CANDLES:].reset_index(drop=True)
    df["señal"] = detectar_cruces(df)

    # Retorno futuro: variacion del precio 'horizonte' velas despues del
    # cierre de la vela del cruce (positivo = subio, negativo = bajo)
    df["retorno_futuro_pct"] = (df["close"].shift(-horizonte) - df["close"]) / df["close"] * 100

    eventos = df[df["señal"].notna()].dropna(subset=["retorno_futuro_pct"]).copy()

    # Para cruces "alza": retorno a favor = subida (retorno positivo)
    # Para cruces "baja": retorno a favor = bajada (retorno negativo, se invierte el signo)
    eventos["retorno_a_favor_pct"] = np.where(
        eventos["señal"] == "alza", eventos["retorno_futuro_pct"], -eventos["retorno_futuro_pct"]
    )

    filas = []
    for direccion in ["alza", "baja"]:
        sub = eventos[eventos["señal"] == direccion]
        for lo, hi, etiqueta in BUCKETS:
            bucket = sub[(sub["verde"] > lo) & (sub["verde"] <= hi)]
            n = len(bucket)
            if n == 0:
                filas.append({"direccion": direccion, "rango_verde": etiqueta, "n_cruces": 0,
                               "pct_a_favor": None, "retorno_medio_pct": None})
                continue
            pct_a_favor = (bucket["retorno_a_favor_pct"] > 0).mean() * 100
            retorno_medio = bucket["retorno_a_favor_pct"].mean()
            filas.append({
                "direccion": direccion, "rango_verde": etiqueta, "n_cruces": n,
                "pct_a_favor": round(pct_a_favor, 1), "retorno_medio_pct": round(retorno_medio, 2),
            })
    return pd.DataFrame(filas)


def guardar_informe(tabla: pd.DataFrame):
    lineas = [
        f"# Analisis del valor de 'verde' en los cruces — {SYMBOL} {INTERVAL} (ultimos {YEARS_BACK} años)",
        "",
        f"Horizonte de medida: {HORIZONTE_VELAS} velas ({HORIZONTE_VELAS}h) tras el cruce.",
        "`pct_a_favor` = % de cruces en ese rango donde el precio se movio a favor de la",
        "direccion del cruce en ese horizonte. `retorno_medio_pct` = retorno medio a favor",
        "(positivo = bien, negativo = el precio se movio en contra de media).",
        "`z` = z-score frente al 50% esperado por azar (con n grande, |z|>3 es solido,",
        "|z|>2 es sugerente pero no concluyente, por debajo es indistinguible del azar).",
        "",
    ]
    for direccion in ["alza", "baja"]:
        lineas.append(f"## Cruces {direccion}")
        lineas.append("")
        lineas.append("| Rango de verde | Nº cruces | % a favor | z | Retorno medio a favor |")
        lineas.append("|---|---|---|---|---|")
        for _, row in tabla[tabla["direccion"] == direccion].iterrows():
            n = row["n_cruces"]
            if row["pct_a_favor"] is None or n == 0:
                pct, z_txt, ret = "-", "-", "-"
            else:
                p = row["pct_a_favor"] / 100
                se = (0.5 * 0.5 / n) ** 0.5
                z = (p - 0.5) / se if se > 0 else 0
                pct = f"{row['pct_a_favor']}%"
                z_txt = f"{z:.2f}"
                ret = f"{row['retorno_medio_pct']}%"
            lineas.append(f"| {row['rango_verde']} | {n} | {pct} | {z_txt} | {ret} |")
        lineas.append("")

    lineas.append(
        "_Si el rango 25-50 (alza) / <=-25 (baja) es realmente el mejor, esas filas deberian "
        "tener el % a favor, el z-score y el retorno medio mas altos dentro de su direccion. "
        "Presta especial atencion a si las zonas extremas (50-100, 100-200, >200 / sus "
        "equivalentes negativas) rinden distinto entre si -- eso indicaria si 'moderadamente "
        "extendido' y 'muy extendido' deberian tratarse como cosas distintas en vez de un "
        "unico bucket '>50'._"
    )

    with open("analisis_valor_verde.md", "w") as f:
        f.write("\n".join(lineas))
    print("\n".join(lineas))


def main():
    print(f"Descargando {YEARS_BACK} años de velas {INTERVAL} de {SYMBOL}...")
    df = get_historical_klines()
    print(f"{len(df)} velas descargadas. Calculando Koncorde...")
    df = compute_koncorde(df)
    print("Analizando cruces...")
    tabla = analizar(df)
    guardar_informe(tabla)
    print("\nListo: analisis_valor_verde.md generado.")


if __name__ == "__main__":
    main()
