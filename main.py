import os
import time
import json
import requests
import threading
from flask import Flask, jsonify
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STATE_FILE = os.getenv(
    "TRADEPULSE_STATE_FILE",
    "/data/tradepulse_state.json"
)

COINS = {
    "BTC": "bitcoin",
    "SOL": "solana",
    "XRP": "ripple",
}

STARTING_CASH = 100.00
TRADE_SIZE = 25.00
CHECK_EVERY = 300
app = Flask(__name__)
latest_signals = {}
@app.route("/signals")
def signals():
    return jsonify(latest_signals)
cash = STARTING_CASH
positions = {}
wins = 0
losses = 0
realized_pnl = 0.0


def send_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        print(text, flush=True)
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": text},
            timeout=20
        )
        response.raise_for_status()
    except Exception as e:
        print("Telegram error:", e, flush=True)


def save_state():
    state = {
        "cash": cash,
        "positions": positions,
        "wins": wins,
        "losses": losses,
        "realized_pnl": realized_pnl
    }

    try:
        folder = os.path.dirname(STATE_FILE)

        if folder:
            os.makedirs(folder, exist_ok=True)

        temp_file = STATE_FILE + ".tmp"

        with open(temp_file, "w") as f:
            json.dump(state, f, indent=2)

        os.replace(temp_file, STATE_FILE)

        print("Portfolio state saved.", flush=True)

    except Exception as e:
        print("State save error:", e, flush=True)


def load_state():
    global cash, positions, wins, losses, realized_pnl

    if not os.path.exists(STATE_FILE):
        print("No saved portfolio found. Starting new.", flush=True)
        save_state()
        return

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)

        cash = float(state.get("cash", STARTING_CASH))
        positions = state.get("positions", {})
        wins = int(state.get("wins", 0))
        losses = int(state.get("losses", 0))
        realized_pnl = float(state.get("realized_pnl", 0.0))

        print("Saved portfolio loaded.", flush=True)

    except Exception as e:
        print("State load error:", e, flush=True)


def ema(values, period=20):
    if len(values) < period:
        return sum(values) / len(values)

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (price - result) * multiplier + result

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return 50

    gains = []
    losses_list = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change > 0:
            gains.append(change)
            losses_list.append(0)
        else:
            gains.append(0)
            losses_list.append(abs(change))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses_list[-period:]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_market_data(coin_id):
    url = (
        f"https://api.coingecko.com/api/v3/coins/"
        f"{coin_id}/market_chart"
    )

    params = {
        "vs_currency": "usd",
        "days": "1"
    }

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    prices = [x[1] for x in data["prices"]]
    volumes = [x[1] for x in data["total_volumes"]]

    return prices, volumes


def analyze(symbol, coin_id):
    prices, volumes = get_market_data(coin_id)

    if len(prices) < 25:
        return None

    price = prices[-1]
    ema20 = ema(prices[-50:], 20)
    rsi14 = rsi(prices[-30:], 14)

    previous_price = prices[-6]

    momentum = (
        (price - previous_price) / previous_price
    ) * 100

    recent_volumes = volumes[-20:]

    avg_volume = sum(recent_volumes[:-1]) / max(
        len(recent_volumes[:-1]), 1
    )

    volume_ratio = (
        recent_volumes[-1] / avg_volume
        if avg_volume > 0 else 1
    )

    signal = "WAIT"

    if (
        price > ema20
        and 50 <= rsi14 <= 70
        and momentum > 0.15
        and volume_ratio > 1.05
    ):
        signal = "BUY"

    elif (
        price < ema20
        and 30 <= rsi14 <= 50
        and momentum < -0.15
        and volume_ratio > 1.05
    ):
        signal = "SELL"

    return {
        "symbol": symbol,
        "price": price,
        "ema": ema20,
        "rsi": rsi14,
        "momentum": momentum,
        "volume_ratio": volume_ratio,
        "signal": signal,
    }


def paper_buy(data):
    global cash

    symbol = data["symbol"]

    if symbol in positions:
        return

    if cash < TRADE_SIZE:
        return

    amount = TRADE_SIZE / data["price"]

    positions[symbol] = {
        "entry": data["price"],
        "amount": amount
    }

    cash -= TRADE_SIZE

    save_state()

    send_message(
        f"🧪 PAPER BUY — {symbol}\n\n"
        f"Entry: ${data['price']:,.4f}\n"
        f"Trade size: ${TRADE_SIZE:.2f}\n"
        f"RSI: {data['rsi']:.1f}\n"
        f"Momentum: {data['momentum']:+.2f}%\n"
        f"Virtual cash: ${cash:.2f}\n\n"
        f"⚠️ Simulation only — no real money used."
    )


def paper_sell(data):
    global cash, wins, losses, realized_pnl

    symbol = data["symbol"]

    if symbol not in positions:
        return

    position = positions[symbol]

    value = position["amount"] * data["price"]
    cost = position["amount"] * position["entry"]

    pnl = value - cost
    pnl_pct = (pnl / cost) * 100

    cash += value
    realized_pnl += pnl

    if pnl > 0:
        wins += 1
    else:
        losses += 1

    del positions[symbol]

    save_state()

    total_trades = wins + losses

    win_rate = (
        wins / total_trades * 100
        if total_trades > 0 else 0
    )

    send_message(
        f"🧪 PAPER SELL — {symbol}\n\n"
        f"Exit: ${data['price']:,.4f}\n"
        f"Trade P/L: ${pnl:+.2f} ({pnl_pct:+.2f}%)\n"
        f"Virtual cash: ${cash:.2f}\n"
        f"Total realized P/L: ${realized_pnl:+.2f}\n"
        f"Record: {wins}W / {losses}L\n"
        f"Win rate: {win_rate:.1f}%\n\n"
        f"⚠️ Simulation only — no real money was used."
    )


def scan():
    for symbol, coin_id in COINS.items():
        try:
            data = analyze(symbol, coin_id)

            if not data:
                latest_signals[symbol] = {
    "signal": data["signal"],
    "price": data["price"],
    "rsi": round(data["rsi"], 1),
    "momentum": round(data["momentum"], 2)
}
            
            print(
                symbol,
                data["signal"],
                data["price"],
                flush=True
            )

            if data["signal"] == "BUY":
                paper_buy(data)

            elif data["signal"] == "SELL":
                paper_sell(data)

        except Exception as e:
            print(symbol, "error:", e, flush=True)
def main():
        port = int(os.getenv("PORT", "8080"))
        threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False
        ),
        daemon=True
    ).start()
        load_state()

        send_message(
        "🤖 404 TradePulse is online.\n"
        "Scan. Analyze. Alert.\n\n"
        "🧪 Paper trading mode\n"
        "Watching: BTC • SOL • XRP\n"
        f"Virtual cash: ${cash:.2f}\n"
        f"Record: {wins}W / {losses}L"
    )

        print("404 TradePulse started.", flush=True)

        while True:
                scan()
                time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main()
