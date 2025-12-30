import ccxt

exchange = ccxt.binancecoinm({
    'apiKey': 'p4FKZRHA26Z3VWyRPF5xZFc3aDU8vxTy7OCULtX7wCgN6l3EaNl882q4JzruPIsE',
    'secret': 'CXqJa5JaKxwVPT5ik3EBbB2Mm0IMp4J0I0OSEY1Q6SKk7PkWHwf7tyDBhxKwLn1b',
    'enableRateLimit': True,
})

try:
    # This is the lightest private request possible
    balance = exchange.fetch_balance()
    print("✅ Connection Successful!")
    print(f"Connected to: {exchange.id}")
except Exception as e:
    print(f"❌ Connection Failed: {e}")
