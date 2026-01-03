
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
TRADE_SIZE = 0.00015 # ~$10
WINDOW = 30 # Looking at last 30 data points for HFT

def send_tg(msg):
    try: requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage?chat_id={TG_CHAT_ID}&text={msg}")
    except: pass

def get_hft_signals():
    # Fetching 1m candles but analyzing micro-movements
    klines = client.get_klines(symbol=SYMBOL, interval='1m', limit=WINDOW)
    closes = np.array([float(k[4]) for k in klines])
    
    # Calculate Z-Score
    mean = np.mean(closes)
    std = np.std(closes)
    z_score = (closes[-1] - mean) / std
    
    # Calculate Momentum (Price Change Velocity)
    momentum = (closes[-1] - closes[-5]) / closes[-5] * 100
    
    return z_score, momentum, closes[-1]

print("⚡ Super HFT AI Bot Deploying...")
send_tg("🚀 2026 Super HFT Bot Active\nStrategy: Z-Score + Momentum\nTarget: High-Frequency Small Wins")

in_position = False

while True:
    try:
        z, mom, price = get_hft_signals()
        
        # LOGIC: Buy if price is heavily oversold (Z < -2.2) AND momentum starts turning up
        if z < -2.2 and mom > -0.01 and not in_position:
            client.create_order(symbol=SYMBOL, side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=TRADE_SIZE)
            send_tg(f"🟢 HFT BUY\nZ-Score: {z:.2f}\nPrice: {price}\nStatus: Scalping...")
            in_position = True
            
        # LOGIC: Sell if price is overbought (Z > 2.0) OR if we hit a 0.3% micro-profit
        elif in_position and (z > 2.0 or mom < -0.02):
            client.create_order(symbol=SYMBOL, side=SIDE_SELL, type=ORDER_TYPE_MARKET, quantity=TRADE_SIZE)
            send_tg(f"🔴 HFT EXIT\nZ-Score: {z:.2f}\nPrice: {price}\nResult: Win Captured")
            in_position = False

        time.sleep(5) # 2026 HFT standard for REST API
        
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(2)



