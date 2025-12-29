
import asyncio, json, aiohttp, logging, numpy as np, pandas as pd, ta
from collections import deque
from river import linear_model, preprocessing, compose, metrics
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk
from telegram import Bot

# 1. Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("Alpha-ML-V4")

# Download sentiment tools
nltk.download('vader_lexicon', quiet=True)

# ================= CONFIG =================
TELEGRAM_TOKEN = "8488789199:AAHhViKmhXlvE7WpgZGVDS4WjCjUuBVtqzQ"
TELEGRAM_CHAT_ID = "5665906172"
CRYPTOPANIC_API_KEY = "936ee60c210fd21b853971b458bfdf6ef2515eb3"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
BASE_USD = 10.0  
# ==========================================

class AlphaMLBot:
    def __init__(self):
        self.wallet = 20.0  
        self.sia = SentimentIntensityAnalyzer()
        self.current_sentiment = 0.0
        self.tg_bot = Bot(token=TELEGRAM_TOKEN)
        
        # ML Engine: Standard Scaler + Online Logistic Regression
        self.model = compose.Pipeline(
            preprocessing.StandardScaler(), 
            linear_model.LogisticRegression()
        )
        self.metric = metrics.Accuracy()
        
        # State Management (Expanded deques for advanced indicators)
        self.state = {s: {
            "price_history": deque(maxlen=200), # Increased for MFI/Volatility
            "flow": deque(maxlen=50),           # For Volume Imbalance
            "position": None, 
            "current_price": 0.0
        } for s in SYMBOLS}

    async def send_tg(self, text):
        try:
            await self.tg_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="Markdown")
        except Exception as e:
            log.error(f"TG Notification Error: {e}")

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
        if len(prices) < 30: return None
        
        # Combined Advanced Features
        return {
            "rsi": ta.momentum.rsi(prices, window=14).iloc[-1],
            "zscore": (prices.iloc[-1] - prices.mean()) / (prices.std() + 1e-9),
            "mfi": ta.volume.money_flow_index(prices, prices, prices, pd.Series([1]*len(prices)), window=14).iloc[-1],
            "volatility": prices.pct_change().std(),
            "flow_imbalance": sum(s["flow"]),
            "news_mood": self.current_sentiment
        }

    async def run_hft(self):
        log.info("🚀 Advanced ML Engine Starting...")
        await self.send_tg("🤖 *Alpha-ML V4 Online*\nTechnical + Sentiment Analysis active.")
        
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
                    # Track trade flow (Positive for buys, Negative for sells)
                    s["flow"].append(-vol if is_maker else vol)
                    
                    features = self.get_features(symbol)
                    if not features: continue
                    
                    # ML Decision Logic
                    prob_buy = self.model.predict_proba_one(features).get(True, 0.5)
                    float_pnl = self.get_total_metrics()

                    # --- BUY LOGIC (80% Confidence + Neutral/Bullish Sentiment) ---
                    if not s["position"] and prob_buy > 0.80 and self.current_sentiment > -0.1:
                        s["position"] = {"entry": price, "qty": BASE_USD/price, "f": features}
                        self.wallet -= BASE_USD
                        log.info(f"🟢 BUY {symbol} @ {price} | ML: {prob_buy:.1%}")

                    # --- SELL LOGIC (TP/SL + Online Learning) ---
                    elif s["position"]:
                        pnl_pct = (price - s["position"]["entry"]) / s["position"]["entry"]
                        
                        if pnl_pct >= 0.008 or pnl_pct <= -0.004:
                            is_win = pnl_pct > 0
                            # Teach the model which features led to this result
                            self.model.learn_one(s["position"]["f"], is_win)
                            self.metric.update(is_win, True)
                            
                            trade_result = s["position"]["qty"] * price
                            self.wallet += trade_result
                            
                            status_msg = (
                                f"🏁 *Trade Closed: {symbol}*\n"
                                f"Result: `{pnl_pct:+.2%}` ({'✅ WIN' if is_win else '❌ LOSS'})\n"
                                f"💰 *Wallet:* `${self.wallet:.2f}`\n"
                                f"📈 *Floating P&L:* `${float_pnl:+.2f}`"
                            )
                            await self.send_tg(status_msg)
                            s["position"] = None

async def main():
    bot = AlphaMLBot()
    await asyncio.gather(bot.update_sentiment(), bot.run_hft())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("System Stopped.")

