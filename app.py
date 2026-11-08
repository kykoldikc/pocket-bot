import os
import datetime
import math
from flask import Flask, render_template_string, jsonify, request
import yfinance as yf
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

CURRENCY_MAP = {
    "EURUSD=X": ["EUR", "USD"],
    "GBPUSD=X": ["GBP", "USD"],
    "AUDUSD=X": ["AUD", "USD"],
    "USDCAD=X": ["USD", "CAD"],
    "USDJPY=X": ["USD", "JPY"],
    "BTC-USD": ["BTC", "USD"],
    "ETH-USD": ["ETH", "USD"]
}

def fetch_economic_calendar():
    url = "https://investing.com"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    events = []
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            table = soup.find('table', id='economicCalendarData')
            if table:
                rows = table.find_all('tr', class_='js-event-item')
                for row in rows:
                    time_col = row.find('td', class_='time')
                    cur_col = row.find('td', class_='flagCur')
                    event_col = row.find('td', class_='event')
                    sentiment_col = row.find('td', class_='sentiment')
                    
                    if time_col and cur_col and event_col and sentiment_col:
                        stars = len(sentiment_col.find_all('i', class_='grayFullBullishIcon'))
                        if stars == 0:
                            stars = len(sentiment_col.find_all('i', class_='js-bullish-icon'))
                        
                        events.append({
                            "time": time_col.text.strip(),
                            "currency": cur_col.text.strip(),
                            "event": event_col.text.strip(),
                            "impact": stars if stars > 0 else 1
                        })
    except Exception:
        pass
    return events

def calculate_indicators(prices):
    if len(prices) < 30:
        return 50, prices[-1], prices[-1], 0, 0, 0, 0
        
    gains = []
    losses = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(diff if diff > 0 else 0)
        losses.append(abs(diff) if diff < 0 else 0)
        
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14
    rsi = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss != 0 else 100

    period_20 = prices[-20:]
    sma_20 = sum(period_20) / 20
    variance = sum((x - sma_20) ** 2 for x in period_20) / 20
    std_dev = math.sqrt(variance)
    upper_bb = sma_20 + (2 * std_dev)
    lower_bb = sma_20 - (2 * std_dev)

    current_atr = abs(prices[-1] - prices[-2])
    avg_atr = sum(abs(prices[i] - prices[i-1]) for i in range(-20, 0)) / 20

    macd_fast = sum(prices[-12:]) / 12
    macd_slow = sum(prices[-26:]) / 26
    macd_line = macd_fast - macd_slow
    signal_line = sum(prices[-9:]) / 9 - macd_slow
    
    return rsi, upper_bb, lower_bb, current_atr, avg_atr, macd_line, signal_line

def analyze_market_condition(prices, asset):
    rsi, upper_bb, lower_bb, current_atr, avg_atr, macd_line, signal_line = calculate_indicators(prices)
    
    news_events = fetch_economic_calendar()
    relevant_currencies = CURRENCY_MAP.get(asset, [])
    news_warning = None
    high_impact_news_active = False
    
    now = datetime.datetime.now()
    for ev in news_events:
        if ev['currency'] in relevant_currencies and ev['impact'] == 3:
            try:
                ev_time = datetime.datetime.strptime(ev['time'], "%H:%M").time()
                ev_datetime = datetime.datetime.combine(now.date(), ev_time)
                time_diff = abs((now - ev_datetime).total_seconds() / 60.0)
                
                if time_diff <= 15:
                    high_impact_news_active = True
                    news_warning = f"⚠️ Важливі новини ({ev['currency']}): {ev['event']} о {ev['time']}"
                    break
            except Exception:
                pass

    if high_impact_news_active:
        return "🔴 НЕ ТОРГУВАТИ (ВИХІД НОВИН)", "На ринку шторм через важливі новини. Індикатори зараз не працюють.", news_warning
    elif current_atr > avg_atr * 1.5 and avg_atr > 0:
        return "🔴 НЕ ТОРГУВАТИ (ВИСОКА ВОЛАТИЛЬНІСТЬ)", "Амплітуда коливань занадто хаотична. Краще перечекати.", news_warning
    elif current_atr < avg_atr * 0.5 and avg_atr > 0:
        return "🟡 ОБЕРЕЖНО (ФЛЕТ / СЛАБКИЙ РИНОК)", "Ціна майже стоїть на місці. Сигнали RSI на відскок є більш надійними.", news_warning
    else:
        return "🟢 СТАБІЛЬНИЙ РИНОК", "Умови в межах норми. Ринок спокійний і готовий до аналізу.", news_warning

def generate_signals(prices):
    rsi, upper_bb, lower_bb, current_atr, avg_atr, macd_line, signal_line = calculate_indicators(prices)
    curr_close = prices[-1]
    
    agree_count = 0
    direction = "SCANNING..."
    
    is_rsi_oversold = rsi < 35
    is_bb_low = curr_close <= lower_bb
    is_macd_bullish = macd_line > signal_line
    
    is_rsi_overbought = rsi > 65
    is_bb_high = curr_close >= upper_bb
    is_macd_bearish = macd_line < signal_line

    if is_rsi_oversold or is_bb_low or is_macd_bullish:
        direction = "CALL 🟢"
        if is_rsi_oversold: agree_count += 1
        if is_bb_low: agree_count += 1
        if is_macd_bullish: agree_count += 1
    elif is_rsi_overbought or is_bb_high or is_macd_bearish:
        direction = "PUT 🔴"
        if is_rsi_overbought: agree_count += 1
        if is_bb_high: agree_count += 1
        if is_macd_bearish: agree_count += 1

    confidence = int((agree_count / 3) * 100) if direction != "SCANNING..." else 0
    return direction, confidence, round(curr_close, 5)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/analyze', methods=['GET'])
def analyze():
    asset = request.args.get('asset', 'EURUSD=X')
    interval = request.args.get('interval', '1m')
    yf_interval = "1m" if interval == "1m" else "2m" if interval == "2m" else "5m" if interval == "5m" else "15m"
    
    try:
        ticker = yf.Ticker(asset)
        df = ticker.history(period="1d", interval=yf_interval)
        if df.empty or len(df) < 5:
            return jsonify({"error": "No data found"}), 400
            
        prices = df['Close'].tolist()
        market_status, market_desc, news_warning = analyze_market_condition(prices, asset)
        signal_dir, confidence, entry_price = generate_signals(prices)
        
        return jsonify({
            "market_status": market_status,
            "market_desc": market_desc,
            "news_warning": news_warning or "Важливих новин на найближчі 15 хв немає",
            "signal_direction": signal_dir,
            "confidence": f"{confidence}%",
            "entry_price": entry_price,
            "time": datetime.datetime.now().strftime("%H:%M:%S")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pocket Option Signal App</title>
    <style>
        body { background-color: #111827; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 15px; margin: 0; }
        .card { background-color: #1f2937; padding: 15px; border-radius: 12px; border: 1px solid #374151; margin-bottom: 15px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        h1 { color: #34d399; font-size: 18px; margin: 0 0 5px 0; font-weight: bold; letter-spacing: 1px; text-align: center; }
        h2 { font-size: 12px; color: #9ca3af; text-transform: uppercase; margin: 0 0 10px 0; letter-spacing: 0.5px; }
        label { font-size: 12px; color: #9ca3af; display: block; margin-bottom: 4px; }
        select { w-index: 10; width: 100%; bg-color: #374151; background: #374151; color: white; border: 1px solid #4b5563; padding: 8px; border-radius: 6px; font-size: 14px; margin-bottom: 10px; outline: none; box-sizing: border-box; }
        button { width: 100%; background-color: #2563eb; color: white; border: none; padding: 12px; border-radius: 8px; font-weight: bold; font-size: 14px; cursor: pointer; transition: background 0.2s; }
        button:active { background-color: #1d4ed8; }
        .badge { padding: 12px; border-radius: 8px; font-weight: bold; text-align: center; font-size: 14px; background-color: #374151; color: #d1d5db; margin-bottom: 8px; }
        .flex-row { display: flex; justify-content: space-between; align-items: center; background-color: #111827; padding: 10px; border-radius: 8px; border: 1px solid #374151; }
        .grid-2 { display: grid; grid-template-cols: 1fr 1fr; gap: 8px; margin-top: 8px; }
        .grid-item { background-color: #111827; padding: 8px; border-radius: 6px; border: 1px solid #374151; }
        .grid-item span { display: block; font-size: 11px; color: #6b7280; }
        .grid-item font { font-weight: bold; font-size: 14px; color: white; }
    </style>
</head>
<body>
    <div style="max-width: 400px; margin: 0 auto;">
        <!-- Header -->
        <div class="card" style="text-align: center;">
            <h1>POCKET OPTION ANALYZER</h1>
            <div style="font-size: 11px; color: #9ca3af;">Сигнали та Волатильність у реальному часі</div>
        </div>

        <!-- Налаштування -->
        <div class="card">
            <label>Виберіть Актив:</label>
            <select id="assetSelect">
                <option value="EURUSD=X">EUR/USD</option>
                <option value="GBPUSD=X">GBP/USD</option>
                <option value="USDCAD=X">USD/CAD</option>
                <option value="USDJPY=X">USD/JPY</option>
                <option value="BTC-USD">BTC/USD (Crypto)</option>
            </select>
            
            <label>Час Експірації:</label>
            <select id="intervalSelect">
                <option value="1m">1 Хвилина</option>
                <option value="2m">2 Хвилини</option>
                <option value="5m">5 Хвилин</option>
                <option value="15m">15 Хвилин</option>
            </select>
            
            <button id="analyzeBtn">🔄 АНАЛІЗУВАТИ РИНОК</button>
        </div>

        <!-- Волатильність -->
        <div class="card">
            <h2>📊 Волатильність ринку та Новини</h2>
            <div id="marketBadge" class="badge">НАТИСНІТЬ АНАЛІЗ ДЛЯ МОНІТОРИНГУ</div>
            <div id="marketDesc" style="font-size: 12px; color: #9ca3af; font-style: italic;"></div>
            <div id="newsWarning" style="font-size: 12px; color: #f59e0b; font-weight: 500; margin-top: 8px; border-top: 1px solid #374151; padding-top: 6px;"></div>
        </div>

        <!-- Сигнал -->
        <div class="card">
            <h2>🎯 Поточний Сигнал</h2>
            <div class="flex-row">
                <span style="font-size: 14px;">Напрямок угоди:</span>
                <span id="signalDir" style="font-size: 18px; font-weight: 900; color: #9ca3af;">---</span>
            </div>
            <div class="grid-2">
                <div class="grid-item">
                    <span>Впевненість:</span>
                    <font id="confidenceVal">0%</font>
                </div>
                <div class="grid-item">
                    <span>Ціна входу:</span>
                    <font id="entryPrice">0.0000</font>
                </div>
            </div>
            <div style="font-size: 10px; color: #4b5563; text-align: center; margin-top: 8px;">Останнє оновлення: <span id="updateTime">Ніколи</span></div>
        </div>
    </div>

    <script>
        document.getElementById('analyzeBtn').addEventListener('click', async () => {
            const asset = document.getElementById('assetSelect').value;
            const interval = document.getElementById('intervalSelect').value;
            const btn = document.getElementById('analyzeBtn');
            
            btn.innerText = "⏳ ЗАВАНТАЖЕННЯ ДАНИХ...";
            btn.disabled = true;

            try {
                const response = await fetch(`/api/analyze?asset=${asset}&interval=${interval}`);
                const data = await response.json();
                
                if (data.error) {
                    alert("Помилка: " + data.error);
                } else {
                    const badge = document.getElementById('marketBadge');
                    badge.innerText = data.market_status;
                    if (data.market_status.includes('🔴')) {
                        badge.style.backgroundColor = "#450a0a"; badge.style.color = "#f87171"; badge.style.border = "1px solid #991b1b";
                    } else if (data.market_status.includes('🟡')) {
                        badge.style.backgroundColor = "#451a03"; badge.style.color = "#fbbf24"; badge.style.border = "1px solid #92400e";
                    } else {
                        badge.style.backgroundColor = "#064e3b"; badge.style.color = "#34d399"; badge.style.border = "1px solid #065f46";
                    }
                    
                    document.getElementById('marketDesc').innerText = data.market_desc;
                    document.getElementById('newsWarning').innerText = data.news_warning;

                    const sigDir = document.getElementById('signalDir');
                    sigDir.innerText = data.signal_direction;
                    if (data.signal_direction.includes('🟢')) sigDir.style.color = "#34d399";
                    else if (data.signal_direction.includes('🔴')) sigDir.style.color = "#f87171";
                    else sigDir.style.color = "#9ca3af";

                    document.getElementById('confidenceVal').innerText = data.confidence;
                    document.getElementById('entryPrice').innerText = data.entry_price;
                    document.getElementById('updateTime').innerText = data.time;
                }
            } catch (err) {
                alert("Не вдалося з'єднатися з сервером.");
            } finally {
                btn.innerText = "🔄 АНАЛІЗУВАТИ РИНОК";
                btn.disabled = false;
            }
        });
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
