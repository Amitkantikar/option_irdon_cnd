"""
LIVE MARKET LOGGER FOR WEEKLY IRON CONDOR ON NIFTY
--------------------------------------------------
Runs continuously (or via GitHub Actions cron) and logs:
 - Entry (strikes, credit)
 - Live SL hit / Target hit
 - Exit price
 - Profit/loss
 - Running capital
 - Timestamp

Trades are stored in ic_live_trades.csv
"""

import yfinance as yf
import pandas as pd
import os
from datetime import datetime

# -------------------------
# USER PARAMETERS
# -------------------------
SYMBOL = "^NSEI"           # NIFTY INDEX
SHORT_STRIKE_PCT = 0.025
WING_WIDTH_PCT  = 0.05
CREDIT_PCT = 0.012
DEPLOY_FRACTION = 0.60
INITIAL_CAPITAL = 1_000_000

CSV_FILE = "ic_live_trades.csv"

# -------------------------
# Helpers
# -------------------------
def fetch_live_price():
    data = yf.Ticker(SYMBOL).history(period="1m", interval="1m")
    if data.empty:
        return None
    return float(data["Close"].iloc[-1])

def load_state():
    if not os.path.exists(CSV_FILE):
        return pd.DataFrame(), INITIAL_CAPITAL, None
    
    df = pd.read_csv(CSV_FILE)

    if df.empty:
        return df, INITIAL_CAPITAL, None

    capital = df["capital_after"].iloc[-1]

    # find open trade
    open_trade = df[df["status"] == "OPEN"]
    if not open_trade.empty:
        return df, capital, open_trade.iloc[-1]
    return df, capital, None

def save_trade_row(row):
    header = not os.path.exists(CSV_FILE)
    pd.DataFrame([row]).to_csv(CSV_FILE, mode="a", header=header, index=False)

# -------------------------
# ENTRY LOGIC (WEEKLY)
# -------------------------
def enter_trade(capital):
    spot = fetch_live_price()
    if spot is None:
        return None

    notional = capital * DEPLOY_FRACTION

    short_call = spot * (1 + SHORT_STRIKE_PCT)
    short_put  = spot * (1 - SHORT_STRIKE_PCT)

    long_call  = short_call * (1 + WING_WIDTH_PCT / (1 + SHORT_STRIKE_PCT))
    long_put   = short_put  * (1 - WING_WIDTH_PCT / (1 - SHORT_STRIKE_PCT))

    credit = CREDIT_PCT * notional

    row = {
        "timestamp": datetime.now(),
        "entry_price": spot,
        "short_call": short_call,
        "long_call": long_call,
        "short_put": short_put,
        "long_put": long_put,
        "credit": credit,
        "exit_price": "",
        "pnl": "",
        "capital_after": "",
        "status": "OPEN"
    }

    return row

# -------------------------
# EXIT LOGIC (SL / TARGET)
# -------------------------
def exit_logic(open_trade, capital):
    spot = fetch_live_price()
    if spot is None:
        return None, None

    sc = open_trade["short_call"]
    sp = open_trade["short_put"]
    lc = open_trade["long_call"]
    lp = open_trade["long_put"]
    credit = open_trade["credit"]

    max_loss = (WING_WIDTH_PCT * (open_trade["entry_price"])) * DEPLOY_FRACTION - (credit / 2)

    pnl = credit  # default: credit earned

    # Call side breach
    if spot > sc:
        if spot >= lc:
            pnl = -max_loss
        else:
            pct = (spot - sc) / (lc - sc)
            pnl = credit + (-pct * max_loss)

    # Put side breach
    if spot < sp:
        if spot <= lp:
            pnl = -max_loss
        else:
            pct = (sp - spot) / (sp - lp)
            pnl = credit + (-pct * max_loss)

    row = open_trade.copy()
    row["timestamp"] = datetime.now()
    row["exit_price"] = spot
    row["pnl"] = pnl
    row["capital_after"] = capital + pnl
    row["status"] = "CLOSED"

    return row, capital + pnl

# -------------------------
# MAIN LOOP (1 execution)
# -------------------------
if __name__ == "__main__":
    df, capital, open_trade = load_state()

    # If NO open trade → Enter new trade
    if open_trade is None:
        new_trade = enter_trade(capital)
        if new_trade:
            save_trade_row(new_trade)
            print("New trade opened:", new_trade)
        else:
            print("Failed to fetch price.")
        exit()

    # If open trade exists → Check if exit needed
    exit_row, new_capital = exit_logic(open_trade, capital)

    if exit_row is not None:
        save_trade_row(exit_row)
        print("Trade closed:", exit_row)
    else:
        print("Trade continues... Spot:", fetch_live_price())
