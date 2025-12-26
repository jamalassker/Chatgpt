import asyncio, json, aiohttp, logging, time
import numpy as np
import pandas as pd
import ta
from collections import deque
from datetime import datetime
import xgboost as xgb

# ================= CONFIG (STRICTLY PRESERVED) =================
BINANCE_API_KEY = "r6hhHQubpwwnDYkYhhdSlk3MQPjTomUggf59gfXJ21hnBcfq3K4BIoSd1eE91V3N"
BINANCE_SECRET = "B7ioAXzVHyYlxPOz3AtxzMC6FQBZaRj6i8A9FenSbsK8rBeCdGZHDhX6Dti22F2x"
TELEGRAM_TOKEN = "8560134874:AAHF4efOAdsg2Y01eBHF-2DzEUNf9WAdniA"
TELEGRAM_CHAT_ID = "5665906172"

# TOP 20 SYMBOLS
SYMBOLS = [
    "btcusdt", "ethusdt", "solusdt", "bnbusdt", "xrpusdt", 
    "adausdt", "avaxusdt", "dogeusdt", "dotusdt", "linkusdt",
    "polusdt", "nearusdt", "ltcusdt", "uniusdt", "aptusdt",
    "arbusdt", "opusdt", "injusdt", "tiausdt", "suiusdt"
]

BASE_USD = 25
TP, SL = 0.0045, 0.0030
# Combined stream URL for multiple symbols
STREAMS = "/".join([f"{s}@aggTrade" for s in SYMBOLS])
WS_URL = f"wss://stream.binance.com:9443/stream?streams={STREAMS}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("Alpha-HFT")

# ================= THE AI BRAIN (PRESERVED) =================
class MLFilter:
    def predict(self, rsi, z_score, ofi, trend):
        score = 0
        if rsi < 32: score += 30
        if z_score < -1.8: score += 30
        if ofi > 0.05: score += 20
        if trend > 0: score += 20
        return score

# ================= MULTI-SYMBOL HFT ENGINE =================
class AlphaHFT:
    def __init__(self):
        # Per-symbol state tracking
        self.state = {s: {
            "price_history": deque(maxlen=200),
            "trade_flow": deque(maxlen=100),
            "position": None,
            "kalman_x": 0.0,
            "kalman_p": 1.0,
            "current_price": 0.0
        } for s in SYMBOLS}
        
        self.closed_trades = []
        self.tg_id = None
        self.ai = MLFilter()

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
                total_pnl = sum(self.closed_trades)
                active_pos = [s for s, data in self.state.items() if data["position"]]
                
                msg = (
                    f"<b>🤖 AI HFT TOP 20 ACTIVE</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Active Positions:</b> {len(active_pos)}\n"
                    f"<b>Banked PnL:</b> ${total_pnl:+.2f}\n"
                    f"<b>Win Rate:</b> {self.get_winrate()}%\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Last Symbol:</b> {active_pos[-1].upper() if active_pos else 'None'}\n"
                    f"<b>Updated:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"
                )
                
                if not self.tg_id:
                    async with session.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                                            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}) as r:
                        res = await r.json()
                        self.tg_id = res["result"]["message_id"]
                else:
                    await session.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText", 
                                       json={"chat_id": TELEGRAM_CHAT_ID, "message_id": self.tg_id, "text": msg, "parse_mode": "HTML"})
            except: pass
            await asyncio.sleep(3)

    def get_winrate(self):
        if not self.closed_trades: return 0
        wins = len([t for t in self.closed_trades if t > 0])
        return round((wins / len(self.closed_trades)) * 100, 1)

    async def run(self):
        async with aiohttp.ClientSession() as session:
            asyncio.create_task(self.telegram_dashboard(session))
            async with session.ws_connect(WS_URL) as ws:
                log.info("Top 20 AggTrade Stream Connected")
                async for msg in ws:
                    raw_data = json.loads(msg.data)
                    stream_name = raw_data['stream'].split('@')[0]
                    data = raw_data['data']
                    
                    s = self.state[stream_name]
                    s["current_price"] = float(data['p'])
                    s["price_history"].append(s["current_price"])
                    
                    flow = float(data['q']) if not data['m'] else -float(data['q'])
                    s["trade_flow"].append(flow)

                    if len(s["price_history"]) < 50: continue

                    # AI Features
                    rsi = ta.momentum.rsi(pd.Series(list(s["price_history"])), window=14).iloc[-1]
                    z_score = (s["current_price"] - np.mean(s["price_history"])) / (np.std(s["price_history"]) + 1e-10)
                    ofi = sum(s["trade_flow"])
                    trend = self.kalman_filter(stream_name, s["current_price"])

                    # Trade Logic
                    if not s["position"]:
                        if self.ai.predict(rsi, z_score, ofi, trend) >= 80:
                            s["position"] = {"entry": s["current_price"], "amount": BASE_USD / s["current_price"]}
                            log.info(f"AI BUY: {stream_name.upper()} at {s['current_price']}")

                    elif s["position"]:
                        pnl = (s["current_price"] - s["position"]["entry"]) / s["position"]["entry"]
                        if pnl >= TP or pnl <= -SL:
                            self.closed_trades.append((s["current_price"] - s["position"]["entry"]) * s["position"]["amount"])
                            log.info(f"EXIT {stream_name.upper()} | PnL: {pnl:.4f}")
                            s["position"] = None

if __name__ == "__main__":
    bot = AlphaHFT()
    asyncio.run(bot.run())
