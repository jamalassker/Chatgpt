import asyncio, json, aiohttp, logging, numpy as np, pandas as pd, ta
from collections import deque
from river import linear_model, preprocessing, compose, metrics
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk
from telegram import Bot

# Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("Alpha-ML-Pro")
nltk.download('vader_lexicon', quiet=True)

# ================= CONFIG =================
TELEGRAM_TOKEN = "8488789199:AAHhViKmhXlvE7WpgZGVDS4WjCjUuBVtqzQ"
TELEGRAM_CHAT_ID = "5665906172"
CRYPTOPANIC_API_KEY = "936ee60c210fd21b853971b458bfdf6ef2515eb3"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT",
    "TRXUSDT", "MATICUSDT", "SHIBUSDT", "TONUSDT", "LTCUSDT",
    "DAIUSDT", "BCHUSDT", "NEARUSDT", "LEOUSDT", "UNIUSDT"
]
BASE_USD = 10.0  
# ==========================================

class AlphaMLBot:
    def __init__(self):
        self.wallet = 20.0
        self.sia = SentimentIntensityAnalyzer()
        self.current_sentiment = 0.0
        self.tg_bot = Bot(token=TELEGRAM_TOKEN)
        
        # Online Learning Model
        self.model = compose.Pipeline(
            preprocessing.StandardScaler(), 
            linear_model.LogisticRegression()
        )
        
        self.state = {s: {
            "price_history": deque(maxlen=50), 
            "flow": deque(maxlen=20),
            "position": None, 
            "current_price": 0.0
        } for s in SYMBOLS}

    async def send_tg(self, text):
        try:
            await self.tg_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="Markdown")
        except: pass

    def get_features(self, symbol):
        s = self.state[symbol]
        prices = pd.Series(list(s["price_history"]))
        if len(prices) < 15: return None
        
        rsi = ta.momentum.rsi(prices, window=14).iloc[-1] if len(prices) >= 14 else 50
        return {
            "rsi": rsi,
            "zscore": (prices.iloc[-1] - prices.mean()) / (prices.std() + 1e-9),
            "flow": sum(s["flow"]),
            "sentiment": self.current_sentiment
        }

    async def update_sentiment(self):
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {"auth_token": CRYPTOPANIC_API_KEY, "public": "true"}
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            titles = [p['title'] for p in data.get('results', [])[:5]]
                            if titles:
                                self.current_sentiment = np.mean([self.sia.polarity_scores(t)['compound'] for t in titles])
            except: pass
            await asyncio.sleep(300)

    async def run_hft(self):
        log.info("🚀 System Active: Scalping Mode Engaged")
        async with aiohttp.ClientSession() as session:
            streams = "/".join([f"{s.lower()}@trade" for s in SYMBOLS])
            async with session.ws_connect(f"wss://stream.binance.com:9443/stream?streams={streams}") as ws:
                async for msg in ws:
                    raw = json.loads(msg.data).get("data")
                    if not raw: continue
                    
                    symbol, price = raw["s"], float(raw["p"])
                    s = self.state[symbol]
                    s["current_price"] = price
                    s["price_history"].append(price)
                    s["flow"].append(-float(raw["q"]) if raw["m"] else float(raw["q"]))
                    
                    feat = self.get_features(symbol)
                    if not feat: continue
                    
                    # PREDICTION
                    prob_buy = self.model.predict_proba_one(feat).get(True, 0.5)

                    # --- SUCCESS LOGIC: ENTRY ---
                    # Logic: Buy if ML is > 60% OR if ML is new (0.50) but RSI is oversold (<35)
                    is_oversold = feat['rsi'] < 35
                    if not s["position"]:
                        if (prob_buy > 0.60) or (prob_buy == 0.50 and is_oversold):
                            if self.current_sentiment > -0.3:
                                s["position"] = {"entry": price, "qty": BASE_USD/price, "feat": feat}
                                log.info(f"🟢 [BUY] {symbol} @ {price} | RSI: {feat['rsi']:.1f} | Prob: {prob_buy:.2f}")

                    # --- SUCCESS LOGIC: EXIT ---
                    elif s["position"]:
                        pnl = (price - s["position"]["entry"]) / s["position"]["entry"]
                        
                        # SCALPING TARGETS: 0.5% Profit or 0.7% Loss
                        if pnl >= 0.005 or pnl <= -0.007:
                            success = pnl > 0
                            self.model.learn_one(s["position"]["feat"], success) # Teach the ML!
                            
                            s["position"] = None
                            status = "✅ PROFIT" if success else "❌ LOSS"
                            log.info(f"🏁 [SELL] {symbol} {status} | PnL: {pnl:+.2%}")
                            await self.send_tg(f"🏁 *{status}* | {symbol}\nNet: `{pnl:+.2%}`")

async def main():
    bot = AlphaMLBot()
    await asyncio.gather(bot.update_sentiment(), bot.run_hft())

if __name__ == "__main__":
    asyncio.run(main())



