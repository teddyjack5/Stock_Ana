import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd
import json
import os
import hashlib
import requests
from datetime import datetime, timedelta
from FinMind.data import DataLoader
from plotly.subplots import make_subplots
from streamlit_gsheets import GSheetsConnection

# ==============================================================================
# 第一部分：【雲端基礎設施】 - 處理 Google Sheets 連線與資料存取
# ==============================================================================
SCRIPT_URL = st.secrets["GOOGLE_SCRIPT_URL"]

def load_db_from_sheets():
    """透過 Apps Script 網址讀取 JSON 格式的整包雲端數據 (庫存+帳務+密碼)"""
    try:
        response = requests.get(SCRIPT_URL, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        st.error(f"雲端讀取失敗，請檢查 Apps Script 網址: {e}")
    return {"password_hash": None, "list": {}, "costs": {}}

def save_db_to_sheets(db):
    """將目前的 session_state 數據發送到雲端 Apps Script 進行儲存"""
    try:
        response = requests.post(SCRIPT_URL, json=db, timeout=15)
        if "Success" in response.text:
            return True
        else:
            st.error(f"存檔回傳異常: {response.text}")
    except Exception as e:
        st.error(f"雲端存檔連線失敗: {e}")
    return False

# 初始化 Session State (確保程式啟動時先從雲端抓資料)
if 'db' not in st.session_state:
    st.session_state.db = load_db_from_sheets()

def hash_password(password):
    """安全機制：將明文密碼轉換為 SHA-256 雜湊碼儲存"""
    if not password:
        return None
    return hashlib.sha256(password.encode()).hexdigest()

# ==============================================================================
# 第二部分：【互動對話視窗 (Dialogs)】 - UI 彈窗功能定義
# ==============================================================================

# 1. 顯示全帳戶損益明細
@st.dialog("📋 全帳戶個股損益明細", width="large")
def show_full_portfolio_report(active_costs, active_list):
    if not active_costs:
        st.warning("目前庫存中沒有帳務資料。")
        return

    report_data = []
    with st.spinner("正在獲取最新報價..."):
        for t_code, info in active_costs.items():
            try:
                tick = yf.Ticker(t_code)
                df_recent = tick.history(period="1d")
                if df_recent.empty: continue
                
                c_price = df_recent['Close'].iloc[-1]
                name = active_list.get(t_code, "未知")
                cost = info['cost']
                qty = info['qty']
                
                total_cost = cost * qty * 1000
                market_value = c_price * qty * 1000
                diff = market_value - total_cost
                roi = (diff / total_cost * 100) if total_cost > 0 else 0
                
                report_data.append({
                    "代號": t_code, "名稱": name, "成本價": f"{cost:.2f}",
                    "現價": f"{c_price:.2f}", "張數": qty,
                    "投入本金": int(total_cost), "目前市值": int(market_value),
                    "損益": int(diff), "報酬率": f"{roi:.2f}%"
                })
            except: continue

    if report_data:
        df_report = pd.DataFrame(report_data)
        st.dataframe(
            df_report.style.applymap(lambda v: f'color: {"red" if v > 0 else "green" if v < 0 else "white"}', subset=['損益']),
            use_container_width=True, hide_index=True
        )
        total_p = sum(d['損益'] for d in report_data)
        st.divider()
        st.metric("合計預估總損益", f"NT$ {total_p:,}", delta=f"{total_p:,}")

# 2. 新增庫存股票
@st.dialog("➕ 新增股票至清單")
def add_stock_dialog():
    new_ticker = st.text_input("股票代號 (例如: 2330.TW)", placeholder="2330.TW")
    new_name = st.text_input("股票名稱", placeholder="台積電")
    
    if st.button("確認新增"):
        if new_ticker and new_name:
            st.session_state.db["list"][new_ticker] = new_name
            st.session_state.db["costs"][new_ticker] = {"cost": 0.0, "qty": 0.0}
            
            success = save_db_to_sheets(st.session_state.db)
            if success:
                st.success(f"已成功新增 {new_name} ({new_ticker}) 並同步至雲端！")
                st.rerun()
            else:
                st.error("同步至雲端失敗，請檢查連線。")
        else:
            st.error("請填寫完整的代號與名稱")

# 3. 刪除庫存股票
@st.dialog("⚠️ 刪除確認")
def delete_confirm_dialog(ticker, name):
    st.warning(f"確定要從庫存中刪除 **{name} ({ticker})** 嗎？")
    st.write("此操作將同時移除該股的買入成本與數量紀錄。")
    
    c1, c2 = st.columns(2)
    if c1.button("取消", use_container_width=True): st.rerun()
        
    if c2.button("確認刪除", type="primary", use_container_width=True):
        st.session_state.db["list"].pop(ticker, None)
        st.session_state.db["costs"].pop(ticker, None)
        success = save_db_to_sheets(st.session_state.db)
        if success:
            st.session_state.selected_ticker = None
            st.session_state.temp_ticker = None
            st.success(f"已從雲端刪除 {name}")
            st.rerun()
        else:
            st.error("雲端刪除失敗，請檢查連線。")

# 4. 紀錄賣出獲利 (已實現損益)
@st.dialog("💰 紀錄已實現獲利")
def record_sale_dialog():
    """手動紀錄賣出獲利的對話框"""
    date = st.date_input("賣出日期", datetime.now())
    col_a, col_b = st.columns(2)
    manual_id = col_a.text_input("股票代號", placeholder="例如: 2330")
    manual_name = col_b.text_input("股票名稱", placeholder="例如: 台積電")
    
    col1, col2 = st.columns(2)
    profit_amt = col1.number_input("獲利金額", value=0, step=1000)
    profit_pct = col2.number_input("獲利百分比", value=0.0, step=0.1, format="%.2f")
    
    st.write("---")
    if st.button("確認存入帳本並同步雲端", type="primary", use_container_width=True):
        if manual_id and manual_name:
            formatted_id = manual_id.upper()
            if "." not in formatted_id: formatted_id = f"{formatted_id}.TW"
            record = {
                "日期": str(date), "代號": formatted_id, "名稱": manual_name,
                "獲利": profit_amt, "百分比": profit_pct
            }
            st.session_state.db.setdefault("realized_pnl", []).append(record)
            success = save_db_to_sheets(st.session_state.db)
            if success:
                st.success(f"✅ 已紀錄 {manual_name} 的獲利並同步至雲端！")
                st.rerun()
            else:
                st.error("❌ 雲端同步失敗，請檢查 Apps Script 設定。")
        else:
            st.error("請填寫股票代號與名稱")

# 5. 年度獲利報表 (時區校準版)
@st.dialog("🗓️ 年度獲利結算報表", width="large")
def show_annual_report_dialog():
    pnl_data = st.session_state.db.get("realized_pnl", [])
    if not pnl_data:
        st.info("目前尚無賣出紀錄。")
        return

    df_pnl = pd.DataFrame(pnl_data)
    try:
        df_pnl['日期'] = pd.to_datetime(df_pnl['日期'], utc=True).dt.tz_convert('Asia/Taipei')
        df_pnl['年份'] = df_pnl['日期'].dt.year
        df_pnl['日期'] = df_pnl['日期'].dt.date
    except:
        df_pnl['日期'] = pd.to_datetime(df_pnl['日期']) + pd.Timedelta(hours=8)
        df_pnl['年份'] = df_pnl['日期'].dt.year
        df_pnl['日期'] = df_pnl['日期'].dt.date
    
    summary = df_pnl.groupby('年份').agg({'獲利': 'sum', '日期': 'count'}).rename(columns={'日期': '交易筆數', '獲利': '年度總損益'}).sort_index(ascending=False)

    def color_pnl(val):
        if isinstance(val, (int, float)):
            if val > 0: return 'color: #FF4B4B'
            if val < 0: return 'color: #00B050'
        return 'color: white'

    st.subheader("📊 年度數據摘要")
    st.table(summary.style.format({"年度總損益": "NT$ {:,.0f}"}).applymap(color_pnl, subset=['年度總損益']))
    st.divider()
    st.subheader("📑 詳細交易紀錄")
    years = sorted(df_pnl['年份'].unique(), reverse=True)
    for y in years:
        with st.expander(f"📅 {y} 年詳細清單"):
            year_df = df_pnl[df_pnl['年份'] == y].sort_values('日期', ascending=False).copy()
            styled_df = year_df[['日期', '代號', '名稱', '獲利', '百分比']].style.applymap(color_pnl, subset=['獲利', '百分比']).format({'日期': lambda x: x.strftime('%Y-%m-%d'), '獲利': 'NT$ {:,.0f}', '百分比': '{:+.2f}%'})
            st.dataframe(styled_df, hide_index=True, use_container_width=True)

# 6. 策略模擬回測工具
@st.dialog("🧪 投資策略模擬回測", width="large")
def backtest_dialog(ticker):
    st.write(f"### 模擬標的：{ticker}")
    col_mode, col_amt, col_year = st.columns([1.5, 2, 2])
    mode = col_mode.radio("選擇投資模式", ["單筆投入", "定期定額"])
    invest_amt = col_amt.number_input(f"{mode}金額 (NT$)", value=100000 if mode == "單筆投入" else 10000, step=5000)
    years = col_year.slider("回測年數", 1, 10, 3)
    start_date = datetime.now() - timedelta(days=years*365)
    st.divider()
    
    with st.spinner("數據計算中..."):
        data = yf.download(ticker, start=start_date, progress=False)
        if data.empty:
            st.error("無法取得歷史數據。")
            return
        if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
        
        close_prices = data['Close']
        history_data = []
        if mode == "單筆投入":
            first_price = float(close_prices.iloc[0])
            total_shares = invest_amt / first_price
            total_invested = invest_amt
            for date, price in close_prices.items():
                history_data.append({"日期": date, "累計投入": total_invested, "當前市值": total_shares * float(price)})
        else:
            monthly_data = close_prices.resample('MS').first()
            total_shares, total_invested = 0, 0
            for date, price in monthly_data.items():
                if pd.isna(price): continue
                price_val = float(price)
                total_shares += invest_amt / price_val
                total_invested += invest_amt
                history_data.append({"日期": date, "累計投入": total_invested, "當前市值": total_shares * price_val})

        df_res = pd.DataFrame(history_data)
        final_value = df_res["當前市值"].iloc[-1]
        total_invested = df_res["累計投入"].iloc[-1]
        total_profit = final_value - total_invested
        total_roi = (total_profit / total_invested) * 100
        cagr = ((final_value / total_invested) ** (1 / years) - 1) * 100
        df_res['rolling_max'] = df_res['當前市值'].cummax()
        df_res['drawdown'] = (df_res['當前市值'] - df_res['rolling_max']) / df_res['rolling_max']
        mdd = df_res['drawdown'].min() * 100

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("最終市值", f"${final_value:,.0f}", delta=f"{total_profit:,.0f}")
        c2.metric("總報酬率", f"{total_roi:.2f}%")
        c3.metric("年化報酬率", f"{cagr:.2f}%")
        c4.metric("最大跌幅 (MDD)", f"{mdd:.2f}%", delta_color="inverse")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_res["日期"], y=df_res["累計投入"], name="成本線", line=dict(color='gray', dash='dot')))
        fig.add_trace(go.Scatter(x=df_res["日期"], y=df_res["當前市值"], name="價值走勢", fill='tozeroy', line=dict(color='#FF4B4B' if total_profit > 0 else '#00B050')))
        fig.update_layout(title=f"{ticker} {years}年績效 (CAGR: {cagr:.1f}% / MDD: {mdd:.1f}%)", template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

# ==============================================================================
# 第三部分：【系統初始化與側邊欄管理】 - 密碼、同步、庫存管理
# ==============================================================================
st.set_page_config(page_title="小鐵的股票分析報告", layout="wide")
st.title("📈 小鐵的股票分析報告")

# 初始化 Widget 狀態
if 'selected_ticker' not in st.session_state: st.session_state.selected_ticker = None
if 'temp_ticker' not in st.session_state: st.session_state.temp_ticker = None

# API Token 設定
FINMIND_TOKEN = st.secrets["FINMIND_TOKEN"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
dl = DataLoader()
try: dl.set_token(token=FINMIND_TOKEN)
except: pass

# 側邊欄：帳戶管理
st.sidebar.title("☁️ 雲端帳戶管理")
if st.session_state.db:
    st.sidebar.success("✅ 已連線至 Google Sheets")
else:
    if st.sidebar.button("🔄 重新連線雲端"):
        st.session_state.db = load_db_from_sheets()
        st.rerun()

st.sidebar.divider()

# 權限驗證邏輯
is_authenticated = False
if st.session_state.db.get("password_hash") is None:
    st.sidebar.info("🔓 此雲端帳戶尚未設置密碼")
    if st.sidebar.checkbox("🔒 設置 4 位數登入密碼"):
        new_pwd = st.sidebar.text_input("設定新密碼", type="password", max_chars=4)
        if st.sidebar.button("確認設置"):
            if len(new_pwd) == 4:
                st.session_state.db["password_hash"] = hash_password(new_pwd)
                save_db_to_sheets(st.session_state.db)
                st.success("密碼已設定！")
                st.rerun()
    is_authenticated = True 
else:
    input_pwd = st.sidebar.text_input("🔑 輸入 4 位數密碼開啟報告", type="password", max_chars=4)
    if input_pwd:
        if hash_password(input_pwd) == st.session_state.db["password_hash"]:
            is_authenticated = True
        else:
            st.sidebar.error("❌ 密碼錯誤")

if not is_authenticated:
    st.warning("🔒 請輸入正確密碼以解鎖報告")
    st.stop()

# 側邊欄：進階設定與存檔
with st.sidebar.expander("⚙️ 進階設定"):
    if st.button("♻️ 強制刷新雲端數據"):
        st.session_state.db = load_db_from_sheets()
        st.toast("已同步最新數據")
    if st.button("💾 手動存檔至雲端"):
        save_db_to_sheets(st.session_state.db)
        st.success("存檔完成")

# 庫存資產總覽卡片
active_list = st.session_state.db["list"]
active_costs = st.session_state.db["costs"]
total_cost, total_value = 0.0, 0.0
if active_costs:
    with st.spinner("計算總資產中..."):
        for t_code, info in active_costs.items():
            try:
                temp_df = yf.download(t_code, period="1d", progress=False)
                if not temp_df.empty:
                    c_price = temp_df['Close'].iloc[-1]
                    c = info['cost'] if isinstance(info, dict) else info
                    q = info['qty'] if isinstance(info, dict) else 1.0
                    total_cost += c * q * 1000
                    total_value += float(c_price) * q * 1000
            except: continue

profit = total_value - total_cost
roi = (profit / total_cost * 100) if total_cost > 0 else 0
p_color = "#FF4B4B" if profit > 0 else ("#00B050" if profit < 0 else "#FFFFFF")

st.write("### 🏢 小鐵的雲端投資組合")
st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1e1e1e 0%, #2d2d2d 100%); padding: 25px; border-radius: 20px; border-left: 10px solid {p_color};">
        <div style="display: flex; justify-content: space-around; align-items: center;">
            <div><p style="color: gray; margin: 0;">資產總市值</p><h2 style="color: white; margin: 0;">NT$ {int(total_value):,}</h2></div>
            <div style="border-left: 1px solid #444; border-right: 1px solid #444; padding: 0 30px;">
                <p style="color: gray; margin: 0;">預估總損益</p>
                <h1 style="color: {p_color}; margin: 0; font-size: 36px;">{"+" if profit > 0 else ""}{int(profit):,}</h1>
            </div>
            <div><p style="color: gray; margin: 0;">總報酬率</p><h2 style="color: {p_color}; margin: 0;">{roi:.2f}%</h2></div>
        </div>
    </div>
""", unsafe_allow_html=True)

# 側邊欄：功能按鈕區
st.sidebar.subheader("⚙️ 庫存管理")
if st.sidebar.button("➕ 新增股票項目", use_container_width=True): add_stock_dialog() 
if st.sidebar.button("🔍 查看目前全帳戶明細", use_container_width=True): show_full_portfolio_report(active_costs, active_list)

st.sidebar.write("### 📈 績效追蹤")
col_pnl1, col_pnl2 = st.sidebar.columns(2)
if col_pnl1.button("💰 紀錄賣出", use_container_width=True): record_sale_dialog() 
if col_pnl2.button("📊 查看報表", use_container_width=True): show_annual_report_dialog()

st.sidebar.write("---")
ticker_options = list(active_list.keys())

# 下拉選單處理
def update_ticker_state(): st.session_state.selected_ticker = st.session_state.temp_ticker

if 'selected_ticker' in st.session_state and st.session_state.selected_ticker in ticker_options:
    st.session_state.temp_ticker = st.session_state.selected_ticker

default_index = 0
if st.session_state.selected_ticker in ticker_options:
    default_index = ticker_options.index(st.session_state.selected_ticker)

selected_ticker = st.sidebar.selectbox(
    "選取庫存個股", ticker_options, index=default_index, key="temp_ticker",        
    on_change=update_ticker_state, format_func=lambda x: f"{x} {active_list.get(x, '')}"
)
st.session_state.selected_ticker = selected_ticker

if selected_ticker:
    if st.sidebar.button(f"🗑️ 刪除 {selected_ticker}", use_container_width=True):
        delete_confirm_dialog(selected_ticker, active_list.get(selected_ticker))

custom_search = st.sidebar.text_input("🔍 全域搜尋 (不加入庫存)", "")
ticker_input = custom_search if custom_search else selected_ticker
period = st.sidebar.selectbox("分析時間範圍", ["5d", "1mo", "6mo", "1y", "2y"], index=2)

if st.sidebar.button("🧪 執行投資模擬回測", use_container_width=True):
    if ticker_input: backtest_dialog(ticker_input)

# 個股帳務快速編輯
current_costs = active_costs.get(selected_ticker, {"cost": 0.0, "qty": 0.0})
st.sidebar.write("---")
st.sidebar.subheader(f"💰 帳務編輯: {active_list.get(selected_ticker, '未知')}")
new_cost = st.sidebar.number_input("買入成本", value=float(current_costs["cost"]), step=0.01, key=f"cost_input_{selected_ticker}")
new_qty = st.sidebar.number_input("持有張數", value=float(current_costs["qty"]), step=1.0, key=f"qty_input_{selected_ticker}")
if st.sidebar.button("💾 儲存帳務修改", use_container_width=True):
    st.session_state.db["costs"][selected_ticker] = {"cost": new_cost, "qty": new_qty}
    save_db_to_sheets(st.session_state.db) 
    st.sidebar.success("已更新")
    st.rerun()

show_news = st.sidebar.checkbox("顯示相關新聞", value=True)

# ==============================================================================
# 第四部分：【技術指標與數據分析】 - 計算公式與資料抓取
# ==============================================================================
def calculate_rsi(df, periods=14):
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
    return 100 - (100 / (1 + (gain / loss)))

def calculate_macd(df):
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal

def calculate_atr(df, window=14):
    tr = pd.concat([df['High']-df['Low'], (df['High']-df['Close'].shift()).abs(), (df['Low']-df['Close'].shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(window=window).mean()

def get_foreign_holding(stock_id):
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockHoldingSharesPer", "data_id": stock_id.split('.')[0], 
              "start_date": (datetime.now()-timedelta(days=180)).strftime('%Y-%m-%d'), "token": FINMIND_TOKEN}
    try:
        data = requests.get(url, params=params).json().get("data", [])
        return pd.DataFrame(data).assign(date=lambda x: pd.to_datetime(x['date'])) if data else pd.DataFrame()
    except: return pd.DataFrame()

def get_monthly_revenue(stock_id):
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockMonthRevenue", "data_id": stock_id.split('.')[0], 
              "start_date": (datetime.now()-timedelta(days=730)).strftime('%Y-%m-%d'), "token": FINMIND_TOKEN}
    try:
        data = requests.get(url, params=params).json().get("data", [])
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['revenue_year'].astype(str) + '-' + df['revenue_month'].astype(str) + '-01')
        return df.sort_values('date')
    except: return pd.DataFrame()

# ==============================================================================
# 第五部分：【視覺化報表與 AI 評等】 - 主畫面圖表渲染
# ==============================================================================
if ticker_input:
    data = yf.download(ticker_input, period=period)
    if not data.empty:
        # 指標計算
        if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
        data['MACD'], data['Signal'], data['Hist'] = calculate_macd(data)
        data['ATR'] = calculate_atr(data)
        data['RSI'] = calculate_rsi(data)
        data['MA5'] = data['Close'].rolling(5).mean(); data['MA20'] = data['Close'].rolling(20).mean(); data['MA60'] = data['Close'].rolling(60).mean()
        data['ATR_Trailing'] = data['Close'].rolling(20).max() - (data['ATR'] * 2)
        curr, prev = data.iloc[-1], data.iloc[-2]
        price = float(curr['Close'])

        # 1. 顯示該股目前的持倉損益
        if ticker_input in active_costs:
            st.write("---")
            info = active_costs[ticker_input]
            c = info['cost'] if isinstance(info, dict) else info
            q = info['qty'] if isinstance(info, dict) else 1.0
            pft = (price * q * 1000) - (c * q * 1000)
            pft_r = (pft / (c * q * 1000)) * 100 if c > 0 else 0
            i1, i2, i3 = st.columns(3)
            p_clr = "#FF4B4B" if pft > 0 else "#00B050"
            i1.markdown(f"**預估損益 (報酬率)** \n<span style='color:{p_clr}; font-size:24px; font-weight:bold;'>{int(pft):,} ({pft_r:.2f}%)</span>", unsafe_allow_html=True)
            i2.metric("投入本金", f"NT$ {int(c*q*1000):,}"); i3.metric("目前市值", f"NT$ {int(price*q*1000):,}")

        # 2. 個股即時概況指標
        st.subheader(f"📊 {ticker_input} {active_list.get(ticker_input, '')} 即時概況")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("當前股價", f"{price:.2f}", f"{price - float(prev['Close']):.2f}", delta_color="inverse")
        m2.metric("60日高點", f"{data['High'].tail(60).max():.2f}")
        m3.metric("5MA", f"{float(curr['MA5']):.2f}"); m4.metric("20MA", f"{float(curr['MA20']):.2f}")
        m5.metric("60MA", f"{float(curr['MA60']):.2f}"); m6.metric("RSI(14)", f"{float(curr['RSI']):.1f}")

        # 3. 法人籌碼數據
        st.write("---")
        st.subheader("👥 昨日三大法人買賣數據 (張)")
        f_net, d_net, s_net = 0, 0, 0
        try:
            df_chip = dl.taiwan_stock_institutional_investors(stock_id=ticker_input.split('.')[0], start_date=(datetime.now()-timedelta(days=10)).strftime('%Y-%m-%d'))
            if not df_chip.empty:
                last_day = df_chip['date'].iloc[-1]
                day_data = df_chip[df_chip['date'] == last_day]
                f_net = (day_data[day_data['name'].str.contains('Foreign')]['buy'].sum() - day_data[day_data['name'].str.contains('Foreign')]['sell'].sum()) / 1000
                d_net = (day_data[day_data['name'] == 'Investment_Trust']['buy'].sum() - day_data[day_data['name'] == 'Investment_Trust']['sell'].sum()) / 1000
                s_net = (day_data[day_data['name'].str.contains('Dealer')]['buy'].sum() - day_data[day_data['name'].str.contains('Dealer')]['sell'].sum()) / 1000
                c1, c2, c3 = st.columns(3)
                for c, l, v in zip([c1, c2, c3], ["外資", "投信", "自營商"], [f_net, d_net, s_net]):
                    clr = "#FF4B4B" if v > 0 else "#00B050"
                    c.markdown(f"<div style='text-align:center;'><p style='color:gray;'>{l}</p><h2 style='color:{clr};'>{int(v):,}</h2></div>", unsafe_allow_html=True)
                st.caption(f"更新日期：{last_day}")
        except: st.error("籌碼抓取失敗")

        # 4. 法人籌碼趨勢圖表
        try:
            if not df_chip.empty:
                st.write("#### 📈 近期法人買賣趨勢 (張)")
                df_chip['net'] = (df_chip['buy'] - df_chip['sell']) / 1000
                df_trend = df_chip.pivot_table(index='date', columns='name', values='net', aggfunc='sum').fillna(0)
                name_map = {'Foreign_Investor': '外資', 'Investment_Trust': '投信', 'Dealer_Self': '自營商(自有)', 'Dealer_Hedging': '自營商(避險)'}
                df_trend = df_trend.rename(columns=lambda x: next((v for k, v in name_map.items() if k in x), x))
                dealer_cols = [c for c in df_trend.columns if '自營商' in c]
                if dealer_cols: df_trend['自營商'] = df_trend[dealer_cols].sum(axis=1)

                fig_chip = go.Figure()
                line_configs = {'外資': '#FF9900', '投信': '#CC00FF', '自營商': '#00B050'}
                for label, color in line_configs.items():
                    if label in df_trend.columns:
                        fig_chip.add_trace(go.Scatter(x=df_trend.index, y=df_trend[label], mode='lines+markers', name=label, line=dict(color=color, width=2)))
                fig_chip.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
                fig_chip.update_layout(hovermode="x unified", height=350, template="plotly_dark")
                st.plotly_chart(fig_chip, use_container_width=True)
        except: pass

        # 5. 中長期數據 (外資持股、月營收)
        df_hold = get_foreign_holding(ticker_input)
        if not df_hold.empty:
            st.write("---"); st.subheader("🏛️ 外資持股中長期變動")
            fig_h = make_subplots(specs=[[{"secondary_y": True}]])
            fig_h.add_trace(go.Scatter(x=data.index, y=data['Close'], name="股價", line=dict(color='gray', width=1)), secondary_y=False)
            fig_h.add_trace(go.Scatter(x=df_hold['date'], y=df_hold['ForeignInvestmentSharesRatio'], name="外資持股%", fill='tozeroy', line=dict(color='#00CCFF')), secondary_y=True)
            fig_h.update_layout(height=400, template="plotly_dark"); st.plotly_chart(fig_h, use_container_width=True)

        df_rev = get_monthly_revenue(ticker_input)
        if not df_rev.empty:
            st.write("---"); st.subheader("📈 月營收成長趨勢")
            df_rev['yoy'] = df_rev['revenue'].pct_change(12) * 100
            fig_r = go.Figure()
            fig_r.add_trace(go.Bar(x=df_rev['date'], y=df_rev['revenue'], name="營收", marker_color='rgba(0, 255, 150, 0.4)'))
            fig_r.add_trace(go.Scatter(x=df_rev['date'], y=df_rev['yoy'], name="年增率", line=dict(color='red'), yaxis="y2"))
            fig_r.update_layout(height=400, template="plotly_dark", yaxis2=dict(overlaying="y", side="right"))
            st.plotly_chart(fig_r, use_container_width=True)
            st.info(f"📊 **營收速報**：本月營收為 **{df_rev['revenue'].iloc[-1]/1e8:.2f} 億**，YoY: **{df_rev['yoy'].iloc[-1]:.2f}%**")

        # 6. 技術指標主 K 線圖
        st.write("---"); st.subheader(f"📊 {ticker_input} 技術指標全覽")
        fig_main = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_width=[0.2, 0.2, 0.2, 0.4])
        fig_main.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name="K線"), row=1, col=1)
        fig_main.add_trace(go.Scatter(x=data.index, y=data['MA5'], name="5MA", line=dict(color='#FFFFFF', width=1.5)), row=1, col=1)
        fig_main.add_trace(go.Scatter(x=data.index, y=data['MA20'], name="20MA", line=dict(color='orange', width=1.5)), row=1, col=1)
        fig_main.add_trace(go.Scatter(x=data.index, y=data['MA60'], name="60MA", line=dict(color='#00FF00', width=1.5)), row=1, col=1)
        fig_main.add_trace(go.Scatter(x=data.index, y=data['ATR_Trailing'], name="ATR止損線", line=dict(color='#FF00FF', width=2, dash='longdash')), row=1, col=1)
        fig_main.add_trace(go.Bar(x=data.index, y=data['Volume'], name="成交量", marker_color='rgba(31, 119, 180, 0.7)'), row=2, col=1)
        fig_main.add_trace(go.Scatter(x=data.index, y=data['RSI'], name="RSI", line=dict(color='yellow')), row=3, col=1)
        fig_main.add_trace(go.Scatter(x=data.index, y=data['MACD'], name="MACD", line=dict(color='#00CCFF')), row=4, col=1)
        fig_main.update_layout(height=900, template="plotly_dark", xaxis_rangeslider_visible=False); st.plotly_chart(fig_main, use_container_width=True)

        # 7. AI 診斷與評分邏輯
        st.write("---"); st.subheader("💡 小鐵專屬：AI 投資策略診斷")
        curr_rsi = data['RSI'].iloc[-1]; curr_macd = data['MACD'].iloc[-1]; curr_sig = data['Signal'].iloc[-1]
        col_a, col_b, col_c = st.columns(3)
        is_above_ma20 = price > float(curr['MA20']); macd_golden_cross = curr_macd > curr_sig
        
        with col_a:
            st.markdown("### 📈 技術趨勢")
            if is_above_ma20 and macd_golden_cross: st.success("**強勢多頭確立**")
            elif is_above_ma20 and not macd_golden_cross: st.warning("**高檔震盪警訊**")
            elif not is_above_ma20 and macd_golden_cross: st.info("**築底反彈階段**")
            else: st.error("**空頭排列走勢**")

        with col_b:
            st.markdown("### 🧠 心理強弱")
            if curr_rsi >= 75: st.error(f"**極度貪婪 ({curr_rsi:.1f})**")
            elif curr_rsi <= 25: st.success(f"**極度恐慌 ({curr_rsi:.1f})**")
            else: st.info(f"**運行區間 ({curr_rsi:.1f})**")

        with col_c:
            st.markdown("### 🚀 動能雷達")
            curr_hist = data['Hist'].iloc[-1]; prev_hist = data['Hist'].iloc[-2]
            if curr_macd > curr_sig and curr_hist > prev_hist: st.success("**攻擊火力全開**")
            elif curr_macd < curr_sig and curr_hist < prev_hist: st.error("**跌勢正在加速**")
            else: st.info("**觀望等待信號**")

        # 綜合總分計算
        score = 0
        if price > float(curr['MA20']): score += 2
        else: score -= 2
        if curr_rsi <= 30: score += 1
        elif curr_rsi >= 70: score -= 1
        if curr_macd > curr_sig: score += 1
        else: score -= 1
        
        total_net = f_net + d_net
        chip_status = "中性觀望"; chip_color = "#FFFFFF"
        if f_net > 0 and d_net > 0: score += 2; chip_status = "🔥 土洋同買"; chip_color = "#FF4B4B"
        elif total_net > 0: score += 1; chip_status = "✅ 法人偏多"; chip_color = "#FF4B4B"
        elif total_net < 0: score -= 1; chip_status = "❌ 法人撤出"; chip_color = "#00B050"

        atr_stop = data['ATR_Trailing'].iloc[-1]
        if price < atr_stop: score -= 1; atr_status = "⚠️ 跌破防線"; atr_color = "#00B050"
        else: atr_status = "✅ 守住支撐"; atr_color = "#FF4B4B"

        # 最終評語定義
        if score >= 4: rec_text, rec_color = "🔥 強力進攻", "#FF4B4B"
        elif score >= 2: rec_text, rec_color = "🔎 偏多觀察", "#FF4B4B"
        elif score >= 0: rec_text, rec_color = "💤 觀望為宜", "#FFFFFF"
        else: rec_text, rec_color = "🚨 嚴防急跌", "#00B050"

        st.markdown(f"""
    <div style="border-radius: 15px; padding: 20px; border: 2px solid {rec_color}; text-align: center; background-color: rgba(255,255,255,0.05); margin: 20px 0;">
        <h3 style="color: #AAAAAA; margin-bottom: 5px;">🏆 小鐵全方位評等</h3>
        <h1 style="color: {rec_color}; margin-top: 0; font-size: 38px;">{rec_text}</h1>
        <div style="display: flex; justify-content: space-around; background-color: rgba(0,0,0,0.2); padding: 15px; border-radius: 10px;">
            <div style="flex: 1;"><p style="color: #888888; font-size: 12px; margin: 0;">籌碼走向</p><p style="color: {chip_color}; font-weight: bold; margin: 0;">{chip_status}</p></div>
            <div style="flex: 1; border-left: 1px solid #444; border-right: 1px solid #444;"><p style="color: #888888; font-size: 12px; margin: 0;">ATR 防線</p><p style="color: {atr_color}; font-weight: bold; margin: 0;">{atr_status}</p></div>
            <div style="flex: 1;"><p style="color: #888888; font-size: 12px; margin: 0;">綜合得分</p><p style="color: #FFFFFF; font-weight: bold; margin: 0;">{score} 分</p></div>
        </div>
    </div>
""", unsafe_allow_html=True)

# 8. 產經新聞區 (自動去重)
if show_news and ticker_input:
    st.write("---"); st.subheader("📰 台灣產經新聞")
    try:
        df_news = dl.taiwan_stock_news(stock_id=ticker_input.split('.')[0], start_date=(datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'))
        if not df_news.empty:
            df_news = df_news.drop_duplicates(subset=['title'], keep='first')
            if 'date' in df_news.columns: df_news = df_news.sort_values(by='date', ascending=False)
            for _, row in df_news.head(8).iterrows():
                with st.expander(f"[{row['date'].split(' ')[0]}] {row['title']}"):
                    st.write(row.get('summary', '無摘要')); st.markdown(f"🔗 [點擊查看原文]({row['link']})")
        else: st.info("⚠️ 近期暫無相關新聞。")
    except: pass

