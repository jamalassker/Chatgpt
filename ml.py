import asyncio, aiohttp, numpy as np, pandas as pd, math
from binance import AsyncClient
from binance.enums import *

# --- CREDENTIALS ---
API_KEY = 'Et7oRtg2CLHyaRGBoQOoTFt7LSixfav28k0bnVfcgzxd2KTal4xPlxZ9aO6sr1EJ'
API_SECRET = '2LfotApekUjBH6jScuzj1c47eEnq1ViXsNRIP4ydYqYWl6brLhU3JY4vqlftnUIo'
TG_TOKEN = '8560134874:AAHF4efOAdsg2Y01eBHF-2DzEUNf9WAdniA'
TG_CHAT_ID = '5665906172'

# Global state
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
    info = await client.get_exchange_info()
    for s in info['symbols']:
        if not s['symbol'].endswith('USDT'): continue
        f = {filt['filterType']: filt for filt in s['filters']}
        symbol_filters[s['symbol']] = {
            'step': float(f['LOT_SIZE']['stepSize']),
            'minNotional': float(f.get('MIN_NOTIONAL', f.get('NOTIONAL', {'minNotional': 5}))['minNotional'])
        }
    return [s['symbol'] for s in info['symbols'] if s['status'] == 'TRADING' and s['symbol'].endswith('USDT')][:100]

def format_quantity(symbol, quantity):
    step = symbol_filters[symbol]['step']
    precision = int(round(-math.log(step, 10), 0))
    qty = math.floor(quantity / step) * step
    return round(qty, precision)

async def get_elite_signals(client, symbol):
    # Fast polling: only 15 candles for speed
    klines = await client.get_klines(symbol=symbol, interval='1m', limit=15)
    df = pd.DataFrame(klines, columns=['t','o','h','l','c','v','ct','qav','nt','tbv','tqv','i']).astype(float)
    df['delta'] = df['tbv'] - (df['v'] - df['tbv'])
    
    depth = await client.get_order_book(symbol=symbol, limit=5)
    bid_v = sum([float(b[1]) for b in depth['bids']])
    ask_v = sum([float(a[1]) for a in depth['asks']])
    obi = (bid_v - ask_v) / (bid_v + ask_v)
    
    z_score = (df['c'].iloc[-1] - df['c'].mean()) / (df['c'].std() + 0.00001)
    return z_score, obi, df['delta'].iloc[-1], df['c'].iloc[-1]

async def portfolio_heartbeat(client):
    """HYPER-ACTIVE: Reports every 3 seconds"""
    while True:
        try:
            acc = await client.get_account()
            usdt_free = float(next(i['free'] for i in acc['balances'] if i['asset'] == 'USDT'))
            
            total_float_pnl = 0
            # Faster P&L calculation using tickers
            if active_positions:
                tickers = await client.get_all_tickers()
                prices = {t['symbol']: float(t['price']) for t in tickers}
                for sym, data in active_positions.items():
                    if sym in prices:
                        total_float_pnl += (prices[sym] - data['p']) * data['q']
            
            status = (
                f"🛰 *LIVE HEARTBEAT*\n"
                f"💰 Balance: `{usdt_free:.2f} USDT`\n"
                f"📦 Active: `{len(active_positions)}/25` | Float: `{total_float_pnl:+.4f}`"
            )
            await send_tg_async(status)
            await asyncio.sleep(3) # 3-second reporting
        except: await asyncio.sleep(3)

async def trade_logic(client, symbol):
    total_slots = 25 # Increased for high-frequency activity
    
    while True:
        try:
            z, obi, delta, price = await get_elite_signals(client, symbol)
            
            # AGGRESSIVE ENTRY: Lowered thresholds for more trades
            if symbol not in active_positions and len(active_positions) < total_slots:
                if z < -1.2 and obi > 0.05 and delta > -5: # Very sensitive settings
                    acc = await client.get_account()
                    balance = float(next(i['free'] for i in acc['balances'] if i['asset'] == 'USDT'))
                    
                    # Allocate all available funds divided by remaining slots
                    usd_per_slot = (balance / (total_slots - len(active_positions))) * 0.98
                    
                    if usd_per_slot > symbol_filters[symbol]['minNotional']:
                        qty = format_quantity(symbol, usd_per_slot / price)
                        await client.create_order(symbol=symbol, side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=qty)
                        active_positions[symbol] = {'p': price, 'q': qty}
                        await send_tg_async(f"🚀 *UNLEASHED ENTRY:* {symbol}\nSize: `${usd_per_slot:.2f}`")

            # EXIT: 0.2% Scalp or Trend Reversal
            elif symbol in active_positions:
                buy_p = active_positions[symbol]['p']
                qty_pos = active_positions[symbol]['q']
                
                if price > (buy_p * 1.002) or z > 1.1:
                    await client.create_order(symbol=symbol, side=SIDE_SELL, type=ORDER_TYPE_MARKET, quantity=qty_pos)
                    prof = (price - buy_p) * qty_pos
                    del active_positions[symbol]
                    await send_tg_async(f"💎 *HARVEST:* {symbol} | `+{prof:.4f}`")

            await asyncio.sleep(1) # HFT speed
        except Exception: await asyncio.sleep(2)

async def main():
    client = await AsyncClient.create(API_KEY, API_SECRET, testnet=True)
    symbols = await setup_filters(client)
    await send_tg_async(f"🌑 *CENTURION UNLEASHED*\nMonitoring {len(symbols)} pairs | 3s Reporting")
    tasks = [trade_logic(client, s) for s in symbols] + [portfolio_heartbeat(client)]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())

