import time
import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, OrderSide, TimeInForce
from datetime import datetime, timedelta
import signal
import sys

# === CONFIG ===
API_KEY = 'PKKUCJVAZLF7GKPECYSN'
API_SECRET = 'Ddgcx9mPfLX7yir2s6EJ1eY4lAKK2TM3IhbS2CS9'
SYMBOLS = ['AAPL', 'MSFT', 'TSLA','AMZN','GOOGL','META','NVDA','INTC','AMD','BAC']
RSI_PERIOD = 14
STOP_LOSS_PCT = 0.05
TAKE_PROFIT_PCT = 0.10
ORDER_SIZE_DOLLARS = 10  # per trade

# === Alpaca Clients ===
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
trade_client = TradingClient(API_KEY, API_SECRET, paper=True)

import requests

def check_iex_quote(symbol, API_KEY, API_SECRET):
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest?feed=iex"
    headers = {
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"IEX quote fetch failed for {symbol}: {response.status_code} {response.text}")
        return None


# === Globals to track trades for CSV export ===
trade_log = []

def fetch_latest_data(symbol, minutes=100):
    now = datetime.utcnow()
    past = now - timedelta(minutes=minutes)
    request_params = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=past,
        end=now,
        provider='iex'
    )
    bars = data_client.get_stock_bars(request_params).df
    df = bars[bars.index.get_level_values(0) == symbol].copy()
    if df.empty:
        return None
    df = df.reset_index()
    df['close'] = df['close'].astype(float)
    return df

def calculate_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    gain = up.rolling(period).mean()
    loss = down.rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def get_position(symbol):
    try:
        pos = trade_client.get_open_position(symbol)
        qty = float(pos.qty)
        entry_price = float(pos.avg_entry_price)
        return qty, entry_price
    except Exception:
        return 0, 0

def place_order(symbol, side, notional):
    order_request = MarketOrderRequest(
        symbol=symbol,
        notional=notional,
        side=side,
        time_in_force=TimeInForce.GTC,
    )
    order = trade_client.submit_order(order_request)
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {side.value.upper()} order placed for {symbol} at ${notional:.2f}")
    trade_log.append({
        'timestamp': datetime.now(),
        'symbol': symbol,
        'side': side.value,
        'notional': notional,
    })

def signal_handler(sig, frame):
    print("\nGraceful shutdown detected, saving trade log...")
    if trade_log:
        df = pd.DataFrame(trade_log)
        df.to_csv("alpaca_live_trades.csv", index=False)
        print(f"Saved {len(trade_log)} trades to alpaca_live_trades.csv")
    else:
        print("No trades to save.")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)  # Handle Ctrl+C

def main():
    print(f"Starting multi-symbol live RSI trading bot with Alpaca paper account...")
    print(f"Symbols: {SYMBOLS}")
    print(f"Order size: ${ORDER_SIZE_DOLLARS} each")
    
    for symbol in SYMBOLS:
        quote = check_iex_quote(symbol, API_KEY, API_SECRET)
        if quote is None:
            print(f"Skipping {symbol} due to IEX feed access issues")
            SYMBOLS.remove(symbol)


    while True:
        for symbol in SYMBOLS:
            try:
                df = fetch_latest_data(symbol, minutes=100)
                if df is None or len(df) < RSI_PERIOD:
                    print(f"No or insufficient data for {symbol}, skipping.")
                    continue
                if len(df) < RSI_PERIOD:
                    print(f"Not enough data for {symbol}, skipping")
                    continue
                df['rsi'] = calculate_rsi(df['close'], RSI_PERIOD)
                rsi_now = df['rsi'].iloc[-1]
                price_now = df['close'].iloc[-1]

                qty, entry_price = get_position(symbol)

                print(f"{datetime.now().strftime('%H:%M:%S')} | {symbol} | Price: {price_now:.3f} | RSI: {rsi_now:.2f} | Qty: {qty}")

                if qty == 0:
                    # No position: Buy if RSI low
                    if rsi_now < 40:
                        place_order(symbol, OrderSide.BUY, ORDER_SIZE_DOLLARS)
                else:
                    stop_price = entry_price * (1 - STOP_LOSS_PCT)
                    take_profit_price = entry_price * (1 + TAKE_PROFIT_PCT)

                    # Check stop loss
                    if price_now <= stop_price:
                        print(f"Stop-loss triggered for {symbol} at {price_now:.2f}")
                        place_order(symbol, OrderSide.SELL, qty * price_now)
                    # Check take profit
                    elif price_now >= take_profit_price:
                        print(f"Take-profit triggered for {symbol} at {price_now:.2f}")
                        place_order(symbol, OrderSide.SELL, qty * price_now)
                    # RSI exit
                    elif rsi_now > 60:
                        print(f"RSI exit triggered for {symbol} at {price_now:.2f}")
                        place_order(symbol, OrderSide.SELL, qty * price_now)

            except Exception as e:
                print(f"Error processing {symbol}: {e}")

        time.sleep(60)  # Run roughly every minute

if __name__ == "__main__":
    main()

