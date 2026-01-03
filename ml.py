import asyncio, aiohttp, numpy as np, pandas as pd, math
from binance import AsyncClient
from binance.enums import *

# --- CREDENTIALS ---
API_KEY = 'Et7oRtg2CLHyaRGBoQOoTFt7LSixfav28k0bnVfcgzxd2KTal4xPlxZ9aO6sr1EJ'
API_SECRET = '2LfotApekUjBH6jScuzj1c47eEnq1ViXsNRIP4ydYqYWl6brLhU3JY4vqlftnUIo'
TG_TOKEN = '8560134874:AAHF4efOAdsg2Y01eBHF-2DzEUNf9WAdniA'
TG_CHAT_ID = '5665906172'

# Global filter cache to prevent constant API calls
symbol_filters = {}
active_positions = {}

async def send_tg_async(msg):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    params = {'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp: return await resp.json()
    except: pass

async def setup_filters(client):
    """Fetches trading rules for all coins to avoid 'Filter Failure' errors"""
    info = await client.get_exchange_info()
    for s in info['symbols']:
        f = {filt['filterType']: filt for filt in s['filters']}
        symbol_filters[s['symbol']] = {
            'step': float(f['LOT_SIZE']['stepSize']),
            'minQty': float(f['LOT_SIZE']['minQty']),
            'minNotional': float(f.get('MIN_NOTIONAL', f.get('NOTIONAL', {'minNotional': 5}))['minNotional'])
        }
    return [s['symbol'] for s in info['symbols'] if s['status'] == 'TRADING' and s['symbol'].endswith('USDT')][:100]

def format_quantity(symbol, quantity):
    """Adjusts the amount to match Binance's strict decimal rules"""
    filt = symbol_filters[symbol]
    step = filt['step']
    precision = int(round(-math.log(step, 10), 0))
    # Round down to ensure we don't exceed balance
    qty = math.floor(quantity / step) * step
    return round(qty, precision)

async def get_elite_signals(client, symbol):
    # Reduced limit to 20 for extreme speed
    klines = await client.get_klines(symbol=symbol, interval='1m', limit=20)
    df = pd.DataFrame(klines, columns=['t','o','h','l','c','v','ct','qav','nt','tbv','tqv','i']).astype(float)
    
    # Volume Delta + OBI
    df['delta'] = df['tbv'] - (df['v'] - df['tbv'])
    avg_delta = df['delta'].mean()
    
    depth = await client.get_order_book(symbol=symbol, limit=10)
    bid_v = sum([float(b[1]) for b in depth['bids']])
    ask_v = sum([float(a[1]) for a in depth['asks']])
    obi = (bid_v - ask_v) / (bid_v + ask_v)
    
    # Statistical Mean Reversion
    tp = (df['h'] + df['l'] + df['c']) / 3
    vwap = (tp * df['v']).sum() / (df['v'].sum() + 0.0001)
    z_score = (df['c'].iloc[-1] - df['c'].mean()) / (df['c'].std() + 0.00001)
    
    return z_score, obi, vwap, df['delta'].iloc[-1], avg_delta, df['c'].iloc[-1]

async def trade_logic(client, symbol):
    usd_per_trade = 5.5 # Slightly above $5 minimum for safety
    max_slots = 18 

    while True:
        try:
            z, obi, vwap, delta, avg_delta, price = await get_elite_signals(client, symbol)
            
            # --- THE "ACTION" ENGINE ---
            if symbol not in active_positions and len(active_positions) < max_slots:
                # Optimized for high frequency: Z < -1.5, OBI > 0.1
                if z < -1.5 and obi > 0.1 and delta > 0:
                    qty = format_quantity(symbol, usd_per_trade / price)
                    
                    # Ensure it meets min notional ($5+)
                    if (qty * price) > symbol_filters[symbol]['minNotional']:
                        await client.create_order(symbol=symbol, side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=qty)
                        active_positions[symbol] = {'p': price, 'q': qty}
                        await send_tg_async(f"🚀 *ELITE ENTRY:* {symbol}\nPrice: `{price}` | Z: `{z:.2f}`")

            # --- THE SCALP EXIT ---
            elif symbol in active_positions:
                buy_p = active_positions[symbol]['p']
                qty_pos = active_positions[symbol]['q']
                
                # Exit at 0.2% Profit or Overbought Z-Score
                if z > 1.3 or price > (buy_p * 1.002):
                    await client.create_order(symbol=symbol, side=SIDE_SELL, type=ORDER_TYPE_MARKET, quantity=qty_pos)
                    prof = (price - buy_p) * qty_pos
                    del active_positions[symbol]
                    await send_tg_async(f"💰 *SCALP PROFIT:* {symbol}\nGain: `+{prof:.4f} USDT`")

            await asyncio.sleep(3) # Safe scan for 100 symbols
        except Exception:
            await asyncio.sleep(5)

async def monitor_portfolio(client):
    """Sends a Live P&L and Balance summary every 60s"""
    while True:
        try:
            acc = await client.get_account()
            bal = next((i['free'] for i in acc['balances'] if i['asset'] == 'USDT'), 0)
            pnl = 0
            for s, d in active_positions.items():
                t = await client.get_symbol_ticker(symbol=s)
                pnl += (float(t['price']) - d['p']) * d['q']
            
            await send_tg_async(f"📊 *STATUS UPDATE*\nUSDT: `{float(bal):.2f}`\nPositions: `{len(active_positions)}` | Float: `{pnl:.4f}`")
            await asyncio.sleep(60)
        except: await asyncio.sleep(10)

async def main():
    client = await AsyncClient.create(API_KEY, API_SECRET, testnet=True)
    symbols = await setup_filters(client)
    
    await send_tg_async(f"⚡️ *CENTURION DEPLOYED*\nScanning `{len(symbols)}` Symbols\nBudget: `$100` | Logic: `Elite HFT`")
    
    tasks = [trade_logic(client, s) for s in symbols] + [monitor_portfolio(client)]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())


