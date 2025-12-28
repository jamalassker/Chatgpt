import asyncio, json, aiohttp, logging
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

SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
    "ADAUSDT","AVAXUSDT","DOGEUSDT","DOTUSDT","LINKUSDT",
    "POLUSDT","NEARUSDT","LTCUSDT","UNIUSDT","APTUSDT",
    "ARBUSDT","OPUSDT","INJUSDT","TIAUSDT","SUIUSDT"
]

BASE_USD = 25
TP, SL = 0.0055, 0.0035 # Adjusted slightly for fee headroom
WS_URL = "wss://stream-testnet.bybit.com/v5/public/spot"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("Alpha-HFT")

# ================= ENHANCED AI BRAIN =================
class MLFilter:
    def predict(self, rsi, z_score, ofi, trend, volatility_squeeze):
        score = 0
        # 1. Momentum Check
        if rsi < 35: score += 25
        # 2. Mean Reversion / Breakout Check
        if z_score < -1.5: score += 25
        # 3. Order Flow (Sensitive to smaller shifts)
        if ofi > 0: score += 20
        # 4. Trend Confirmation
        if trend > 0: score += 15
        # 5. Volatility Squeeze (High probability entry)
        if volatility_squeeze: score += 15
        
        return score

# ================= ENGINE =================
class AlphaHFT:
    def __init__(self):
        self.exchange = ccxt.bybit({
            "apiKey": BYBIT_API_KEY,
            "secret": BYBIT_SECRET,
            "enableRateLimit": True,
            "options": {"defaultType": "spot", "accountType": "UNIFIED"}
        })

        self.exchange.urls["api"] = {
            "public": "https://api-testnet.bybit.com",
            "private": "https://api-testnet.bybit.com",
        }

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
            usdt = bal["total"].get("USDT", 0)
            log.info(f"✅ DEMO OK | USDT: {usdt}")
        except Exception as e:
            log.error(f"Balance Check Error: {e}")

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
                active_trades = [d for d in self.state.values() if d["position"]]
                total_floating = sum((d["current_price"] - d["position"]["entry"]) * d["position"]["amount"] for d in active_trades)

                msg = (
                    f"<b>🤖 ALPHA AI HFT (BYBIT)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Active:</b> {len(active_trades)} | <b>Banked:</b> ${total_banked:+.2f}\n"
                    f"<b>Floating:</b> ${total_floating:+.4f}\n"
                    f"<b>Win Rate:</b> {self.get_win_rate()}%\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏱ {datetime.utcnow().strftime('%H:%M:%S')} UTC"
                )

                if not self.tg_id:
                    r = await session.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"})
                    res = await r.json()
                    if res.get("ok"): self.tg_id = res["result"]["message_id"]
                else:
                    await session.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText", json={"chat_id": TELEGRAM_CHAT_ID, "message_id": self.tg_id, "text": msg, "parse_mode": "HTML"})
            except: pass
            await asyncio.sleep(10)

    def get_win_rate(self):
        if not self.closed_trades: return 0
        wins = [t for t in self.closed_trades if t > 0]
        return round((len(wins) / len(self.closed_trades)) * 100, 1)

    async def ws_loop(self, session):
        while True:
            try:
                async with session.ws_connect(WS_URL, heartbeat=20) as ws:
                    await ws.send_json({"op": "subscribe", "args": [f"publicTrade.{s}" for s in SYMBOLS]})
                    log.info("🚀 AI-HFT WebSocket Online")

                    async for msg in ws:
                        raw = json.loads(msg.data)
                        if "data" not in raw: continue

                        for t in raw["data"]:
                            symbol = t["s"]
                            price = float(t["p"])
                            s = self.state[symbol]
                            s["current_price"] = price
                            s["price_history"].append(price)
                            s["trade_flow"].append(float(t["v"]) if t["S"] == "Buy" else -float(t["v"]))

                            if len(s["price_history"]) < 30: continue

                            # --- AI FEATURE ENGINEERING ---
                            prices = pd.Series(s["price_history"])
                            rsi = ta.momentum.rsi(prices, 14).iloc[-1]
                            std = np.std(s["price_history"])
                            z = (price - np.mean(s["price_history"])) / (std + 1e-9)
                            trend = self.kalman_filter(symbol, price)
                            ofi = sum(s["trade_flow"])
                            
                            # Bollinger Band Squeeze (AI enhancement)
                            upper_bb = ta.volatility.bollinger_hband(prices, 20, 2).iloc[-1]
                            lower_bb = ta.volatility.bollinger_lband(prices, 20, 2).iloc[-1]
                            squeeze = (upper_bb - lower_bb) / price < 0.002 # 0.2% squeeze

                            symbol_ccxt = f"{symbol[:-4]}/USDT"

                            # --- EXECUTION LOGIC ---
                            if not s["position"]:
                                score = self.ai.predict(rsi, z, ofi, trend, squeeze)
                                if score >= 75: # Lowered slightly for HFT frequency
                                    qty = BASE_USD / price
                                    try:
                                        await self.exchange.create_market_buy_order(symbol_ccxt, qty)
                                        s["position"] = {"entry": price, "amount": qty}
                                        log.info(f"🚀 AI BUY {symbol_ccxt} | Score: {score}")
                                    except Exception as e: log.error(f"Buy Error: {e}")

                            elif s["position"]:
                                pnl = (price - s["position"]["entry"]) / s["position"]["entry"]
                                if pnl >= TP or pnl <= -SL:
                                    try:
                                        await self.exchange.create_market_sell_order(symbol_ccxt, s["position"]["amount"])
                                        self.closed_trades.append((price - s["position"]["entry"]) * s["position"]["amount"])
                                        log.info(f"💰 AI SELL {symbol_ccxt} | PnL: {pnl:+.4f}")
                                        s["position"] = None
                                    except Exception as e: log.error(f"Sell Error: {e}")

            except Exception as e:
                log.error(f"WS Sync Lost: {e}")
                await asyncio.sleep(5)

    async def run(self):
        await self.verify_balance()
        async with aiohttp.ClientSession() as session:
            asyncio.create_task(self.telegram_dashboard(session))
            await self.ws_loop(session)

if __name__ == "__main__":
    asyncio.run(AlphaHFT().run())
