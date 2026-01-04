
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
active_positions = {} # Stores {'symbol': {'p': buy_price, 'q': qty, 't': time}}

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
        f = {filt['filterType']: filt for filt in s['filters']}
        symbol_filters[s['symbol']] = {
            'step': float(f['LOT_SIZE']['stepSize']),
            'minNotional': float(f.get('MIN_NOTIONAL', f.get('NOTIONAL', {'minNotional': 5}))['minNotional'])
        }
    # Return top 100 USDT pairs by volume/status
    return [s['symbol'] for s in info['symbols'] if s['status'] == 'TRADING' and s['symbol'].endswith('USDT')][:100]

def format_quantity(symbol, quantity):
    step = symbol_filters[symbol]['step']
    precision = int(round(-math.log(step, 10), 0))
    qty = math.floor(quantity / step) * step
    return round(qty, precision)

async def get_elite_signals(client, symbol):
    # Reduced limit to 20 for faster HFT polling
    klines = await client.get_klines(symbol=symbol, interval='1m', limit=20)
    df = pd.DataFrame(klines, columns=['t','o','h','l','c','v','ct','qav','nt','tbv','tqv','i']).astype(float)
    df['delta'] = df['tbv'] - (df['v'] - df['tbv'])
    
    depth = await client.get_order_book(symbol=symbol, limit=10)
    bid_v = sum([float(b[1]) for b in depth['bids']])
    ask_v = sum([float(a[1]) for a in depth['asks']])
    obi = (bid_v - ask_v) / (bid_v + ask_v)
    
    z_score = (df['c'].iloc[-1] - df['c'].mean()) / (df['c'].std() + 0.00001)
    return z_score, obi, df['delta'].iloc[-1], df['c'].iloc[-1]

async def portfolio_heartbeat(client):
    """Broadcasts Balance and Floating P&L every minute"""
    while True:
        try:
            acc = await client.get_account()
            usdt_free = float(next(i['free'] for i in acc['balances'] if i['asset'] == 'USDT'))
            
            # Calculate Floating P&L
            total_float_pnl = 0
            for sym, data in active_positions.items():
                ticker = await client.get_symbol_ticker(symbol=sym)
                current_p = float(ticker['price'])
                total_float_pnl += (current_p - data['p']) * data['q']
            
            status = (
                f"🛰 *STATUS UPDATE*\n"
                f"💰 USDT Balance: `{usdt_free:.2f}`\n"
                f"📦 Active Trades: `{len(active_positions)}` / 15\n"
                f"📉 Floating P&L: `{total_float_pnl:+.4f} USDT`"
            )
            await send_tg_async(status)
            await asyncio.sleep(60)
        except Exception as e:
            await asyncio.sleep(10)

async def trade_logic(client, symbol):
    # Configuration
    total_slots = 15 # Max simultaneous trades
    
    while True:
        try:
            z, obi, delta, price = await get_elite_signals(client, symbol)
            
            # ENTRY: Same Logic, but scanning 100 pairs with Slot check
            if symbol not in active_positions and len(active_positions) < total_slots:
                # ENTRY Logic: Z < -1.5 (Dip) + OBI > 0.1 (Support) + Delta > 0 (Aggressive Buy)
                if z < -1.5 and obi > 0.1 and delta > 0:
                    acc = await client.get_account()
                    usdt_free = float(next(i['free'] for i in acc['balances'] if i['asset'] == 'USDT'))
                    
                    # Snowball calculation: Reinvests balance into open slots
                    usd_per_slot = (usdt_free / (total_slots - len(active_positions))) * 0.9
                    
                    if usd_per_slot > symbol_filters[symbol]['minNotional']:
                        qty = format_quantity(symbol, usd_per_slot / price)
                        await client.create_order(symbol=symbol, side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=qty)
                        active_positions[symbol] = {'p': price, 'q': qty}
                        await send_tg_async(f"🚀 *COMPOUND ENTRY:* {symbol}\nPrice: `{price}` | Z: `{z:.2f}`")

            # EXIT: 0.2% Scalp Target or Overbought reversal
            elif symbol in active_positions:
                buy_p = active_positions[symbol]['p']
                qty_pos = active_positions[symbol]['q']
                
                if price > (buy_p * 1.002) or z > 1.3:
                    await client.create_order(symbol=symbol, side=SIDE_SELL, type=ORDER_TYPE_MARKET, quantity=qty_pos)
                    profit = (price - buy_p) * qty_pos
                    del active_positions[symbol]
                    await send_tg_async(f"💎 *PROFIT HARVEST:* {symbol}\nResult: `+{profit:.4f} USDT`")

            await asyncio.sleep(2) # HFT Polling speed
        except Exception: await asyncio.sleep(5)

async def main():
    client = await AsyncClient.create(API_KEY, API_SECRET, testnet=True)
    symbols = await setup_filters(client)
    
    await send_tg_async(f"❄️ *SNOWBALL MODE DEPLOYED*\nPairs: `{len(symbols)}` | Target: `0.2%` | Slots: `15`")
    
    # Run Portfolio Monitor + 100 Trading Tasks
    tasks = [trade_logic(client, s) for s in symbols]
    tasks.append(portfolio_heartbeat(client))
    
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
