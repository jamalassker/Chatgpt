import time, requests, numpy as np, pandas as pd
from binance.client import Client
from binance.enums import *

# --- HARDCODED CREDENTIALS ---
API_KEY = 'Et7oRtg2CLHyaRGBoQOoTFt7LSixfav28k0bnVfcgzxd2KTal4xPlxZ9aO6sr1EJ'
API_SECRET = '2LfotApekUjBH6jScuzj1c47eEnq1ViXsNRIP4ydYqYWl6brLhU3JY4vqlftnUIo'
TG_TOKEN = '8560134874:AAHF4efOAdsg2Y01eBHF-2DzEUNf9WAdniA'
TG_CHAT_ID = '5665906172'

client = Client(API_KEY, API_SECRET, testnet=True)
SYMBOL = 'BTCUSDT'
TRADE_SIZE = 0.00015 

def send_tg(msg):
    try: requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage?chat_id={TG_CHAT_ID}&text={msg}")
    except: pass

def get_apex_signals():
    # 1. Fetch Order Book Depth (The HFT "Secret Sauce")
    depth = client.get_order_book(symbol=SYMBOL, limit=20)
    bid_vol = sum([float(b[1]) for b in depth['bids']])
    ask_vol = sum([float(a[1]) for a in depth['asks']])
    obi = (bid_vol - ask_vol) / (bid_vol + ask_vol) # Range -1 to 1
    
    # 2. Fetch Klines for VWAP & Z-Score
    klines = client.get_klines(symbol=SYMBOL, interval='1m', limit=30)
    df = pd.DataFrame(klines, columns=['t','o','h','l','c','v','ct','qa','nt','tb','tq','i']).astype(float)
    
    # VWAP Calculation
    df['tp'] = (df['h'] + df['l'] + df['c']) / 3
    vwap = (df['tp'] * df['v']).sum() / df['v'].sum()
    
    # Z-Score
    mean = df['c'].mean()
    z_score = (df['c'].iloc[-1] - mean) / (df['c'].std() + 0.00001)
    
    return z_score, obi, vwap, df['c'].iloc[-1]

print("🌑 Apex AI HFT Core Initializing...")
send_tg("🕵️‍♂️ APEX HFT ONLINE\nAnalyzing Order Book Depth & VWAP\nMonitoring $10 Scalp Opportunities")

in_pos = False
last_buy = 0

while True:
    try:
        z, obi, vwap, price = get_apex_signals()
        
        # BUY: Price is cheap (Z < -2.0) AND Order Book shows Buy Pressure (OBI > 0.3)
        if not in_pos and z < -2.0 and obi > 0.3 and price < vwap:
            client.create_order(symbol=SYMBOL, side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=TRADE_SIZE)
            last_buy = price
            send_tg(f"🔥 APEX BUY\nPrice: {price}\nOBI: {obi:.2f} (Strong Demand)\nZ: {z:.2f}")
            in_pos = True
            
        # SELL: Price is over-extended (Z > 1.8) OR Profit target hit
        elif in_pos and (z > 1.8 or price > (last_buy * 1.002)): # 0.2% Scalp
            client.create_order(symbol=SYMBOL, side=SIDE_SELL, type=ORDER_TYPE_MARKET, quantity=TRADE_SIZE)
            send_tg(f"💰 APEX PROFIT\nPrice: {price}\nStrategy: Micro-Scalp Successful")
            in_pos = False

        time.sleep(2) # Ultra-fast 2026 polling
        
    except Exception as e:
        print(f"Latency/API Error: {e}")
        time.sleep(1)


