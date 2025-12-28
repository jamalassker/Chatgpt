import asyncio, json, aiohttp, logging, time
import numpy as np
import pandas as pd
import ta
import ccxt.async_support as ccxt
from collections import deque
from datetime import datetime

# ================= CONFIG (STRICTLY PRESERVED) =================
BYBIT_API_KEY = "UYr9b62FtiRiN9hHue"
BYBIT_SECRET = "rUDdj0QM2lQJQjVY1EeoUuPw29LldrNLtzKI"
TELEGRAM_TOKEN = "8560134874:AAHF4efOAdsg2Y01eBHF-2DzEUNf9WAdniA"
TELEGRAM_CHAT_ID = "5665906172"

# PRESERVED TOP 20 SYMBOLS
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT",
    "POLUSDT", "NEARUSDT", "LTCUSDT", "UNIUSDT", "APTUSDT",
    "ARBUSDT", "OPUSDT", "INJUSDT", "TIAUSDT", "SUIUSDT"
]

BASE_USD = 25
TP, SL = 0.0045, 0.0030
WS_URL = "wss://stream-testnet.bybit.com/v5/public/spot"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("Alpha-HFT")

# ================= THE AI BRAIN (STRICTLY PRESERVED) =================
class MLFilter:
    def predict(self, rsi, z_score, ofi, trend):
        score = 0
        if rsi < 32: score += 30
        if z_score < -1.8: score += 30
        if ofi > 0.05: score += 20
        if trend > 0: score += 20
        return score

# ================= MAIN ENGINE (BYBIT V5 ADAPTED) =================
class AlphaHFT:
    def __init__(self):
        # 1. CCXT CONFIG FOR BYBIT TESTNET V5
        self.exchange = ccxt.bybit({
            'apiKey': BYBIT_API_KEY,
            'secret': BYBIT_SECRET,
            'enableRateLimit': True,
            'options': {
                'accountType': 'UNIFIED', # Essential for new Bybit accounts
                'defaultType': 'spot',
            }
        })
        # Override URLs for Testnet specifically
        self.exchange.urls['api'] = {
            'public': 'https://api-testnet.bybit.com',
            'private': 'https://api-testnet.bybit.com',
        }

        # 2. STATE INITIALIZATION
        self.state = {
            s: {
                "price_history": deque(maxlen=100),
                "trade_flow": deque(maxlen=50),
                "position": None,
                "kalman_x": 0.0,
                "kalman_p": 1.0,
                "current_price": 0.0
            } for s in SYMBOLS
        }
        
        self.closed_trades = []
        self.tg_id = None
        self.ai = MLFilter()

    async def verify_balance(self):
        try:
            bal = await self.exchange.fetch_balance()
            usdt = bal['total'].get('USDT', 0)
            log.info(f"✅ DEMO OK | USDT: {usdt}")
            return usdt
        except Exception as e:
            log.error(f"❌ AUTH FAILED: {e}")
            return 0

    def kalman_filter(self, symbol, z):
        s = self.state[symbol]
        s["kalman_p"] += 0.0001
        k = s["kalman_p"] / (s["kalman_p"] + 0.01)
        s["kalman_x"] += k * (z - s["kalman_x"])
        s["kalman_p"] *= (1 - k)
        return s["kalman_x"]

    async def telegram_dashboard(self, session):
        while True:
            try:
                total_banked = sum(self.closed_trades)
                active_list = [s for s, d in self.state.items() if d["position"]]
                total_floating = sum([(d["current_price"] - d["position"]["entry"]) * d["position"]["amount"] 
                                     for d in self.state.values() if d["position"]])
                
                msg = (f"<b>🤖 AI HFT TOP 20 (BYBIT DEMO)</b>\n"
                       f"━━━━━━━━━━━━━━━━━━━━\n"
                       f"<b>Active Trades:</b> {len(active_list)}\n"
                       f"<b>Floating P&L:</b> ${total_floating:+.4f}\n"
                       f"<b>Banked PnL:</b> ${total_banked:+.2f}\n"
                       f"━━━━━━━━━━━━━━━━━━━━\n"
                       f"<b>Last Update:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC")
                
                if not self.tg_id:
                    async with session.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}) as r:
                        res = await r.json()
                        self.tg_id = res["result"]["message_id"]
                else:
                    await session.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText", 
                        json={"chat_id": TELEGRAM_CHAT_ID, "message_id": self.tg_id, "text": msg, "parse_mode": "HTML"})
            except: pass
            await asyncio.sleep(5)

    async def run(self):
        await self.verify_balance()

        async with aiohttp.ClientSession() as session:
            asyncio.create_task(self.telegram_dashboard(session))
            
            async with session.ws_connect(WS_URL) as ws:
                # SUBSCRIBE TO ALL 20 SYMBOLS
                await ws.send_json({
                    "op": "subscribe",
                    "args": [f"publicTrade.{s}" for s in SYMBOLS]
                })
                log.info(f"🚀 Monitoring {len(SYMBOLS)} Assets via Bybit Testnet")

                async for msg in ws:
                    raw = json.loads(msg.data)
                    if "data" not in raw: continue

                    for t in raw["data"]:
                        symbol = t['s'] # e.g., "BTCUSDT"
                        if symbol not in self.state: continue

                        price = float(t["p"])
                        s = self.state[symbol]
                        s["current_price"] = price
                        s["price_history"].append(price)
                        s["trade_flow"].append(float(t["v"]) if t["S"] == "Buy" else -float(t["v"]))

                        if len(s["price_history"]) < 30: continue

                        # CALCULATE INDICATORS
                        prices_series = pd.Series(list(s["price_history"]))
                        rsi = ta.momentum.rsi(prices_series, 14).iloc[-1]
                        z = (price - np.mean(s["price_history"])) / (np.std(s["price_history"]) + 1e-9)
                        trend = self.kalman_filter(symbol, price)
                        ofi = sum(s["trade_flow"])

                        # SYMBOL FORMATTING FOR CCXT
                        symbol_ccxt = f"{symbol[:-4]}/USDT" 

                        # TRADE EXECUTION
                        if not s["position"] and self.ai.predict(rsi, z, ofi, trend) >= 80:
                            qty = BASE_USD / price
                            try:
                                await self.exchange.create_order(
                                    symbol_ccxt, 'market', 'buy', qty,
                                    params={'category': 'spot'}
                                )
                                s["position"] = {"entry": price, "amount": qty}
                                log.info(f"✅ BUY {symbol_ccxt} at {price}")
                            except Exception as e:
                                log.error(f"❌ Buy Failed: {e}")

                        elif s["position"]:
                            pnl_pct = (price - s["position"]["entry"]) / s["position"]["entry"]
                            if pnl_pct >= TP or pnl_pct <= -SL:
                                try:
                                    await self.exchange.create_order(
                                        symbol_ccxt, 'market', 'sell', s["position"]["amount"],
                                        params={'category': 'spot'}
                                    )
                                    self.closed_trades.append((price - s["position"]["entry"]) * s["position"]["amount"])
                                    s["position"] = None
                                    log.info(f"💰 SELL {symbol_ccxt} | PnL: {pnl_pct:.4f}")
                                except Exception as e:
                                    log.error(f"❌ Sell Failed: {e}")

if __name__ == "__main__":
    asyncio.run(AlphaHFT().run())

