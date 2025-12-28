
import asyncio, json, aiohttp, logging
import numpy as np
import pandas as pd
import ta
from collections import deque
from telegram import Bot

# ================= CONFIG =================
TELEGRAM_TOKEN = "8560134874:AAHF4efOAdsg2Y01eBHF-2DzEUNf9WAdniA"
TELEGRAM_CHAT_ID = "5665906172"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT",
    "TRXUSDT", "MATICUSDT", "SHIBUSDT", "TONUSDT", "LTCUSDT",
    "DAIUSDT", "BCHUSDT", "NEARUSDT", "LEOUSDT", "UNIUSDT"
]

BASE_USD = 20
WS_URL = "wss://stream.binance.com:9443/stream"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("Alpha-HFT-PAPER")


class AlphaHFTPaper:
    def __init__(self):
        self.tg_bot = Bot(token=TELEGRAM_TOKEN)

        self.state = {
            s: {
                "price_history": deque(maxlen=50),
                "trade_flow": deque(maxlen=20),
                "position": None,
                "trades": 0,
                "pnl": 0.0
            } for s in SYMBOLS
        }

    async def notify(self, message):
        try:
            await self.tg_bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"🤖 *Alpha HFT PAPER*\n{message}",
                parse_mode="Markdown"
            )
        except Exception as e:
            log.error(f"Telegram Error: {e}")

    async def run(self):
        log.info("✅ Paper Trading Engine Online")

        async with aiohttp.ClientSession() as session:
            streams = "/".join([f"{s.lower()}@trade" for s in SYMBOLS])
            ws_url = f"{WS_URL}?streams={streams}"

            async with session.ws_connect(ws_url) as ws:
                async for msg in ws:
                    raw = json.loads(msg.data)
                    data = raw.get("data")
                    if not data:
                        continue

                    symbol = data.get("s")
                    if symbol not in self.state:
                        continue

                    price = float(data["p"])
                    vol = float(data["q"])

                    s = self.state[symbol]
                    s["price_history"].append(price)
                    s["trade_flow"].append(-vol if data["m"] else vol)

                    if len(s["price_history"]) < 10:
                        continue

                    # ===== STRATEGY LOGIC (UNCHANGED) =====
                    prices = pd.Series(s["price_history"])
                    rsi = ta.momentum.rsi(prices, window=min(len(prices), 14)).iloc[-1]

                    z_score = (
                        (price - np.mean(s["price_history"])) /
                        (np.std(s["price_history"]) + 1e-9)
                    )

                    score = 0
                    if rsi < 45:
                        score += 40
                    if z_score < -1.5:
                        score += 40
                    if sum(s["trade_flow"]) > 0:
                        score += 20

                    # ========== BUY (PAPER) ==========
                    if not s["position"] and score >= 80:
                        qty = BASE_USD / price
                        s["position"] = {
                            "entry": price,
                            "amount": qty
                        }

                        log.info(f"[PAPER BUY] {symbol} @ {price}")
                        await self.notify(
                            f"🟢 BUY {symbol}\n"
                            f"Price: {price}\nScore: {score}"
                        )

                    # ========== SELL (PAPER) ==========
                    elif s["position"]:
                        pnl = (
                            (price - s["position"]["entry"]) /
                            s["position"]["entry"]
                        )

                        if pnl >= 0.006 or pnl <= -0.003:
                            trade_pnl = pnl * BASE_USD
                            s["pnl"] += trade_pnl
                            s["trades"] += 1

                            result = "PROFIT 💰" if pnl > 0 else "LOSS 📉"

                            log.info(
                                f"[PAPER SELL] {symbol} | {result} | PnL {pnl:+.2%}"
                            )

                            await self.notify(
                                f"🔴 SELL {symbol}\n"
                                f"Result: {result}\n"
                                f"PnL: {pnl:+.2%}\n"
                                f"Total PnL: {s['pnl']:.2f}$\n"
                                f"Trades: {s['trades']}"
                            )

                            s["position"] = None


if __name__ == "__main__":
    try:
        asyncio.run(AlphaHFTPaper().run())
    except KeyboardInterrupt:
        log.info("Paper bot stopped")
