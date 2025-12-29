import asyncio, json, aiohttp, logging, numpy as np, pandas as pd, ta
from collections import deque
from river import linear_model, preprocessing, compose, metrics
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk
from telegram import Bot

# 1. Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("Alpha-ML-Fast")

# Download sentiment tools
nltk.download('vader_lexicon', quiet=True)

# ================= CONFIG =================
TELEGRAM_TOKEN = "8488789199:AAHhViKmhXlvE7WpgZGVDS4WjCjUuBVtqzQ"
TELEGRAM_CHAT_ID = "5665906172"
CRYPTOPANIC_API_KEY = "936ee60c210fd21b853971b458bfdf6ef2515eb3"

# Top 20 symbols as requested in your preferences
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
        
        # ML Engine
        self.model = compose.Pipeline(
            preprocessing.StandardScaler(), 
            linear_model.LogisticRegression()
        )
        self.metric = metrics.Accuracy()
        
        self.state = {s: {
            "price_history": deque(maxlen=100), 
            "flow": deque(maxlen=30),
            "position": None, 
            "current_price": 0.0
        } for s in SYMBOLS}

    async def send_tg(self, text):
        try:
            await self.tg_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="Markdown")
        except Exception as e:
            log.error(f"TG Error: {e}")

    def get_total_metrics(self):
        floating_pnl = 0.0
        for s, data in self.state.items():
            if data["position"]:
                entry = data["position"]["entry"]
                qty = data["position"]["qty"]
                current = data["current_price"]
                floating_pnl += (current - entry) * qty
        return floating_pnl

    async def update_sentiment(self):
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {"auth_token": CRYPTOPANIC_API_KEY, "public": "true", "kind": "news"}
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json(content_type=None)
                            titles = [post['title'] for post in data.get('results', [])[:10]]
                            if titles:
                                scores = [self.sia.polarity_scores(t)['compound'] for t in titles]
                                self.current_sentiment = np.mean(scores)
                                log.info(f"📰 News Sentiment: {self.current_sentiment:+.2f}")
            except Exception as e:
                log.error(f"News Fetch Error: {e}")
            await asyncio.sleep(600)

    def get_features(self, symbol):
        s = self.state[symbol]
        prices = pd.Series(list(s["price_history"]))
        # REDUCED: Only need 15 points to start trading instead of 30
        if len(prices) < 15: return None
        
        return {
            "rsi": ta.momentum.rsi(prices, window=14).iloc[-1] if len(prices) >= 14 else 50,
            "zscore": (prices.iloc[-1] - prices.mean()) / (prices.std() + 1e-9),
            "volatility": prices.pct_change().std(),
            "flow": sum(s["flow"]),
            "news": self.current_sentiment
        }

    async def run_hft(self):
        log.info("🚀 High-Frequency ML Engine Starting...")
        await self.send_tg("🤖 *Alpha-ML Fast Mode Online*\nTrading 20 symbols. Threshold: 60%.")
        
        async with aiohttp.ClientSession() as session:
            streams = "/".join([f"{s.lower()}@trade" for s in SYMBOLS])
            async with session.ws_connect(f"wss://stream.binance.com:9443/stream?streams={streams}") as ws:
                async for msg in ws:
                    raw = json.loads(msg.data).get("data")
                    if not raw: continue
                    
                    symbol, price = raw["s"], float(raw["p"])
                    vol = float(raw["q"])
                    is_maker = raw["m"]

                    s = self.state[symbol]
                    s["current_price"] = price
                    s["price_history"].append(price)
                    s["flow"].append(-vol if is_maker else vol)
                    
                    features = self.get_features(symbol)
                    if not features: continue
                    
                    # ML Decision Logic
                    prob_buy = self.model.predict_proba_one(features).get(True, 0.5)
                    float_pnl = self.get_total_metrics()

                    # DEBUG LOG: Shows you exactly what the bot is thinking for every coin
                    if np.random.random() < 0.05: # Only log 5% of messages to avoid flooding
                        log.info(f"🔍 {symbol} | Price: {price} | ML Prob: {prob_buy:.2f} | News: {self.current_sentiment:.2f}")

                    # --- AGGRESSIVE BUY LOGIC ---
                    # Lowered confidence to 0.60 (60%) and sentiment floor to -0.4
                    if not s["position"] and prob_buy > 0.60 and self.current_sentiment > -0.4:
                        s["position"] = {"entry": price, "qty": BASE_USD/price, "f": features}
                        self.wallet -= BASE_USD
                        log.info(f"🟢 [BUY] {symbol} @ {price} | Prob: {prob_buy:.2%}")

                    # --- SELL LOGIC ---
                    elif s["position"]:
                        pnl_pct = (price - s["position"]["entry"]) / s["position"]["entry"]
                        
                        # Exit if profit > 0.6% or loss > 0.4% (Scalping settings)
                        if pnl_pct >= 0.006 or pnl_pct <= -0.004:
                            is_win = pnl_pct > 0
                            self.model.learn_one(s["position"]["f"], is_win)
                            
                            trade_result = s["position"]["qty"] * price
                            self.wallet += trade_result
                            
                            await self.send_tg(
                                f"🏁 *Trade Closed: {symbol}*\n"
                                f"PnL: `{pnl_pct:+.2%}` ({'✅' if is_win else '❌'})\n"
                                f"💰 *Wallet:* `${self.wallet:.2f}`\n"
                                f"📈 *Float:* `${float_pnl:+.2f}`"
                            )
                            s["position"] = None

async def main():
    bot = AlphaMLBot()
    # Runs the sentiment fetcher and the trading loop at the same time
    await asyncio.gather(bot.update_sentiment(), bot.run_hft())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("System Stopped.")


