"""
Alerta Koncorde -> Telegram
============================
Se ejecuta repetidamente (cada 5 min) dentro del bucle del workflow de
GitHub Actions (.github/workflows/koncorde.yml), que se auto-relanza cada
~5h40m para funcionar de forma indefinida. Cada ejecucion de este script:

  1. Descarga velas de Binance para 1h y 1d (incluida la vela EN CURSO,
     todavia sin cerrar, que Binance sigue actualizando en vivo)
  2. Calcula el Koncorde (verde, marron, azul, media), el Trend Speed
     Analyzer (dyn_ema, tsa_bullish), el ADX (fuerza de tendencia), el AO,
     el BBWP y el veredicto Bitman para cada temporalidad
  3. Revisa 3 sistemas de aviso independientes, TODOS sobre la vela EN
     CURSO (no esperan al cierre, para notificar en el instante en que se
     produce el cambio, replicando el comportamiento "Una vez por barra"
     de la alerta original de TradingView):
     - Cruces (con desglose de 3 condiciones validadas con datos
       historicos: valor, Trend Speed Analyzer, ADX)
     - Bitman (COMPRAR/VENDER/ESPERAR)
     - ML RSI (verde/rojo/gris)
  4. Manda por Telegram el aviso correspondiente (fusionando cruce y
     Bitman en un unico mensaje si ambos tienen algo nuevo en la misma
     pasada), incluyendo al final un resumen del estado EN VIVO de las
     temporalidades configuradas
  5. Guarda en state.json la ultima posicion/veredicto conocido de cada
     temporalidad, para avisar solo en los cambios reales

IMPORTANTE -- esto puede repintarse: al evaluar la vela todavia en
formacion (no cerrada), un cruce o un cambio de veredicto puede aparecer y
revertirse varias veces antes de que la vela termine, generando avisos que
se contradicen entre si dentro de la misma hora/dia. Es una decision
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
import tempfile
from pathlib import Path

import requests
import pandas as pd
import numpy as np

SYMBOL = "BTCUSDT"
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
