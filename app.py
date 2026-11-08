import os
import datetime
from flask import Flask, render_template_string, jsonify, request
import yfinance as yf
import pandas as pd
import ta
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

def analyze_market_condition(df, asset):
    try:
        atr = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
        current_atr = atr.iloc[-1] if not atr.empty else 0
        avg_atr = atr.rolling(window=20).mean().iloc[-1] if not atr.empty else 0
        
        adx_ind = ta.trend.adx(df['High'], df['Low'], df['Close'], window=14)
        current_adx = adx_ind.iloc[-1] if not adx_ind.empty else 0
    except Exception:
        current_atr, avg_atr, current_adx = 0, 0, 0
    
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
        return "🔴 НЕ ТОРГУВАТИ (ВИХІД НОВИН)", "На ринку шторм через важливі економічні публікації. Технічні індикатори зараз не працюють.", news_warning
    elif current_atr > avg_atr * 1.5 and avg_atr > 0:
        return "🔴 НЕ ТОРГУВАТИ (ВИСОКА ВОЛАТИЛЬНІСТЬ)", "Амплітуда коливань занадто хаотична. Краще перечекати.", news_warning
    elif current_adx < 20:
        return "🟡 ОБЕРЕЖНО (ФЛЕТ / СЛАБКИЙ РИНОК)", "Ціна затиснута в коридорі, об'єми низькі. Сигнали RSI на відскок від меж є більш надійними.", news_warning
    elif current_adx > 25:
        return "🟢 ЧУДОВИЙ СТАН (СИЛЬНИЙ ТРЕНД)", "На ринку чіткий прогнозований рух. Сприятливий час для торгівлі за трендом.", news_warning
    else:
        return "🟢 СТАБІЛЬНИЙ РИНОК", "Умови в межах норми. Ринок спокійний і готовий до аналізу.", news_warning

def generate_signals(df):
    try:
        rsi = ta.momentum.rsi(df['Close'], window=14)
        
        bb_low = ta.volatility.bollinger_lband(df['Close'], window=20, window_sign=2)
        bb_high = ta.volatility.bollinger_hband(df['Close'], window=20, window_sign=2)
        
        macd_line = ta.trend.macd(df['Close'], window_fast=12, window_slow=26)
        signal_line = ta.trend.macd_signal(df['Close'], window_fast=12, window_slow=26)
        
        curr_close = df['Close'].iloc[-1]
        curr_rsi = rsi.iloc[-1]
        lower_bb = bb_low.iloc[-1]
        upper_bb = bb_high.iloc[-1]
        
        curr_macd = macd_line.iloc[-1]
        curr_signal = signal_line.iloc[-1]
        prev_macd = macd_line.iloc[-2] if len(macd_line) > 1 else curr_macd
        prev_signal = signal_line.iloc[-2] if len(signal_line) > 1 else curr_signal
    except Exception:
        return "SCANNING...", 0, df['Close'].iloc[-1]
    
    agree_count = 0
    direction = "SCANNING..."
    
    is_rsi_oversold = curr_rsi < 35
    is_bb_low = curr_close <= lower_bb
    is_macd_bullish = curr_macd > curr_signal
    
    is_rsi_overbought = curr_rsi > 65
    is_bb_high = curr_close >= upper_bb
    is_macd_bearish = curr_macd < curr_signal

    if is_rsi_oversold or is_bb_low or (prev_macd <= prev_signal and is_macd_bullish):
        direction = "CALL 🟢"
        if is_rsi_oversold: agree_count += 1
        if is_bb_low: agree_count += 1
        if is_macd_bullish: agree_count += 1
    elif is_rsi_overbought or is_bb_high or (prev_macd >= prev_signal and is_macd_bearish):
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
        if df.empty:
            return jsonify({"error": "No data found"}), 400
        
        market_status, market_desc, news_warning = analyze_market_condition(df, asset)
        signal_dir, confidence, entry_price = generate_signals(df)
        
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
    <script src="https://jsdelivr.net"></script>
</head>
<body class="bg-gray-900 text-gray-100 font-sans min-h-screen p-4">
    <div class="max-w-md mx-auto space-y-4">
        <div class="bg-gray-800 p-4 rounded-xl shadow-lg border border-gray-700 text-center">
            <h1 class="text-xl font-bold text-green-400 tracking-wider">POCKET OPTION ANALYZER</h1>
            <p class="text-xs text-gray-400 mt-1">Сигнали та Волатильність у реальному часі</p>
        </div>

        <div class="bg-gray-800 p-4 rounded-xl shadow-lg border border-gray-700 space-y-3">
            <div>
                <label class="text-xs text-gray-400 block mb-1">Виберіть Актив:</label>
                <select id="assetSelect" class="w-full bg-gray-700 border border-gray-600 rounded p-2 text-sm focus:outline-none focus:border-green-500">
                    <option value="EURUSD=X">EUR/USD</option>
                    <option value="GBPUSD=X">GBP/USD</option>
                    <option value="USDCAD=X">USD/CAD</option>
                    <option value="USDJPY=X">USD/JPY</option>
                    <option value="BTC-USD">BTC/USD (Crypto)</option>
                </select>
            </div>
            <div>
                <label class="text-xs text-gray-400 block mb-1">Час Експірації:</label>
                <select id="intervalSelect" class="w-full bg-gray-700 border border-gray-600 rounded p-2 text-sm focus:outline-none focus:border-green-500">
                    <option value="1m">1 Хвилина</option>
                    <option value="2m">2 Хвилини</option>
                    <option value="5m">5 Хвилин</option>
                    <option value="15m">15 Хвилин</option>
                </select>
            </div>
            <button id="analyzeBtn" class="w-full bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white font-bold p-3 rounded-lg text-sm transition shadow-md">
                🔄 АНАЛІЗУВАТИ РИНОК
            </button>
        </div>

        <div class="bg-gray-800 p-4 rounded-xl shadow-lg border border-gray-700 space-y-2">
            <h2 class="text-xs font-semibold text-gray-400 uppercase tracking-wider">📊 Волатильність ринку та Новини</h2>
            <div id="marketBadge" class="p-3 rounded-lg font-bold text-center text-sm bg-gray-700 text-gray-300">
                НАТИСНІТЬ АНАЛІЗ ДЛЯ МОНІТОРИНГУ
            </div>
            <p id="marketDesc" class="text-xs text-gray-400 italic px-1"></p>
            <div id="newsWarning" class="text-xs text-yellow-500 font-medium border-t border-gray-700 pt-2 mt-2"></div>
        </div>

        <div class="bg-gray-800 p-4 rounded-xl shadow-lg border border-gray-700 space-y-3">
            <h2 class="text-xs font-semibold text-gray-400 uppercase tracking-wider">🎯 Поточний Сигнал</h2>
            <div class="flex justify-between items-center bg-gray-900 p-3 rounded-lg border border-gray-700">
                <span class="text-sm font-medium">Напрямок угоди:</span>
                <span id="signalDir" class="text-lg font-black tracking-wide text-gray-400">---</span>
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs">
                <div class="bg-gray-900 p-2 rounded border border-gray-700">
                    <span class="text-gray-500 block">Впевненість:</span>
                    <span id="confidenceVal" class="font-bold text-sm text-white">0%</span>
                </div>
                <div class="bg-gray-900 p-2 rounded border border-gray-700">
                    <span class="text-gray-500 block">Ціна входу:</span>
                    <span id="entryPrice" class="font-bold text-sm text-white">0.0000</span>
                </div>
            </div>
            <p class="text-[10px] text-gray-500 text-center">Останнє оновлення: <span id="updateTime">Ніколи</span></p>
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
                        badge.className = "p-3 rounded-lg font-bold text-center text-sm bg-red-950 text-red-400 border border-red-800";
                    } else if (data.market_status.includes('🟡')) {
                        badge.className = "p-3 rounded-lg font-bold text-center text-sm bg-yellow-950 text-yellow-400 border border-yellow-800";
                    } else {
                        badge.className = "p-3 rounded-lg font-bold text-center text-sm bg-green-950 text-green-400 border border-green-800";
                    }
                    
                    document.getElementById('marketDesc').innerText = data.market_desc;
                    document.getElementById('newsWarning').innerText = data.news_warning;

                    const sigDir = document.getElementById('signalDir');
                    sigDir.innerText = data.signal_direction;
                    if (data.signal_direction.includes('🟢')) sigDir.className = "text-lg font-black text-green-400";
                    else if (data.signal_direction.includes('🔴')) sigDir.className = "text-lg font-black text-red-500";
                    else sigDir.className = "text-lg font-black text-gray-400";

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
