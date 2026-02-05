import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd
import json
import os
from datetime import datetime, timedelta
from FinMind.data import DataLoader
from plotly.subplots import make_subplots

# --- 0. 資料庫功能設定 ---
DB_FILE = "my_stock_db.json"

def load_db():
    default_data = {
        "groups": {
            "我的最愛": {
                "list": {"2356.TW": "英業達", "0050.TW": "元大台灣50"},
                "costs": {
                    "2356.TW": {"cost": 49.0, "qty": 1.0},
                    "0050.TW": {"cost": 70.0, "qty": 1.0}
                }
            }
        },
        "selected_group": "我的最愛"
    }
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default_data
    return default_data

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

if 'db' not in st.session_state:
    st.session_state.db = load_db()

# --- 1. 配置 FinMind ---
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNi0wMS0yOCAwODoyNToyNyIsInVzZXJfaWQiOiJ0ZWRkeWphY2siLCJlbWFpbCI6InRlZGR5amFjazVAeWFob28uY29tLnR3IiwiaXAiOiI0Mi43Mi4yMTEuMTUzIn0.Su4W8X5E9XPN9PZdA03Z6XO6i630kOSvOjcrLowcO-I"
dl = DataLoader()
try:
    dl.set_token(token=FINMIND_TOKEN)
except:
    pass

st.set_page_config(page_title="小鐵的股票分析報告", layout="wide")
st.title("📈 小鐵的股票分析報告") 

# --- 2. 側邊欄管理 ---
st.sidebar.title("🛠️ 小鐵的導航面板")

# A. 分類選擇
all_groups = list(st.session_state.db["groups"].keys())
current_group = st.sidebar.selectbox("選擇分類", all_groups)

new_group_name = st.sidebar.text_input("➕ 新增分類名稱")
if st.sidebar.button("建立新分類"):
    if new_group_name and new_group_name not in st.session_state.db["groups"]:
        st.session_state.db["groups"][new_group_name] = {"list": {}, "costs": {}}
        save_db(st.session_state.db)
        st.rerun()

st.sidebar.divider()
active_list = st.session_state.db["groups"][current_group]["list"]
active_costs = st.session_state.db["groups"][current_group]["costs"]

# B. 庫存管理
st.sidebar.subheader(f"📍 管理【{current_group}】")
col_id, col_name = st.sidebar.columns(2)
m_id = col_id.text_input("代號", placeholder="2330.TW", key="m_id").upper()
m_name = col_name.text_input("名稱", placeholder="台積電", key="m_name")

if st.sidebar.button("➕ 加入此分類"):
    if m_id and m_name:
        st.session_state.db["groups"][current_group]["list"][m_id] = m_name
        save_db(st.session_state.db)
        st.rerun()

# C. 股票選取 (核心修改：先選取再搜尋)
selected_ticker = st.sidebar.selectbox(
    "選取庫存股票", 
    list(active_list.keys()), 
    format_func=lambda x: f"{x} {active_list[x]}" if x in active_list else x
)

if st.sidebar.button(f"🗑️ 刪除所選股票"):
    if selected_ticker in active_list:
        del st.session_state.db["groups"][current_group]["list"][selected_ticker]
        if selected_ticker in active_costs:
            del st.session_state.db["groups"][current_group]["costs"][selected_ticker]
        save_db(st.session_state.db)
        st.rerun()

st.sidebar.markdown("---")
custom_ticker = st.sidebar.text_input("🔍 全域搜尋 (不加入庫存)", "")
ticker_input = custom_ticker if custom_ticker else selected_ticker

period = st.sidebar.selectbox("分析時間範圍", ["5d", "1mo", "6mo", "1y", "2y"], index=2)

# D. 帳務管理
st.sidebar.subheader(f"💰 {ticker_input} 帳務管理")
stock_acc = active_costs.get(ticker_input, {"cost": 0.0, "qty": 1.0})
if isinstance(stock_acc, (float, int)): stock_acc = {"cost": stock_acc, "qty": 1.0}
buy_cost = st.sidebar.number_input("買入單價", value=float(stock_acc['cost']))
buy_qty = st.sidebar.number_input("持有張數", value=float(stock_acc['qty']), step=1.0)

if st.sidebar.button("💾 儲存帳務"):
    st.session_state.db["groups"][current_group]["costs"][ticker_input] = {"cost": buy_cost, "qty": buy_qty}
    save_db(st.session_state.db)
    st.sidebar.success("帳務已更新！")

show_news = st.sidebar.checkbox("顯示相關新聞", value=True)

# --- 3. 計算函數 ---
def calculate_rsi(df, periods=14):
    if len(df) < periods: return pd.Series([50] * len(df))
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))
def calculate_macd(df, fast=12, slow=26, signal=9):
    ema12 = df['Close'].ewm(span=fast, adjust=False).mean()
    ema26 = df['Close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram
def calculate_atr(df, window=14):
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(window=window).mean()

if ticker_input:
    data = yf.download(ticker_input, period=period)
    if not data.empty:
        data['MACD'], data['Signal'], data['Hist'] = calculate_macd(data)
        data['ATR'] = calculate_atr(data)
        close_series = data['Close']
        if isinstance(close_series, pd.DataFrame):
            close_series = close_series.iloc[:, 0]  # 如果是多欄位，只取第一欄
            
        atr_series = data['ATR']
        if isinstance(atr_series, pd.DataFrame):
            atr_series = atr_series.iloc[:, 0]
        data['ATR_Trailing'] = close_series.rolling(window=20).max() - (atr_series * 2)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data['MA5'] = data['Close'].rolling(window=5).mean()
        data['MA20'] = data['Close'].rolling(window=20).mean()
        data['MA60'] = data['Close'].rolling(window=60).mean()
        data['RSI'] = calculate_rsi(data)

        curr = data.iloc[-1]
        prev = data.iloc[-2]
        price = float(curr['Close'])
        high_60d = float(data['High'].tail(60).max())

        # --- 4. 指標儀表板 ---
        st.subheader(f"📊 {ticker_input} {active_list.get(ticker_input, '')} 即時概況")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("當前股價", f"{price:.2f}", f"{price - float(prev['Close']):.2f}", delta_color="inverse")
        m2.metric("60日高點", f"{high_60d:.2f}")
        m3.metric("5日均線", f"{float(curr['MA5']):.2f}")
        m4.metric("月線(20MA)", f"{float(curr['MA20']):.2f}")
        m5.metric("季線(60MA)", f"{float(curr['MA60']):.2f}")
        m6.metric("RSI(14)", f"{float(curr['RSI']):.1f}")

        # --- 6. 三大法人籌碼 ---
        st.write("---")
        st.subheader("👥 昨日三大法人買賣數據 (張)")
        f_net = 0
        try:
            target_id = ticker_input.split('.')[0]
            df_chip = dl.taiwan_stock_institutional_investors(
                stock_id=target_id, start_date=(datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
            )
            if not df_chip.empty:
                last_day = df_chip['date'].iloc[-1]
                today_chip = df_chip[df_chip['date'] == last_day]
                def get_net(names):
                    sub = today_chip[today_chip['name'].isin(names)]
                    return (sub['buy'].sum() - sub['sell'].sum()) / 1000
                f_net = get_net(['Foreign_Investor', 'Foreign_Investor_Excluded_Foreign_Investment_Trust'])
                d_net = get_net(['Investment_Trust'])
                s_net = get_net(['Dealer_Self', 'Dealer_proprietary', 'Dealer_Hedge'])
                def color_metric(label, value):
                    # 判斷顏色：正數紅色，負數綠色，0則白色
                    color = "#FF4B4B" if value > 0 else ("#00B050" if value < 0 else "#FFFFFF")
                    return f"""
                    <div style="text-align: center;">
                        <p style="color: gray; font-size: 16px; margin-bottom: 5px;">{label}</p>
                        <p style="color: {color}; font-size: 32px; font-weight: bold; margin-top: 0px;">
                            {int(value):,} 張
                        </p>
                    </div>
                    """

                c1, c2, c3 = st.columns(3)
                # 使用 markdown 渲染 HTML
                c1.markdown(color_metric("外資", f_net), unsafe_allow_html=True)
                c2.markdown(color_metric("投信", d_net), unsafe_allow_html=True)
                c3.markdown(color_metric("自營商", s_net), unsafe_allow_html=True)
                
                st.write("") # 留一點間距
                st.caption(f"數據更新日期：{last_day}")
        except:
            st.error("籌碼抓取失敗")

        # --- 6. 繪製圖表 ---
        fig = make_subplots(
            rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.05,
            subplot_titles=('K線與均線', '成交量', 'RSI 強弱指標', 'MCAD趨勢指標'),
            row_width=[0.2, 0.2, 0.2, 0.4]
        )
        # 加入 ATR 移動止損線
        fig.add_trace(go.Scatter(
            x=data.index, 
            y=data['ATR_Trailing'], 
            name="ATR 2.0 止損線", 
            line=dict(color='rgba(255, 165, 0, 0.5)', width=2, dash='dot'), # 橘色半透明虛線
            fill=None
        ), row=1, col=1)
        fig.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name="K線", increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data['MA5'], name="5MA", line=dict(color='cyan')), row=1, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data['MA20'], name="20MA", line=dict(color='orange')), row=1, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data['MA60'], name="60MA", line=dict(color='purple')), row=1, col=1)
        
        v_colors = ['red' if r['Close'] >= r['Open'] else 'green' for _, r in data.iterrows()]
        fig.add_trace(go.Bar(x=data.index, y=data['Volume'], name="成交量", marker_color=v_colors), row=2, col=1)
        
        fig.add_trace(go.Scatter(x=data.index, y=data['RSI'], name="RSI", line=dict(color='#ff7f0e')), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)
        
        fig.update_layout(xaxis_rangeslider_visible=False, height=800, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        fig.add_trace(go.Scatter(x=data.index, y=data['MACD'], name="MACD", line=dict(color='white')), row=4, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data['Signal'], name="Signal", line=dict(color='orange')), row=4, col=1)

        h_colors = ['red' if val >= 0 else 'green' for val in data['Hist']]
        fig.add_trace(go.Bar(x=data.index, y=data['Hist'], name="Histogram", marker_color=h_colors), row=4, col=1)

        # --- 7. AI 診斷 (美化版) ---
        st.write("---")
        st.subheader("💡 小鐵專屬：AI 投資策略診斷")
        
        curr_rsi = data['RSI'].iloc[-1] if not data['RSI'].isnull().all() else 50
        curr_macd = data['MACD'].iloc[-1]
        curr_sig = data['Signal'].iloc[-1]
        
        # 建立三欄佈局
        col_a, col_b, col_c = st.columns(3)
        
        is_above_ma20 = price > float(curr['MA20'])
        macd_golden_cross = curr_macd > curr_sig
        
        with col_a:
            st.markdown("### 📈 技術趨勢")
            if is_above_ma20 and macd_golden_cross:
                st.success(f"**強勢多頭確立**\n\n股價穩守月線且動能同步向上，這是一段標準的波段起漲訊號。")
            elif is_above_ma20 and not macd_golden_cross:
                st.warning(f"**高檔震盪警訊**\n\n雖然股價在月線上，但 MACD 已死叉，暗示高位買盤縮手，短線恐轉為橫盤。")
            elif not is_above_ma20 and macd_golden_cross:
                st.info(f"**築底反彈階段**\n\n股價雖在月線下，但動能已先翻紅。這通常是底部轉強的徵兆，可關注月線站回時機。")
            else:
                st.error(f"**空頭排列走勢**\n\n股價跌破月線且動能低迷，目前處於弱勢整理。建議『看多不做多』，耐心等落底。")

        with col_b:
            st.markdown("### 🧠 心理強弱")
            if curr_rsi >= 75:
                st.error(f"**極度貪婪 ({curr_rsi:.1f})**\n\n市場情緒已經沸騰！這時候追價風險極高，資深散戶都在這時減碼，別去接最後一棒。")
            elif curr_rsi <= 25:
                st.success(f"**極度恐慌 ({curr_rsi:.1f})**\n\n別人在恐慌時我們要留意。指標已進入超賣區，隨時可能出現報復性反彈。")
            elif 45 <= curr_rsi <= 55:
                st.info(f"**多空平手 ({curr_rsi:.1f})**\n\n市場正在觀望。RSI 盤旋於中軸，代表買賣雙方都在等下一個利多或利空訊息。")
            else:
                st.write(f"**運行區間 ({curr_rsi:.1f})**\n\n目前情緒穩定。股價隨波逐流，適合依照原有的支撐壓力線進行操作。")

        with col_c:
            st.markdown("### 🚀 動能雷達")
            # 加入對 Hist (柱狀圖) 的判斷會更像真人
            curr_hist = data['Hist'].iloc[-1]
            prev_hist = data['Hist'].iloc[-2]
            
            if curr_macd > curr_sig and curr_hist > prev_hist:
                st.success(f"**攻擊火力全開**\n\nMACD 金叉且紅柱持續增長，代表主升段的衝刺力道非常強勁。")
            elif curr_macd > curr_sig and curr_hist <= prev_hist:
                st.warning(f"**多頭力道衰竭**\n\n雖然還是金叉，但紅柱已經縮短。這叫『底背離』或漲勢趨緩，小心獲利回吐。")
            elif curr_macd < curr_sig and curr_hist < prev_hist:
                st.error(f"**跌勢正在加速**\n\n死叉加上綠柱延伸，這是最危險的『向下俯衝』，千萬不要隨意進去攤平。")
            else:
                st.info(f"**空方縮手中**\n\n雖然是死叉，但綠柱開始縮短。代表最壞的情況可能快過去了，可以開始鎖定觀察。")

        # --- 8. 綜合總結建議 ---
        st.write("---")
        
        curr_atr = data['ATR'].iloc[-1]
        atr_stop = data['ATR_Trailing'].iloc[-1]

        # 計算綜合得分
        score = 0
        # 1. 技術面 (MA20) - 趨勢是王道，給 2 分
        if price > float(curr['MA20']): score += 2
        else: score -= 2
        
        # 2. RSI (強弱) - 維持原樣
        if curr_rsi <= 30: score += 1
        elif curr_rsi >= 70: score -= 1
        
        # 3. MACD (動能) - 維持原樣
        if curr_macd > curr_sig: score += 1
        else: score -= 1

        total_net = f_net + d_net

        # 4. 籌碼 (法人) - 土洋同買是強訊號，維持 +2
        if f_net > 0 and d_net > 0:
            score += 2
        elif total_net > 0:
            score += 1
        elif total_net < 0:
            score -= 1

        # 5. ATR (風險) - 守住支撐也給分，增加分數寬度
        if price < atr_stop:
            score -= 2 # 破位是大風險，扣重一點
        else:
            score += 1 # 守住支撐加 1 分

        # 4. 籌碼得分 
        chip_status = "中性觀望"
        chip_color = "#FFFFFF"
        
        if f_net > 0 and d_net > 0:
            score += 2  # 法人土洋同買，大加分
            chip_status = "🔥 土洋同買 (極佳)"
            chip_color = "#FF4B4B"
        elif total_net > 0:
            score += 1  # 合計買超
            chip_status = "✅ 法人偏多"
            chip_color = "#FF4B4B"
        elif total_net < 0:
            score -= 1  # 合計賣超
            chip_status = "❌ 法人撤出"
            chip_color = "#00B050"

        # ATR 止損判斷 (若收盤價跌破 ATR 止損線，強制扣分)
        if price < atr_stop:
            score -= 1
            atr_status = "⚠️ 已跌破 ATR 止損位，風險極高！"
            atr_color = "#00B050"
        else:
            atr_status = "✅ 位於 ATR 支撐上方，波動尚在安全範圍。"
            atr_color = "#FF4B4B"

        # 根據得分決定建議
        if score >= 4:
            rec_text, rec_color = "🔥 極度看多 / 強力進攻", "#FF4B4B"
            rec_desc = "現在是罕見的『黃金共振』狀態！技術、動能與法人錢包同步翻紅，適合勇敢參與大行情。"
        elif score == 3:
            rec_text, rec_color = "📈 趨勢確立 / 穩定加碼", "#FF4B4B"
            rec_desc = "多頭部隊佔領高地，籌碼結構穩健。雖然小有波動，但主趨勢依然向上，順勢而為是明智之舉。"
        elif score == 2:
            rec_text, rec_color = "🔎 偏多觀察 / 尋找買點", "#FF4B4B"
            rec_desc = "指標開始轉暖，但法人可能還在猶豫。這時候不宜追高，建議在支撐位附近小量試單。"
        elif score == 1:
            rec_text, rec_color = "⚖️ 多空拉鋸 / 謹慎試探", "#FFCC00" # 黃色
            rec_desc = "目前正處於方向選擇期，雖然有一點多頭味道，但力道不足。建議控制好倉位，別把子彈一次打完。"
        elif score == 0:
            rec_text, rec_color = "💤 靜待轉機 / 觀望為宜", "#FFFFFF"
            rec_desc = "盤勢就像一灘死水，或是多空力道剛好抵銷。這時候『不動如山』就是最好的策略，把體力留給未來的突破。"
        elif score == -1:
            rec_text, rec_color = "📉 弱勢整理 / 縮減部位", "#00B050"
            rec_desc = "技術面已經出現裂痕，且法人開始有撤退跡象。不要對虧損有感情，適度減碼才能保持心理彈性。"
        elif score <= -2:
            rec_text, rec_color = "🚨 風險警示 / 嚴防急跌", "#00B050"
            rec_desc = "大勢已去，目前正處於空頭控制區。強烈建議空手觀望，保護好你的本金，落底訊號出現前別急著接刀。"

        # 新增一個「人性化叮嚀」標籤
        if price < atr_stop and score > 0:
            rec_desc = "⚠️ 注意！雖然指標偏多，但股價已破 ATR 防線，這可能是『假突破』，請務必嚴守停損！"
        elif f_net > 500 and price < float(curr['MA20']):
            rec_desc = "🧐 發現亮點！外資正在『逆勢接貨』，雖然技術面還沒翻紅，但可以開始關注打底跡象。"

        rec_color = locals().get('rec_color', '#FFFFFF')
        rec_text = locals().get('rec_text', '計算中...')
        rec_desc = locals().get('rec_desc', '正在彙整指標數據...')
        chip_color = locals().get('chip_color', '#FFFFFF')
        chip_status = locals().get('chip_status', '暫無數據')
        atr_color = locals().get('atr_color', '#FFFFFF')
        atr_status = locals().get('atr_status', '監測中')
        score = locals().get('score', 0)

        # 渲染全方位評等卡片
        st.markdown(f"""
    <div style="border-radius: 15px; padding: 20px; border: 2px solid {rec_color}; text-align: center; background-color: rgba(255,255,255,0.05); margin: 20px 0;">
        <h3 style="color: #AAAAAA; margin-bottom: 5px;">🏆 小鐵全方位評等</h3>
        <h1 style="color: {rec_color}; margin-top: 0; font-size: 38px;">{rec_text}</h1>
        <p style="color: #DDDDDD; font-size: 16px;">{rec_desc}</p>
        <div style="display: flex; justify-content: space-around; background-color: rgba(0,0,0,0.2); padding: 15px; border-radius: 10px;">
            <div style="flex: 1;">
                <p style="color: #888888; font-size: 12px; margin: 0;">籌碼走向</p>
                <p style="color: {chip_color}; font-weight: bold; margin: 0;">{chip_status}</p>
            </div>
            <div style="flex: 1; border-left: 1px solid #444; border-right: 1px solid #444;">
                <p style="color: #888888; font-size: 12px; margin: 0;">ATR 防線</p>
                <p style="color: {atr_color}; font-weight: bold; margin: 0;">{atr_status}</p>
            </div>
            <div style="flex: 1;">
                <p style="color: #888888; font-size: 12px; margin: 0;">綜合得分</p>
                <p style="color: #FFFFFF; font-weight: bold; margin: 0;">{score} 分</p>
            </div>
        </div>
    </div>
""", unsafe_allow_html=True)


        # --- 8. 籌碼動向 (單獨一橫條，看起來更清楚) ---
        st.write("") 
        with st.expander("🔍 查看詳細籌碼與數據細節", expanded=False):
             # 這裡可以放入之前的籌碼數據與數據日期
             st.write(f"當前 DIF: `{curr_macd:.2f}` | Signal: `{curr_sig:.2f}`")

        # --- 5. 獲利試算區 ---
        if ticker_input in active_costs:
            st.write("---")
            stock_info = active_costs[ticker_input]
            c = stock_info['cost'] if isinstance(stock_info, dict) else stock_info
            q = stock_info['qty'] if isinstance(stock_info, dict) else 1.0
            if c > 0:
                total_cost = c * q * 1000
                current_val = price * q * 1000
                profit = current_val - total_cost
                profit_rate = (profit / total_cost) * 100 if total_cost > 0 else 0
                
                st.subheader(f"💰 投資損益試算 (分類: {current_group})")
                # 獲利紅色，虧損綠色，平盤白色
                p_color = "#FF4B4B" if profit > 0 else ("#00B050" if profit < 0 else "#FFFFFF")
                
                i1, i2, i3 = st.columns(3)
                
                # 1. 預估損益 (自訂 HTML)
                with i1:
                    st.markdown(f"""
                        <div style="text-align: left;">
                            <p style="color: gray; font-size: 16px; margin-bottom: 0px;">預估損益 (報酬率)</p>
                            <p style="color: {p_color}; font-size: 30px; font-weight: bold; margin-top: -5px;">
                                {int(profit):,} <span style="font-size: 18px;">({profit_rate:.2f}%)</span>
                            </p>
                        </div>
                    """, unsafe_allow_html=True)
                i2.metric("投入本金", f"{int(total_cost):,}")
                i3.metric("目前市值", f"{int(current_val):,}")


# --- 9. 新聞區 ---
if show_news and ticker_input:
    st.write("---")
    st.subheader("📰 台灣產經新聞")
    try:
        # 抓取近 5 天新聞
        df_news = dl.taiwan_stock_news(
            stock_id=ticker_input.split('.')[0], 
            start_date=(datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
        )
        
        if not df_news.empty:
            # --- 核心優化：去重 ---
            # 1. 根據標題去重，保留最新的一則
            df_news = df_news.drop_duplicates(subset=['title'], keep='first')
            
            # 2. 確保按日期排序（最新的在前）
            if 'date' in df_news.columns:
                df_news = df_news.sort_values(by='date', ascending=False)

            # 3. 只取前 8 則不一樣的新聞，避免洗版
            display_news = df_news.head(8)

            for _, row in display_news.iterrows():
                # 在標題加上時間戳，更人性化
                pub_date = row['date'].split(' ')[0] if 'date' in row else ""
                expander_label = f"[{pub_date}] {row['title']}"
                
                with st.expander(expander_label):
                    st.write(row.get('summary', '無摘要內容'))
                    if row.get('link'): 
                        st.markdown(f"🔗 [點擊查看原文網址]({row['link']})")
        else:
            st.info("⚠️ 近期暫無相關產經新聞。")
    except Exception as e:
        st.warning(f"新聞抓取暫時異常，請稍後再試。")
