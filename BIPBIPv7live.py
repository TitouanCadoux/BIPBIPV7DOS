import sys
sys.path.append("./live_tools")
import ccxt
import ta
import pandas as pd
from utilities.perp_bitget import PerpBitget
from utilities.custom_indicators import get_n_columns
from datetime import datetime
import time
import json

# === PARAMÈTRES ===
EMA_FAST = 200
EMA_SLOW = 300
ATR_PERIOD = 14
ATR_MULT_UPPER = 3
ATR_MULT_LOWER = 3
STOP_LOSS_PCT = 0.02    # 2 % stop-loss
RRR = 4                 # Risk / Reward ratio
POSITION_SIZE = 0.25
LEVERAGE = 25

PAIR = "SOL/USDT:USDT"
TIMEFRAME = "1m"

# Chargement des keys
with open("./BOT/secret.json") as f:
    secret = json.load(f)
bitget = PerpBitget(
    apiKey=secret["bitget_exemple"]["apiKey"],
    secret=secret["bitget_exemple"]["secret"],
    password=secret["bitget_exemple"]["password"],
)

print(f"\n--- Start {datetime.now():%d/%m/%Y %H:%M:%S} | {PAIR} ×{LEVERAGE} ---")

# === Récupération des données & indicateurs ===
df = bitget.get_more_last_historical_async(PAIR, TIMEFRAME, 1000)
df = df[["open","high","low","close","volume"]]
df["EMA_FAST"] = ta.trend.ema_indicator(df["close"], EMA_FAST)
df["EMA_SLOW"] = ta.trend.ema_indicator(df["close"], EMA_SLOW)
df["ATR"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], ATR_PERIOD)
df["ATR_UPPER"] = df["high"] + ATR_MULT_UPPER * df["ATR"]
df["ATR_LOWER"] = df["low"] - ATR_MULT_LOWER * df["ATR"]
df = get_n_columns(df, ["EMA_FAST","EMA_SLOW"], 1)
row = df.iloc[-2]
latest_price = df.iloc[-1]["close"]

# === État du compte & position ===
usd_balance = float(bitget.get_usdt_equity())
print(f"USDT balance: {usd_balance:.2f}")
active = [
    p for p in bitget.get_open_position()
    if p["symbol"] == PAIR
]
positions = [{
    "side": p["side"],
    "qty": float(p["contracts"]) * float(p["contractSize"])
} for p in active]

# Charge l'état des TP si existant
tp_data = {}
if os.path.isfile("live_tp.json"):
    with open("live_tp.json") as f:
        tp_data = json.load(f)

def crossed_up(r):   return r["EMA_FAST"] > r["EMA_SLOW"] and r["n1_EMA_FAST"] <= r["n1_EMA_SLOW"]
def crossed_down(r): return r["EMA_FAST"] < r["EMA_SLOW"] and r["n1_EMA_FAST"] >= r["n1_EMA_SLOW"]
open_long = crossed_up
open_short = crossed_down

# === Gestion de la position ouverte ===
if positions:
    pos = positions[0]
    side = pos["side"]
    qty_total = pos["qty"]
    print(f"Position active: {side.upper()} qty={qty_total:.4f}")

    # Evénements TP / SL
    price = latest_price

    # Stop-loss fixe
    if side == "long" and price <= tp_data.get("entry_price", 0) * (1 - STOP_LOSS_PCT):
        print("❌ SL atteint → fermeture complète")
        bitget.place_market_order(PAIR, "sell", qty_total, reduce=True)
        tp_data.clear()

    elif side == "short" and price >= tp_data.get("entry_price", 0) * (1 + STOP_LOSS_PCT):
        print("❌ SL atteint → fermeture complète")
        bitget.place_market_order(PAIR, "buy", qty_total, reduce=True)
        tp_data.clear()

    else:
        # TP1
        tp1 = tp_data.get("tp1_price")
        if tp1 and not tp_data.get("tp1_hit"):
            if (side=="long" and price>=tp1) or (side=="short" and price<=tp1):
                partial = qty_total * 0.25
                act = "sell" if side=="long" else "buy"
                print(f"💰 TP1 atteint à {tp1:.4f} → {act} {partial:.4f}")
                bitget.place_market_order(PAIR, act, partial, reduce=True)
                tp_data["tp1_hit"] = True

        # TP2
        tp2 = tp_data.get("tp2_price")
        if tp2 and not tp_data.get("tp2_hit"):
            if (side=="long" and price>=tp2) or (side=="short" and price<=tp2):
                partial = qty_total * 0.50
                act = "sell" if side=="long" else "buy"
                print(f"💰 TP2 atteint à {tp2:.4f} → {act} {partial:.4f}")
                bitget.place_market_order(PAIR, act, partial, reduce=True)
                tp_data["tp2_hit"] = True

        # TP3 (RRR)
        tp3 = tp_data.get("tp_price")
        if tp3:
            cond3 = (side=="long" and price>=tp3) or (side=="short" and price<=tp3)
            if cond3:
                act = "sell" if side=="long" else "buy"
                print(f"🎯 TP3 atteint à {tp3:.4f} → fermeture complète")
                bitget.place_market_order(PAIR, act, qty_total, reduce=True)
                tp_data.clear()

    # Sauvegarde ou nettoyage de l'état
    if tp_data:
        with open("live_tp.json","w") as f:
            json.dump(tp_data, f)
    else:
        if os.path.isfile("live_tp.json"):
            os.remove("live_tp.json")

# === Pas de position : ouverture si signal ===
else:
    print("Pas de position → vérification des entrées...")
    notional = usd_balance * POSITION_SIZE * LEVERAGE

    if open_long(row) or open_short(row):
        side = "long" if open_long(row) else "short"
        qty = float(bitget.convert_amount_to_precision(PAIR, notional / latest_price))
        act = "buy" if side=="long" else "sell"
        print(f"🚀 Ouverture {side.upper()} qty={qty:.4f}")
        bitget.place_market_order(PAIR, act, qty, reduce=False)

        # Calcul TP fractionnés
        entry = latest_price
        atr_band = df.iloc[-1]["ATR_LOWER"] if side=="long" else df.iloc[-1]["ATR_UPPER"]
        risk_pct = abs(entry - atr_band) / entry
        rr_pct = risk_pct * RRR
        tp_price = entry * (1 + rr_pct) if side=="long" else entry * (1 - rr_pct)
        tp1_price = entry * (1 + 0.01) if side=="long" else entry * (1 - 0.01)
        tp2_price = entry * (1 + 0.02) if side=="long" else entry * (1 - 0.02)

        tp_data = {
            "side": side,
            "entry_price": entry,
            "tp_price": tp_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "tp1_hit": False,
            "tp2_hit": False
        }
        with open("live_tp.json","w") as f:
            json.dump({**tp_data, "qty": qty}, f)

# === Fin
print(f"--- End {datetime.now():%d/%m/%Y %H:%M:%S} ---")
