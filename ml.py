import asyncio, aiohttp, numpy as np, pandas as pd
from binance import AsyncClient
from binance.enums import *

# --- CREDENTIALS (RE-INTEGRATED) ---
API_KEY = 'Et7oRtg2CLHyaRGBoQOoTFt7LSixfav28k0bnVfcgzxd2KTal4xPlxZ9aO6sr1EJ'
API_SECRET = '2LfotApekUjBH6jScuzj1c47eEnq1ViXsNRIP4ydYqYWl6brLhU3JY4vqlftnUIo'
TG_TOKEN = '8560134874:AAHF4efOAdsg2Y01eBHF-2DzEUNf9WAdniA'
TG_CHAT_ID = '5665906172'

# DYNAMICALLY FETCH TOP 100 USDT PAIRS
async def get_top_100_symbols(client):
    try:
        info = await client.get_exchange_info()
        # Filter for trading USDT pairs
        symbols = [s['symbol'] for s in info['symbols'] if s['status'] == 'TRADING' and s['symbol'].endswith('USDT')]
        # Sort or slice to get the top 100
        return symbols[:100]
    except Exception as e:
        print(f"Error fetching symbols: {e}")
        return ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT'] # Fallback

active_positions = {}

async def send_tg_async(msg):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    params = {'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp: return await resp.json()
    except: pass

async def get_elite_signals(client, symbol):
    # Fetching klines - Loosened window to 20 for faster signal generation
    klines = await client.get_klines(symbol=symbol, interval='1m', limit=20)
    df = pd.DataFrame(klines, columns=['t','o','h','l','c','v','ct','qav','nt','tbv','tqv','i']).astype(float)
    
    # VOLUME DELTA (The Aggressive Push)
    df['sell_vol'] = df['v'] - df['tbv']
    df['delta'] = df['tbv'] - df['sell_vol']
    avg_delta = df['delta'].mean()
    current_delta = df['delta'].iloc[-1]
    
    # OBI (Order Book Imbalance)
    depth = await client.get_order_book(symbol=symbol, limit=10)
    bid_v = sum([float(b[1]) for b in depth['bids']])
    ask_v = sum([float(a[1]) for a in depth['asks']])
    obi = (bid_v - ask_v) / (bid_v + ask_v)
    
    # Z-SCORE (Loosened from -2.1 to -1.8 for more trades)
    df['tp'] = (df['h'] + df['l'] + df['c']) / 3
    vwap = (df['tp'] * df['v']).sum() / (df['v'].sum() + 0.0001)
    z_score = (df['c'].iloc[-1] - df['c'].mean()) / (df['c'].std() + 0.00001)
    
    return z_score, obi, vwap, current_delta, avg_delta, df['c'].iloc[-1]

async def trade_logic(client, symbol):
    # $100 capital: roughly 18 slots of $5.20 to stay above Binance $5 minimum
    usd_per_trade = 5.2 
    max_concurrent_trades = 18 

    while True:
        try:
            z, obi, vwap, delta, avg_delta, price = await get_elite_signals(client, symbol)
            
            # Simple qty calculation (note: real production needs lot_size filtering)
            qty = round(usd_per_trade / price, 6)
            
            # ELITE LOOSER ENTRY: Z < -1.8 | OBI > 0.2 | Delta Push
            if symbol not in active_positions and len(active_positions) < max_concurrent_trades:
                if z < -1.8 and obi > 0.2 and delta > (avg_delta * 0.5):
                    await client.create_order(symbol=symbol, side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=qty)
                    active_positions[symbol] = {'p': price, 'q': qty}
                    await send_tg_async(f"⚡️ *ENTRY:* {symbol}\nPrice: `{price}`\nZ: `{z:.2f}`")

            # ELITE QUICK EXIT: 0.20% Profit Scalp or Overbought
            elif symbol in active_positions:
                buy_p = active_positions[symbol]['p']
                qty_pos = active_positions[symbol]['q']
                
                if z > 1.5 or price > (buy_p * 1.002):
                    await client.create_order(symbol=symbol, side=SIDE_SELL, type=ORDER_TYPE_MARKET, quantity=qty_pos)
                    prof = (price - buy_p) * qty_pos
                    del active_positions[symbol]
                    await send_tg_async(f"💰 *PROFIT:* {symbol}\nGain: `+{prof:.4f} USDT`")

            await asyncio.sleep(4) # 4s delay to prevent rate limits with 100 coins
        except Exception:
            await asyncio.sleep(5)

async def main():
    client = await AsyncClient.create(API_KEY, API_SECRET, testnet=True)
    symbols = await get_top_100_symbols(client)
    
    await send_tg_async(f"🚀 *CENTURION MODE ACTIVE*\nPairs: `{len(symbols)}` | Target: `0.2% Scalps` | Risk: `Aggressive`")
    
    # Launch monitoring for all 100 pairs
    tasks = [trade_logic(client, s) for s in symbols]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())

