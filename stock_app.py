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
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
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
    # 建立 Ticker 物件
    ticker_obj = yf.Ticker(ticker_input)
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

        # --- 專業估值診斷區 ---
        st.write("---")
        st.subheader("⚖️ 專業價值診斷 (歷史本益比法)")

        try:
            info = ticker_obj.info
            current_price = info.get('currentPrice') or price
            eps = info.get('trailingEps') # 過去四季累積 EPS
            
            if eps and eps > 0:
                # 取得歷史價格資料來計算本益比區間 (過去一年)
                hist_1y = ticker_obj.history(period="1y")
                hist_pe = hist_1y['Close'] / eps
                
                avg_pe = hist_pe.mean()
                max_pe = hist_pe.max()
                min_pe = hist_pe.min()
                current_pe = current_price / eps
                
                cheap_price = eps * (avg_pe * 0.85)
                fair_price = eps * avg_pe
                expensive_price = eps * (avg_pe * 1.15)
                
                c1, c2, c3 = st.columns(3)
                c1.metric("便宜價", f"{cheap_price:.2f}")
                c2.metric("合理價", f"{fair_price:.2f}")
                c3.metric("昂貴價", f"{expensive_price:.2f}")
                
                st.write(f"目前股價: **{current_price}** | 目前本益比: **{current_pe:.2f}**")
                
                if current_price <= cheap_price:
                    st.success("🎯 **診斷結果：股價處於【便宜】位階。**")
                elif current_price >= expensive_price:
                    st.error("🚩 **診斷結果：股價處於【昂貴】位階。**")
                else:
                    st.warning("⚖️ **診斷結果：股價處於【合理】範圍。**")
                    
                position = (current_price - (min_pe * eps)) / ((max_pe - min_pe) * eps)
                position = max(0, min(position, 1.0))
                st.write("📈 目前股價在年度高低位階：")
                st.progress(position)
                st.caption(f"左側為年度最低 ({min_pe*eps:.1f})，右側為年度最高 ({max_pe*eps:.1f})")
            else:
                st.info("💡 該公司目前虧損或無 EPS 資料，改看股價淨值比 (P/B)。")
                pb = info.get('priceToBook')
                if pb:
                    st.write(f"目前 P/B: **{pb:.2f}**")
                    if pb < 1.0: st.success("📉 股價低於淨值。")
        except Exception as e:
            st.info(f"估值數據暫時無法取得。")

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
        fig.add_hline(y=high_60d, line_dash="dot", line_color="yellow", annotation_text="前高壓力", row=1, col=1)

        colors = ['red' if row['Close'] >= row['Open'] else 'green' for _, row in data.iterrows()]
        fig.add_trace(go.Bar(x=data.index, y=data['Volume'], name="成交量", marker_color=colors, opacity=0.7), row=2, col=1)
        fig.update_layout(xaxis_rangeslider_visible=False, height=600, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        # --- 6. 三大法人籌碼 ---
        st.write("---")
        st.subheader("👥 昨日三大法人買賣數據 (張)")
        f_net = 0 # 預設值
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
        except:
            st.error("籌碼抓取失敗")

        # --- 7. AI 投資策略建議 ---
        st.write("---")
        st.subheader("💡 小鐵專屬：AI 投資策略診斷")
        sma5 = float(curr['MA5'])
        dist_to_ma5 = ((price - sma5) / sma5) * 100
        col_a, col_b = st.columns(2)
        with col_a:
            st.write("**📈 技術面診斷：**")
            if abs(dist_to_ma5) < 0.5:
                st.success(f"目前股價貼近 5 日線，正在測試支撐。")
            elif price < float(curr['MA20']):
                st.error("股價低於月線，屬於弱勢格局。")
            elif dist_to_ma5 > 3:
                st.warning(f"乖離率過高 ({dist_to_ma5:.2f}%)，不建議追高。")
            else:
                st.info("指標平穩，多頭排列中。")
        with col_b:
            st.write("**👥 籌碼面動向：**")
            if f_net > 500:
                st.success(f"外資進貨 {int(f_net)} 張，籌碼有撐。")
            elif f_net < -1000:
                st.error(f"外資大賣 {int(abs(f_net))} 張，壓力沉重。")
            else:
                st.warning("法人買賣力道不強。")

        # --- 最終操盤建議 ---
        st.write("---")
        if price > float(curr['MA5']) and price > float(curr['MA20']):
            summary_text = "🚀 強勢多頭：建議【續抱】或【回測 5MA 加碼】。"
            border_style = "5px solid #FF4B4B"
            txt_color = "#FF4B4B"
        elif price < float(curr['MA60']):
            summary_text = "⚠️ 弱勢格局：建議【空手觀望】或【嚴格停損】。"
            border_style = "5px solid #21C354"
            txt_color = "#21C354"
        else:
            summary_text = "⚖️ 震盪盤整：建議【低買高賣小波段】操作。"
            border_style = "5px solid #007BFF"
            txt_color = "#007BFF"

        st.markdown(f'<div style="background-color: #1E1E1E; padding: 25px; border-radius: 15px; border: {border_style}; text-align: center;"><h2 style="color: {txt_color};">{summary_text}</h2></div>', unsafe_allow_html=True)

        # --- 9. 賣出與風險控管 ---
        st.write("---")
        st.subheader("🚩 賣出建議與風險控管")
        if ticker_input in my_costs:
            p_l_ratio = ((price - cost) / cost) * 100
            st.write(f"**💰 目前損益：{p_l_ratio:.2f}%**")
            if p_l_ratio >= 15: st.warning("⚠️ 獲利超過 15%，建議先入袋一部分。")
            elif p_l_ratio <= -8: st.error("🚨 虧損達 8%，請考慮停損。")

        # --- 10. 動能強度 ---
        st.write("---")
        st.subheader(f"⚡ {ticker_input} 動能強度偵測")
        avg_vol_5d = data['Volume'].tail(6).iloc[:-1].mean() 
        vol_ratio = curr['Volume'] / avg_vol_5d
        st.metric("成交量倍數", f"{vol_ratio:.2f} x")
        if vol_ratio >= 2.0: st.error("🔥 爆量攻擊訊號！")
        elif vol_ratio <= 0.5: st.info("😴 目前人氣渙散。")

# --- 新聞區 (放在最下方) ---
if show_news and ticker_input:
    st.write("---")
    st.subheader("📰 台灣產經新聞")
    try:
        df_news = dl.taiwan_stock_news(stock_id=ticker_input.split('.')[0], 
                                     start_date=(datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'))
        if not df_news.empty:
            df_news['clean_title'] = df_news['title'].apply(lambda x: x.split(' - ')[0].strip())
            df_news = df_news.drop_duplicates(subset=['clean_title'], keep='first').sort_values(by='date', ascending=False)
            for _, row in df_news.head(8).iterrows():
                with st.expander(f"📌 {row['date']} | {row['clean_title']}"):
                    st.write(row.get('summary', ''))
                    link = row.get('link')
                    if link and str(link) != 'nan':
                        st.markdown(f'[📖 閱讀原文]({link})')
                    else:
                        st.markdown(f"[🔍 Google 搜尋](https://www.google.com/search?q={row['clean_title']})")
    except Exception as e:
        st.error(f"新聞抓取失敗: {e}")