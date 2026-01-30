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

def load_costs():
    """載入成本資料庫"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"2356.TW": 49.0, "0050.TW": 185.0}

def save_costs(costs):
    """儲存成本至資料庫"""
    with open(DB_FILE, "w") as f:
        json.dump(costs, f)

# 初始化載入
my_costs = load_costs()

# --- 1. 配置 FinMind ---
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNi0wMS0yOCAwODoyNToyNyIsInVzZXJfaWQiOiJ0ZWRkeWphY2siLCJlbWFpbCI6InRlZGR5amFjazVAeWFob28uY29tLnR3IiwiaXAiOiI0Mi43Mi4yMTEuMTUzIn0.Su4W8X5E9XPN9PZdA03Z6XO6i630kOSvOjcrLowcO-I"
dl = DataLoader()
try:
    dl.set_token(token=FINMIND_TOKEN)
except:
    pass

st.set_page_config(page_title="小鐵的股票分析報告", layout="wide")
st.title("📈 小鐵的股票分析報告") 

# --- 2. 側邊欄：導航與設定 ---
st.sidebar.title("🛠️ 小鐵的導航面板")

my_stocks = {
    "2356.TW": "英業達",
    "2618.TW": "長榮航",
    "2609.TW": "陽明",
    "2352.TW": "佳世達",
    "2002.TW": "中鋼",
    "2646.TW": "星宇航空",
    "0050.TW": "元大台灣50"
}

selected_ticker = st.sidebar.selectbox("選取庫存", list(my_stocks.keys()))
custom_ticker = st.sidebar.text_input("或手動輸入 (例: 2330.TW)", "")
ticker_input = custom_ticker if custom_ticker else selected_ticker

period = st.sidebar.selectbox("分析時間範圍", ["5d", "1mo", "6mo", "1y", "2y"], index=2)

# --- 成本管理區 ---
st.sidebar.markdown("---")
st.sidebar.subheader("💰 成本管理")
initial_cost = my_costs.get(ticker_input, 0.0)
cost = st.sidebar.number_input(f"{ticker_input} 買入成本", value=float(initial_cost), step=0.1)

if st.sidebar.button("💾 永久儲存修改"):
    my_costs[ticker_input] = cost
    save_costs(my_costs)
    st.sidebar.success(f"已更新 {ticker_input} 成本！")

show_news = st.sidebar.checkbox("顯示相關新聞", value=True)

# --- 3. 下載與處理資料 ---
if ticker_input:
    data = yf.download(ticker_input, period=period)
    
    if not data.empty:
        # 處理 yfinance 多重索引問題
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # 計算技術指標
        data['MA5'] = data['Close'].rolling(window=5).mean()
        data['MA20'] = data['Close'].rolling(window=20).mean()
        data['MA60'] = data['Close'].rolling(window=60).mean()

        # 取得最新一筆與前一筆數據
        curr = data.iloc[-1]
        prev = data.iloc[-2]
        price = float(curr['Close'])
        volume_sheets = int(curr['Volume'] / 1000)
        
        # 前波高點計算 (60日)
        high_60d = float(data['High'].tail(60).max())
        dist_to_high = ((high_60d - price) / high_60d) * 100

        # --- 4. 指標儀表板 ---
        st.subheader(f"📊 {ticker_input} 即時概況")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("當前股價", f"{price:.2f}", f"{price - float(prev['Close']):.2f}")
        m2.metric("前波高點", f"{high_60d:.2f}")
        m3.metric("挑戰進度", f"{100 - dist_to_high:.1f}%")
        m4.metric("5日均線", f"{float(curr['MA5']):.2f}")
        m5.metric("20日(月線)", f"{float(curr['MA20']):.2f}")
        m6.metric("60日(季線)", f"{float(curr['MA60']):.2f}")

        # --- 5. 繪製 K 線圖 ---
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, 
            subplot_titles=(f'{ticker_input} K線與均線', '成交量'), 
            row_width=[0.3, 0.7]
        )
        fig.add_trace(go.Candlestick(
            x=data.index, open=data['Open'], high=data['High'],
            low=data['Low'], close=data['Close'], name="K線"
        ), row=1, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data['MA5'], line=dict(color='#17becf', width=1.5), name="5MA"), row=1, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data['MA20'], line=dict(color='#ff7f0e', width=2), name="20MA"), row=1, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data['MA60'], line=dict(color='#9467bd', width=2), name="60MA"), row=1, col=1)
        fig.add_hline(y=high_60d, line_dash="dot", line_color="yellow", annotation_text=f"前高壓力", row=1, col=1)

        # 成交量柱狀圖顏色判斷
        colors = ['red' if row['Close'] >= row['Open'] else 'green' for _, row in data.iterrows()]
        fig.add_trace(go.Bar(x=data.index, y=data['Volume'], name="成交量", marker_color=colors, opacity=0.7), row=2, col=1)
        fig.update_layout(xaxis_rangeslider_visible=False, height=600, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        # --- 6. 三大法人籌碼 ---
        st.write("---")
        st.subheader("👥 昨日三大法人買賣數據 (張)")
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
                c1, c2, c3 = st.columns(3)
                c1.metric("外資", f"{int(f_net):,} 張")
                c2.metric("投信", f"{int(d_net):,} 張")
                c3.metric("自營商", f"{int(s_net):,} 張")
                st.caption(f"數據更新日期：{last_day}")
            else:
                f_net = 0 # 避免後面 AI 診斷報錯
                st.warning("⚠️ 暫無法人數據")
        except:
            f_net = 0
            st.error("籌碼抓取失敗")

        # --- 7. AI 投資策略建議 ---
        st.write("---")
        st.subheader("💡 小鐵專屬：AI 投資策略診斷")
        
        # 計算距離 5 日線的乖離率
        sma5 = float(curr['MA5'])
        dist_to_ma5 = ((price - sma5) / sma5) * 100
        
        # 判斷邏輯
        col_a, col_b = st.columns(2)
        
        with col_a:
            st.write("**📈 技術面診斷：**")
            if abs(dist_to_ma5) < 0.5:
                st.success(f"目前股價正貼近 5 日線 ({sma5:.2f})，正在測試支撐。若能守住不破，是短線強勢表現。")
            elif price < float(curr['MA20']):
                st.error("股價目前低於月線，屬於弱勢格局，操作上需保守，先看季線支撐。")
            elif dist_to_ma5 > 3:
                st.warning(f"乖離率稍高 ({dist_to_ma5:.2f}%)，短線可能會有回測 5 日線的壓力，建議不要追高。")
            else:
                st.info("目前技術指標平穩，處於多頭排列中。")

        with col_b:
            st.write("**👥 籌碼面動向：**")
            # 這裡引用剛才計算的 f_net (外資買賣超)
            try:
                if f_net > 500:
                    st.success(f"外資昨日進貨 {int(f_net)} 張，籌碼面有撐，有利於止跌反彈。")
                elif f_net < -1000:
                    st.error(f"外資昨日大賣 {int(abs(f_net))} 張，上方壓力沉重，加碼建議再等等。")
                else:
                    st.warning("法人買賣力道不強，目前屬於內資與散戶盤，波動會較隨機。")
            except:
                st.write("暫無最新籌碼數據，請於 15:00 後重新整理。")

        # --- 綜合結論：醒目戰情室版 ---
        st.write("---")
        st.subheader("🚩 最終操盤建議")
        
        # 根據邏輯判斷顏色與圖示
        if price > float(curr['MA5']) and price > float(curr['MA20']):
            # 多頭強勢
            bg_color = "#FF4B4B" # 強勢紅
            summary_text = "🚀 強勢多頭：目前股價站穩所有均線，建議【續抱】或【回測 5MA 小量加碼】。"
            border_style = "5px solid #FF4B4B"
        elif price < float(curr['MA60']):
            # 弱勢空頭
            bg_color = "#21C354" # 警示綠 (跌)
            summary_text = "⚠️ 弱勢格局：股價跌破季線，建議【空手觀望】或【嚴格執行停損】，勿輕易接刀。"
            border_style = "5px solid #21C354"
        else:
            # 盤整期
            bg_color = "#007BFF" # 中性藍
            summary_text = "⚖️ 震盪盤整：股價於均線間糾結，建議【靜待帶量突破】或【低買高賣小波段】操作。"
            border_style = "5px solid #007BFF"

        # 使用 HTML 語法來達成極致醒目的效果
        st.markdown(f"""
            <div style="
                background-color: #1E1E1E; 
                padding: 25px; 
                border-radius: 15px; 
                border: {border_style};
                text-align: center;
            ">
                <h2 style="color: {bg_color}; margin: 0; font-size: 30px;">{summary_text}</h2>
            </div>
        """, unsafe_allow_html=True)

        st.write("") # 留白

        # --- 8. 最終操盤建議 (醒目版) ---
        st.write("---")
        st.subheader(f"🎯 {ticker_input} 買入風險評估")
        
        # 抓取均線數值
        curr_price = float(curr['Close'])
        ma5 = float(curr['MA5'])
        ma20 = float(curr['MA20'])
        
        # 計算乖離率
        gap_ma5 = ((curr_price - ma5) / ma5) * 100
        gap_ma20 = ((curr_price - ma20) / ma20) * 100
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**⚠️ 風險警示：**")
            if gap_ma5 > 5:
                st.error(f"【過熱】目前股價高於 5 日線 {gap_ma5:.1f}%。現在進場容易遇到短線回測，建議先冷靜。")
            elif gap_ma5 < -5:
                st.warning(f"【超跌】目前股價低於 5 日線 {abs(gap_ma5):.1f}%。雖然在跌，但可能會有跌深反彈。")
            else:
                st.success("【穩定】目前股價與 5 日線距離適中，波動在正常範圍。")

        with col2:
            st.write("**💰 建議買入區間：**")
            # 策略：最佳買點通常在 5 日線與月線之間
            safe_low = ma20 * 1.01 # 月線上方 1%
            safe_high = ma5 * 1.02 # 5 日線上方 2%
            
            if curr_price > safe_high:
                st.write(f"📢 建議等股價回落至 **{safe_low:.2f} ~ {ma5:.2f}** 區間再考慮分批佈局。")
            else:
                st.write(f"📢 目前價位接近支撐區，若看好長線，可在 **{curr_price:.2f}** 附近分批建立基本持股。")

        st.info(f"💡 註：此建議是基於技術面乖離率計算，仍須配合『昨日三大法人數據』確認是否有大戶在出貨。")

        # --- 9. 賣出建議與風險控管 ---
        st.write("---")
st.subheader("🚩 賣出建議與風險控管")

# A. 設定個人停損停利點 (從側邊欄或預設讀取)
# 假設你的成本已經存在 my_costs 字典中
if ticker_input in my_costs:
    cost = my_costs[ticker_input]
    p_l_ratio = ((price - cost) / cost) * 100
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.write(f"**💰 成本：{cost}**")
        # 設定固定停利 (+20%) 與 停損 (-10%) 參考
        st.write(f"👉 建議停利點 (+20%): **{cost * 1.2:.2f}**")
        st.write(f"👉 建議停損點 (-10%): **{cost * 0.9:.2f}**")

    with col_s2:
        if p_l_ratio >= 15:
            st.warning("⚠️ 【獲利提醒】目前獲利已超過 15%，建議可先賣出 1/3 獲利了結，落袋為安。")
        elif p_l_ratio <= -8:
            st.error("🚨 【止損警示】虧損已達 8% 以上，請嚴格執行紀律，評估是否汰弱留強。")
        else:
            st.info("✅ 【部位持有】目前損益尚在波動範圍內，建議依均線支撐操作。")

# B. 技術面自動賣出訊號偵測
st.markdown("#### 📉 自動化賣出指標")
sell_signals = []

# 1. 跌破 20MA (月線)
if price < float(curr['MA20']):
    sell_signals.append("股價已跌破 **20日月線**，中期趨勢轉弱。")

# 2. 乖離率過高 (針對 0050 等噴發股)
ma5 = float(curr['MA5'])
bias_5 = ((price - ma5) / ma5) * 100
if bias_5 > 5:
    sell_signals.append(f"短線正乖離過大 (**{bias_5:.1f}%**)，小心過熱回檔，切勿追高。")

# 3. 前高壓力偵測
if abs(price - high_60d) / high_60d < 0.02 and price < high_60d:
    sell_signals.append(f"股價接近 **前波高點 ({high_60d:.2f})**，若無量突破可能遭遇解套賣壓。")

if sell_signals:
    for s in sell_signals:
        st.markdown(f"📍 {s}")
else:
        st.success("✨ 目前暫無明顯技術性賣出訊號，趨勢維持良好。")

        # --- 10. 動能強度 (成交量分析) ---
        st.write("---")
        st.subheader(f"⚡ {ticker_input} 動能強度偵測")
        
        # 計算過去 5 天的平均成交量
        avg_volume_5d = data['Volume'].tail(6).iloc[:-1].mean() 
        curr_volume = data['Volume'].iloc[-1]
        vol_ratio = curr_volume / avg_volume_5d
        
        c_vol1, c_vol2 = st.columns([1, 2])
        
        with c_vol1:
            st.metric("成交量倍數", f"{vol_ratio:.2f} x", delta=f"{vol_ratio-1:.2f}x", delta_color="normal")
            
        with c_vol2:
            if vol_ratio >= 2.0:
                st.error(f"🔥 【爆量警告】成交量是均量的 {vol_ratio:.1f} 倍！這通常是攻擊訊號或高檔換手，請密切注意股價是否站穩開盤價。")
            elif vol_ratio >= 1.5:
                st.warning(f"🚀 【帶量轉強】成交量明顯放大，動能正在集結，有機會突破整理區。")
            elif vol_ratio <= 0.5:
                st.info(f"😴 【極度量縮】成交量不到均量的一半，目前人氣渙散，處於盤整或打底階段。")
            else:
                st.success(f"✅ 【量能平穩】成交量維持常態，走勢依循技術面運行。")

        # 結合「價」與「量」的最終判斷
        if vol_ratio > 1.5 and price > float(curr['MA5']):
            st.markdown("### 🌟 戰略結論：**量價齊揚**，短線攻擊欲望強烈，適合順勢操作！")
        elif vol_ratio < 0.6 and price < float(curr['MA20']):
            st.markdown("### 🌟 戰略結論：**量縮下跌**，雖然低迷但賣壓正在減輕，建議等待止跌訊號。")
        
        # 新聞區
if show_news:
    st.write("---")
    st.subheader("📰 相關新聞")
    ticker_obj = yf.Ticker(ticker_input)
    news_list = ticker_obj.news
    
    # --- 聰明連結偵測版新聞區 ---
if news_list:
    for item in news_list[:5]:
        title = item.get('title') or "查看新聞詳情"
        
        # 1. 多重欄位偵測：Yahoo 有時用 link，有時用 url
        link = item.get('link') or item.get('url') 
        
        publisher = item.get('publisher', '財經媒體')
        
        with st.expander(title):
            if link:
                # 2. 自動補齊網域
                if not link.startswith('http'):
                    link = f"https://finance.yahoo.com{link}"
                
                # 3. 顯示按鈕樣式的連結，更直覺
                st.markdown(
                    f"""<a href="{link}" target="_blank">
                        <button style="
                            background-color: #ff4b4b; 
                            color: white; 
                            border: none; 
                            padding: 10px 20px; 
                            border-radius: 5px; 
                            cursor: pointer;
                            font-weight: bold;
                        ">🔗 點此閱讀新聞全文 ({publisher})</button>
                    </a>""", 
                    unsafe_allow_html=True
                )
            else:
                # 4. 如果真的沒連結，顯示原始資料內容供開發參考 (Debug 用)
                st.write("⚠️ 此則新聞來源未提供直接連結")
                # st.write(item) # 如果你想看原始資料長怎樣，可以把這行註解拿掉