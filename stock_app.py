import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd
import json
import os
import hashlib
import requests
import time
from datetime import datetime, timedelta
from FinMind.data import DataLoader
from plotly.subplots import make_subplots
from streamlit_gsheets import GSheetsConnection
from streamlit_echarts import st_echarts
from bs4 import BeautifulSoup

# ==============================================================================
# 【CSS 優化】 - 針對 st.tabs 進行 TradingView 風格美化
# ==============================================================================
st.markdown("""
    <style>
    /* 1. 調整整個 Tab 欄的高度與背景 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        background-color: #161a25; /* 深色背景 */
        padding: 10px 10px 0px 10px;
        border-radius: 10px 10px 0 0;
    }

    /* 2. 調整單個 Tab 的樣式 */
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #1e222d; /* 預設深灰 */
        border-radius: 8px 8px 0px 0px;
        color: #d1d4dc; /* 淺灰字 */
        font-size: 18px;
        font-weight: 600;
        padding: 0px 25px;
        border: 1px solid #363a45;
        border-bottom: none;
        transition: all 0.2s ease;
    }

    /* 3. 懸停時的效果 (Hover) */
    .stTabs [data-baseweb="tab"]:hover {
        color: #2962ff !important;
        background-color: #2a2e39;
    }

    /* 4. 選中狀態的樣式 (Active) */
    .stTabs [aria-selected="true"] {
        background-color: #2a2e39 !important;
        color: #2962ff !important; /* TradingView 經典藍 */
        border-bottom: 3px solid #2962ff !important; /* 底部藍色粗條 */
    }
    
    /* 隱藏預設的細線 */
    .stTabs [data-baseweb="tab-highlight"] {
        background-color: transparent !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# 【新增效能優化】 - 集中式快取管理 (解決介面卡頓)
# ==============================================================================
@st.cache_data(ttl=300) # 快取 5 分鐘，避免頻繁呼叫 yfinance
def fetch_yf_data_cached(ticker, period=None, interval=None, start=None):
    if start:
        return yf.download(ticker, start=start, progress=False)
    return yf.download(ticker, period=period, interval=interval, progress=False)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_chip_data_cached(stock_id):

    dl_cache = DataLoader()

    try:
        if "FINMIND_TOKEN" in st.secrets:
            dl_cache.set_token(token=st.secrets["FINMIND_TOKEN"])

        df = dl_cache.taiwan_stock_institutional_investors(
            stock_id=stock_id.split('.')[0],
            start_date=(datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        )

        # ✅ 關鍵修正1：避免 cache 空資料
        if df is None or df.empty:
            raise ValueError("No data fetched")

        # ✅ 關鍵修正2：確保欄位存在（防 API 變動）
        required_cols = {"date", "name", "buy", "sell"}
        if not required_cols.issubset(df.columns):
            raise ValueError("Missing columns")

        return df

    except Exception as e:
        # ✅ 不要 silent fail（你之前最大問題）
        print("fetch_chip_data_cached error:", e)
        return None

@st.cache_data(ttl=3600) # 新聞快取 1 小時
def fetch_news_data_cached(stock_id):
    dl_cache = DataLoader()
    try:
        if "FINMIND_TOKEN" in st.secrets:
            dl_cache.set_token(token=st.secrets["FINMIND_TOKEN"])
        return dl_cache.taiwan_stock_news(
            stock_id=stock_id.split('.')[0], 
            start_date=(datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
        )
    except:
        return pd.DataFrame()

# 初始化 DataLoader (用於其他未快取的輕量操作)
dl = DataLoader()

# =============================
# 🔥 籌碼分析強化模組（NEW - 不影響原邏輯）
# =============================
def analyze_chip_trend(df_chip):
    if df_chip is None or df_chip.empty:
        return {}

    df = df_chip.copy()
    df['date'] = pd.to_datetime(df['date'], errors='coerce')

    # 計算淨買賣
    df['net'] = (df['buy'] - df['sell']) / 1000

    # 分三大法人
    foreign = df[df['name'].str.contains('Foreign', case=False, na=False)]
    trust = df[df['name'].str.contains('Investment_Trust', case=False, na=False)]
    dealer = df[df['name'].str.contains('Dealer', case=False, na=False)]

    # 每日加總
    f_daily = foreign.groupby('date')['net'].sum()
    t_daily = trust.groupby('date')['net'].sum()
    d_daily = dealer.groupby('date')['net'].sum()

    def count_streak(series):
        streak = 0
        for val in reversed(series.tail(10)):
            if val > 0:
                streak += 1
            else:
                break
        return streak

    result = {
        "外資連續買": count_streak(f_daily),
        "投信連續買": count_streak(t_daily),
        "自營商連續買": count_streak(d_daily),
        "外資趨勢": f_daily.tail(5).sum(),
        "投信趨勢": t_daily.tail(5).sum(),
        "自營商趨勢": d_daily.tail(5).sum()
    }

    return result
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
                df_recent = fetch_yf_data_cached(t_code, period="1d", interval="1d")
                if df_recent is None or df_recent.empty:
                    continue
                
                c_price = df_recent['Close'].iloc[-1]
                name = active_list.get(t_code, "未知")

                cost = float(info['cost']) if isinstance(info, dict) else float(info)
                qty = float(info['qty']) if isinstance(info, dict) else 0.0
                
                total_cost = cost * qty * 1000
                market_value = c_price * qty * 1000
                diff = market_value - total_cost
                roi = (diff / total_cost * 100) if total_cost > 0 else 0

                report_data.append({
                    "代號": t_code,
                    "名稱": name,
                    "成本價": cost,
                    "現價": c_price,
                    "張數": qty,
                    "投入本金": int(total_cost),
                    "目前市值": int(market_value),
                    "損益": int(diff),
                    "報酬率": roi   # ✅ 保持數值
                })

            except Exception as e:
                print("error:", t_code, e)
                continue

    # ❗ 防呆（重要）
    if not report_data:
        st.warning("⚠️ 無法取得任何報價資料")
        return

    df_report = pd.DataFrame(report_data)

    # 排序
    df_report = df_report.sort_values(by='報酬率', ascending=False)

    # =============================
    # 🎨 顏色函數
    # =============================
    def color_pnl_custom(val):
        try:
            val = float(val)
        except:
            return ""

        if val > 0:
            return "color: #EF5350; font-weight:600;"
        elif val < 0:
            return "color: #26A69A; font-weight:600;"
        return ""

    # =============================
    # 📊 顯示
    # =============================
    st.dataframe(
        df_report.style.applymap(color_pnl_custom, subset=['損益', '報酬率']),
        column_config={
            "報酬率": st.column_config.NumberColumn(format="%.2f%%"),
            "成本價": st.column_config.NumberColumn(format="%.2f"),
            "現價": st.column_config.NumberColumn(format="%.2f"),
        },
        use_container_width=True,
        hide_index=True
    )

    # =============================
    # 📈 合計
    # =============================
    total_p = df_report['損益'].sum()

    st.divider()
    st.metric(
        "合計預估總損益",
        f"NT$ {int(total_p):,}",
        delta=f"{int(total_p):,}"
    )

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
    df_pnl['日期'] = pd.to_datetime(df_pnl['日期'], errors='coerce')
    df_pnl = df_pnl.dropna(subset=['日期'])
    try:
        if df_pnl['日期'].dt.tz is None:
            df_pnl['日期'] = df_pnl['日期'].dt.tz_localize('UTC').dt.tz_convert('Asia/Taipei')
        else:
            df_pnl['日期'] = df_pnl['日期'].dt.tz_convert('Asia/Taipei')
            
        df_pnl['年份'] = df_pnl['日期'].dt.year
        df_pnl['日期顯示'] = df_pnl['日期'].dt.date
    except Exception as e:
        st.warning(f"時區校準異常，切換至手動補償模式: {e}")
        df_pnl['日期'] = df_pnl['日期'] + pd.Timedelta(hours=8)
        df_pnl['年份'] = df_pnl['日期'].dt.year
        df_pnl['日期顯示'] = df_pnl['日期'].dt.date
    
    summary = df_pnl.groupby('年份').agg({'獲利': 'sum', '日期': 'count'}).rename(columns={'日期': '交易筆數', '獲利': '年度總損益'}).sort_index(ascending=False)

    def color_pnl(val):
        if isinstance(val, (int, float)):
            if val > 0: return 'color: #FF4B4B'
            if val < 0: return 'color: #26A69A' # 【UI優化】改用波斯綠
        return 'color: white'

    st.subheader("📊 年度數據摘要")
    st.dataframe(
        summary.style.format({"年度總損益": "NT$ {:,.0f}"}).map(color_pnl, subset=['年度總損益']),
        use_container_width=True
    )
    st.divider()
    st.subheader("📑 詳細交易紀錄")
    years = sorted(df_pnl['年份'].unique(), reverse=True)
    
    for y in years:
        with st.expander(f"📅 {y} 年詳細清單"):
            year_df = df_pnl[df_pnl['年份'] == y].sort_values('日期', ascending=False).copy()
            year_df['日期'] = year_df['日期'].dt.date
            styled_df = year_df[['日期', '代號', '名稱', '獲利', '百分比']].style.map(
                color_pnl, subset=['獲利', '百分比']
            ).format({
                '獲利': 'NT$ {:,.0f}', 
                '百分比': '{:+.2f}%'
            })
            st.dataframe(styled_df, hide_index=True, use_container_width=True)

# 6. 策略模擬回測工具 【優化：加入 MDD 水下曲線】
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
        # 【效能優化】改用快取函數
        data = fetch_yf_data_cached(ticker, start=start_date)
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

        # 【圖表優化】加入雙 Y 軸與 MDD 水下圖
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=df_res["日期"], y=df_res["累計投入"], name="成本線", line=dict(color='gray', dash='dot')), secondary_y=False)
        fig.add_trace(go.Scatter(x=df_res["日期"], y=df_res["當前市值"], name="價值走勢", fill='tozeroy', line=dict(color='#FF4B4B' if total_profit > 0 else '#26A69A')), secondary_y=False)
        fig.add_trace(go.Scatter(x=df_res["日期"], y=df_res['drawdown'] * 100, name="回撤幅度(%)", fill='tozeroy', line=dict(color='rgba(255, 82, 82, 0.3)', width=1)), secondary_y=True)
        
        fig.update_layout(title=f"{ticker} {years}年績效 (CAGR: {cagr:.1f}% / MDD: {mdd:.1f}%)", template="plotly_dark")
        fig.update_yaxes(title_text="資產市值", secondary_y=False)
        fig.update_yaxes(title_text="回撤幅度 %", secondary_y=True, showgrid=False)
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
FINMIND_TOKEN = st.secrets.get("FINMIND_TOKEN", "")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
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
        # 清除所有快取
        st.cache_data.clear()
        st.session_state.db = load_db_from_sheets()
        st.toast("已同步最新數據並清除快取")
    if st.button("💾 手動存檔至雲端"):
        save_db_to_sheets(st.session_state.db)
        st.success("存檔完成")

# 庫存資產總覽卡片
active_list = st.session_state.db["list"]
active_costs = st.session_state.db["costs"]

# 側邊欄：功能按鈕區
st.sidebar.subheader("⚙️ 庫存管理")
if st.sidebar.button("➕ 新增股票項目", use_container_width=True): add_stock_dialog() 
if st.sidebar.button("🔍 查看目前全帳戶明細", use_container_width=True): show_full_portfolio_report(active_costs, active_list)

st.sidebar.write("### 📈 績效追蹤")
col_pnl1, col_pnl2 = st.sidebar.columns(2)
if col_pnl1.button("💰 紀錄賣出", use_container_width=True): record_sale_dialog() 
if col_pnl2.button("📊 查看報表", use_container_width=True): show_annual_report_dialog()

st.sidebar.write("---")
ticker_options = sorted(list(active_list.keys()))

if 'selected_ticker' not in st.session_state:
    st.session_state.selected_ticker = ticker_options[0] if ticker_options else ""

try:
    current_index = ticker_options.index(st.session_state.selected_ticker)
except (ValueError, KeyError):
    current_index = 0

selected_ticker = st.sidebar.selectbox(
    "選取庫存個股",
    options=ticker_options,
    index=current_index,
    format_func=lambda x: f"{x} {active_list.get(x, '')}",
    key="ticker_selector_widget" 
)

st.session_state.selected_ticker = selected_ticker
ticker_input = selected_ticker

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
# 【新增 UI 優化】 - st.tabs 模組化分頁架構
# ==============================================================================
tab_portfolio, tab_analysis,  tab_news = st.tabs([
    "📦 庫存總覽", "📈 個股深度分析",  "📰 產經動態"
])

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


# ==============================================================================
# Tab 1: 庫存總覽 (移入 Tab)
# ==============================================================================
with tab_portfolio:
    total_cost, total_value = 0.0, 0.0
    processed_data = []

    if active_costs:
        with st.spinner("正在同步雲端數據並計算總資產..."):
            for t_code, info in active_costs.items():
                try:
                    # 【效能優化】使用快取取代每次都要重新下載
                    temp_df = fetch_yf_data_cached(t_code, period="5d", interval="1m")
                    
                    if not temp_df.empty:
                        if isinstance(temp_df.columns, pd.MultiIndex):
                            temp_df.columns = temp_df.columns.get_level_values(0)
                        
                        valid_close = temp_df['Close'].dropna()
                        if not valid_close.empty:
                            c_price = float(valid_close.iloc[-1])
                            
                            c = float(info['cost']) if isinstance(info, dict) else float(info)
                            q = float(info['qty']) if isinstance(info, dict) else 0.0
                            
                            current_market_val = c_price * q * 1000
                            total_cost += (c * q * 1000)
                            total_value += current_market_val
                            
                            if current_market_val > 0:
                                processed_data.append({
                                    "label": active_list.get(t_code, t_code),
                                    "value": current_market_val
                                })
                except Exception as e:
                    continue

    # 計算損益
    profit = total_value - total_cost
    roi = (profit / total_cost * 100) if total_cost > 0 else 0
    if profit > 0:
        p_color = "#FF4B4B" # 紅色
        prefix = "+"
    elif profit < 0:
        p_color = "#00BA81" # 綠色
        prefix = ""
    else:
        p_color = "#FFFFFF" # 白色
        prefix = ""
    

    st.write("### ☁️ 小鐵的雲端投資組合")
    col_summary, col_chart = st.columns([3.5, 6.5])

    with col_summary:
        st.markdown(f"""
            <div style="
                background-color: #1e1e1e; 
                padding: 25px; 
                border-radius: 20px; 
                border-left: 12px solid {p_color}; 
                height: 380px; 
                display: flex; 
                flex-direction: column; 
                justify-content: space-between;
                box-shadow: 5px 5px 15px rgba(0,0,0,0.3);
            ">
                <div>
                    <p style="color: #888; margin: 0; font-size: 14px; font-weight: bold;">資產總市值</p>
                    <h2 style="color: white; margin: 0; font-size: 28px; font-family: 'Courier New';">NT$ {int(total_value):,}</h2>
                </div>
                <div style="border-top: 1px solid #333; border-bottom: 1px solid #333; padding: 20px 0;">
                    <p style="color: #888; margin: 0; font-size: 14px; font-weight: bold;">預估總損益</p>
                    <h1 style="color: {p_color}; margin: 0; font-size: 38px; font-weight: 800;">{prefix}{int(profit):,}</h1>
                </div>
                <div>
                    <p style="color: #888; margin: 0; font-size: 14px; font-weight: bold;">總報酬率</p>
                    <h2 style="color: {p_color}; margin: 0; font-size: 28px; font-weight: bold;">{prefix}{roi:.2f}%</h2>
                </div>
            </div>
        """, unsafe_allow_html=True)

    with col_chart:
        if processed_data:
            # 1. 格式化資料為 ECharts 格式
            chart_data = [{"value": d['value'], "name": d['label']} for d in processed_data]
        
            # 2. 設定 ECharts 配置項 (南丁格爾玫瑰圖樣式)
            options = {
                "backgroundColor": "rgba(0,0,0,0)", # 透明背景，完美契合你的深色 UI
                "tooltip": {
                    "trigger": "item", 
                    "formatter": "{b}: {c} ({d}%)",
                    "backgroundColor": "#2a2e39",
                    "textStyle": {"color": "#fff"}
                },
                "legend": {
                    "orient": "horizontal",
                    "bottom": "0",
                    "textStyle": {"color": "#d1d4dc"}
                },
                "series": [
                    {
                        "name": "資產配置",
                        "type": "pie",
                        "radius": ["15%", "75%"], # 內外半徑，創造層次感
                        "center": ["50%", "45%"],
                        "roseType": "area", # 關鍵：南丁格爾玫瑰模式，數值越大半徑越長
                        "itemStyle": {
                            "borderRadius": 12, # 圓角
                            "shadowBlur": 20,   # 陰影，營造 2.5D 立體感
                            "shadowColor": "rgba(0, 0, 0, 0.5)"
                        },
                        "data": chart_data,
                        "label": {
                            "show": True,
                            "color": "#fff",
                            "formatter": "{b}\n{d}%",
                            "fontSize": 14
                        },
                        # 使用與你原本一致的專業配色
                        "color": ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3', '#FF6692']
                    }
                ]
            }
        
            # 3. 渲染圖表
            st_echarts(options=options, height="450px")
            
    # 顯示下方的智慧點評 (跨欄顯示)
    if 'values' in locals() and values:
        max_idx = values.index(max(values))
        max_stock = labels[max_idx]
        max_pct = (values[max_idx] / sum(values)) * 100
        
        if max_pct > 50:
            st.warning(f"⚠️ **小鐵提醒**：您的資金高度集中在 **{max_stock}** ({max_pct:.1f}%)。若該股波動較大，將顯著影響總資產水位。")
        else:
            st.info(f"✅ **小鐵點評**：資產配置比例健康。目前以 **{max_stock}** 為核心持股。")

# ==============================================================================
# Tab 2: 個股深度分析 (移入 Tab 且更新 UI)
# ==============================================================================
with tab_analysis:
    # 🎨 TradingView UI 強化 【優化：注入專業波斯綠 #26A69A 與 hover 效果】
    st.markdown("""
    <style>
    .card {
        background-color: #131722;
        padding: 16px;
        border-radius: 12px;
        border: 1px solid #2A2E39;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s, border-color 0.2s;
    }
    .card:hover {
        transform: translateY(-2px);
        border-color: #26A69A;
    }
    .metric-title { color: #9BA3AF; font-size: 12px; }
    .metric-value { font-size: 22px; font-weight: 600; }
    .up { color: #FF4B4B; }
    .down { color: #26A69A; } /* 【UI優化】台股習慣紅色為漲，綠色為跌。改用高質感的波斯綠 */
    .section-title {
        font-size: 18px;
        font-weight: 600;
        margin-top: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

    df_chip = pd.DataFrame()

    if ticker_input:
        f_period = "2d" if period == "1d" else period
        f_interval = "1m" if period in ["1d", "5d"] else "1d"

        # 【效能優化】使用快取取代 yf.download
        data = fetch_yf_data_cached(ticker_input, period=f_period, interval=f_interval)

        if not data.empty:
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                if col in data.columns:
                    data[col] = pd.to_numeric(data[col], errors='coerce')

            data = data.ffill()
            data = data.dropna(subset=['Close'])

            # ===== 指標 =====
            data['MACD'], data['Signal'], data['Hist'] = calculate_macd(data)
            data['ATR'] = calculate_atr(data)
            data['RSI'] = calculate_rsi(data)
            data['MA5'] = data['Close'].rolling(5).mean()
            data['MA20'] = data['Close'].rolling(20).mean()
            data['MA60'] = data['Close'].rolling(60).mean()
            data['ATR_Trailing'] = data['Close'].rolling(20).max() - (data['ATR'] * 2)

            curr = data.iloc[-1]
            prev = data.iloc[-2] if len(data) > 1 else curr
            price = float(curr['Close'])

            # =============================
            # 💰 持倉卡片
            # =============================
            if ticker_input in active_costs:
                st.markdown('<div class="section-title">💰 持倉分析</div>', unsafe_allow_html=True)

                info = active_costs[ticker_input]
                c = float(info['cost']) if isinstance(info, dict) else float(info)
                q = float(info['qty']) if isinstance(info, dict) else 1.0

                pft = (price*q*1000)-(c*q*1000)
                pft_r = (pft/(c*q*1000))*100 if c>0 else 0

                cols = st.columns(4)

                def card(col, title, val, updown=None):
                    cls = "up" if updown == "up" else "down" if updown == "down" else ""
                    col.markdown(f"""
                    <div class="card">
                        <div class="metric-title">{title}</div>
                        <div class="metric-value {cls}">{val}</div>
                    </div>
                    """, unsafe_allow_html=True)

                card(cols[0], "損益", f"{int(pft):,} ({pft_r:.2f}%)", "up" if pft>0 else "down")
                card(cols[1], "成本", f"{c:.2f}")
                card(cols[2], "投入", f"{int(c*q*1000):,}")
                card(cols[3], "市值", f"{int(price*q*1000):,}")

            # =============================
            # 📊 即時概況（卡片化）
            # =============================
            st.markdown(f'<div class="section-title">📊 {ticker_input} 即時數據</div>', unsafe_allow_html=True)

            cols = st.columns(6)
            metrics = [
                ("價格", f"{price:.2f}", price > prev['Close']),
                ("60H", f"{data['High'].tail(60).max():.2f}", None),
                ("MA5", f"{curr['MA5']:.2f}", None),
                ("MA20", f"{curr['MA20']:.2f}", None),
                ("MA60", f"{curr['MA60']:.2f}", None),
                ("RSI", f"{curr['RSI']:.1f}", None),
            ]

            for col, (t, v, trend) in zip(cols, metrics):
                cls = "up" if trend else "down" if trend==False else ""
                col.markdown(f"""
                <div class="card">
                    <div class="metric-title">{t}</div>
                    <div class="metric-value {cls}">{v}</div>
                </div>
                """, unsafe_allow_html=True)

            # =============================
            # 👥 法人籌碼
            # =============================
            try:
                df_chip = fetch_chip_data_cached(ticker_input)

                if df_chip is not None and not df_chip.empty:

                    df_chip['date'] = pd.to_datetime(df_chip['date'], errors='coerce')

                    last_day = df_chip['date'].dropna().max()

                    # ✅ 修正1：日期比對問題（最重要）
                    day_data = df_chip[df_chip['date'].dt.date == last_day.date()]

                    # ✅ 修正2：避免假資料（空）
                    if day_data.empty:
                        st.warning("⚠️ 最新交易日尚無法人資料（通常是今天尚未更新）")
                        st.stop()

                    # ===== 法人計算 =====
                    f_net = (
                        day_data[day_data['name'].str.contains('Foreign', case=False, na=False)]['buy'].sum()
                        - day_data[day_data['name'].str.contains('Foreign', case=False, na=False)]['sell'].sum()
                    ) / 1000

                    d_net = (
                        day_data[day_data['name'].str.contains('Investment_Trust', case=False, na=False)]['buy'].sum()
                        - day_data[day_data['name'].str.contains('Investment_Trust', case=False, na=False)]['sell'].sum()
                    ) / 1000

                    s_net = (
                        day_data[day_data['name'].str.contains('Dealer', case=False, na=False)]['buy'].sum()
                        - day_data[day_data['name'].str.contains('Dealer', case=False, na=False)]['sell'].sum()
                    ) / 1000

                    st.markdown('<div class="section-title">👥 法人動向</div>', unsafe_allow_html=True)
                    c1, c2, c3 = st.columns(3)

                    for c,l,v in zip([c1,c2,c3],["外資","投信","自營商"],[f_net,d_net,s_net]):
                        cls = "up" if v>0 else "down"
                        c.markdown(f"""
                        <div class="card">
                            <div class="metric-title">{l}</div>
                            <div class="metric-value {cls}">{int(v):,} 張</div>
                        </div>
                        """, unsafe_allow_html=True)

                    st.caption(f"更新：{last_day.date()}")

                    # =============================
                    # 🔥 主力行為分析
                    # =============================
                    chip_analysis = analyze_chip_trend(df_chip)

                    if chip_analysis:
                        st.markdown("### 🧠 主力行為解析")

                        c1, c2, c3 = st.columns(3)

                        def render_chip_card(col, title, streak, trend):
                            if streak >= 3:
                                status = "🔥 連續買超"
                                color = "#FF4B4B"
                            elif trend > 0:
                                status = "✅ 偏多"
                                color = "#FF9900"
                            elif trend < 0:
                                status = "❌ 偏空"
                                color = "#00B050"
                            else:
                                status = "中性"
                                color = "#AAAAAA"

                            col.markdown(f"""
                            <div class="card">
                                <div class="metric-title">{title}</div>
                                <div style="color:{color}; font-size:20px; font-weight:bold;">
                                    {status}
                                </div>
                                <div style="font-size:12px; color:gray;">
                                    連續買超：{streak} 天
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                        render_chip_card(c1, "外資", chip_analysis["外資連續買"], chip_analysis["外資趨勢"])
                        render_chip_card(c2, "投信", chip_analysis["投信連續買"], chip_analysis["投信趨勢"])
                        render_chip_card(c3, "自營商", chip_analysis["自營商連續買"], chip_analysis["自營商趨勢"])

                else:
                    st.warning("⚠️ 無法人資料（API或快取問題）")

            except Exception as e:
                st.error(f"籌碼抓取失敗: {e}")

            # =============================
            # 📈 法人趨勢
            # =============================
            if df_chip is not None and not df_chip.empty:
                df_chip['net'] = (df_chip['buy'] - df_chip['sell']) / 1000
                df_trend = df_chip.pivot_table(index='date', columns='name', values='net', aggfunc='sum').fillna(0)

                name_map = {'Foreign_Investor':'外資','Investment_Trust':'投信','Dealer_Self':'自營商(自有)','Dealer_Hedging':'自營商(避險)'}
                df_trend = df_trend.rename(columns=lambda x: next((v for k,v in name_map.items() if k in x), x))
                dealer_cols = [c for c in df_trend.columns if '自營商' in c]
                if dealer_cols:
                    df_trend['自營商'] = df_trend[dealer_cols].sum(axis=1)
                    df_trend = df_trend.drop(columns=dealer_cols, errors='ignore')

                fig_chip = go.Figure()

                for label,color in {'外資':'#2962FF','投信':'#FF6D00','自營商':'#00C853'}.items():
                    if label in df_trend.columns:
                        fig_chip.add_trace(go.Scatter(x=df_trend.index,y=df_trend[label],name=label,line=dict(color=color)))

                fig_chip.update_layout(template="plotly_dark",height=300,hovermode="x unified")
                st.plotly_chart(fig_chip,use_container_width=True)

            # =============================
            # 📊🔥 合併主圖（TV風格）
            # =============================
            st.markdown('<div class="section-title">📊 技術分析</div>', unsafe_allow_html=True)

            fig = make_subplots(
                rows=3, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                row_heights=[0.6,0.2,0.2]
            )

            # K線 (【UI優化】將下降 K 線改為波斯綠色)
            fig.add_trace(go.Candlestick(
                x=data.index,
                open=data['Open'],
                high=data['High'],
                low=data['Low'],
                close=data['Close'],
                increasing_line_color='#FF4B4B',
                decreasing_line_color='#26A69A'
            ), row=1,col=1)

            # MA + ATR
            fig.add_trace(go.Scatter(x=data.index,y=data['MA5'],name="5日均線",line=dict(color='white',width=1)),row=1,col=1)
            fig.add_trace(go.Scatter(x=data.index,y=data['MA20'],name="20日均線",line=dict(color='orange',width=1)),row=1,col=1)
            fig.add_trace(go.Scatter(x=data.index,y=data['MA60'],name="60日均線",line=dict(color='green',width=1)),row=1,col=1)
            fig.add_trace(go.Scatter(x=data.index,y=data['ATR_Trailing'],name="ATR 停損線",line=dict(color='magenta',dash='dot')),row=1,col=1)

            fig.add_trace(go.Bar(x=data.index,y=data['Volume'],name="成交量",marker_color='rgba(100,149,237,0.4)'),row=2,col=1)

            fig.add_trace(go.Scatter(x=data.index,y=data['RSI'],name="RSI 指標",line=dict(color='yellow')),row=3,col=1)
            fig.add_trace(go.Scatter(x=data.index,y=data['MACD'],name="MACD 動能",line=dict(color='#00CCFF')),row=3,col=1)

            fig.update_layout(
                template="plotly_dark",
                height=800,
                hovermode="x unified",
                margin=dict(l=10,r=10,t=10,b=10),
                xaxis_rangeslider_visible=False
            )

            fig.update_yaxes(gridcolor="#2A2E39")

            st.plotly_chart(fig,use_container_width=True)

            # =============================
            # 🤖 AI 專業評分系統（升級版）
            # =============================
            st.write("---")
            st.markdown("## 🤖 投資診斷系統")

            curr_rsi = data['RSI'].iloc[-1]
            curr_macd = data['MACD'].iloc[-1]
            curr_sig = data['Signal'].iloc[-1]
            curr_hist = data['Hist'].iloc[-1]
            prev_hist = data['Hist'].iloc[-2]

            is_above_ma20 = price > float(curr['MA20'])
            macd_golden_cross = curr_macd > curr_sig

            # =============================
            # 🎯 1. 三大核心因子評分
            # =============================
            trend_score, psy_score, momo_score = 0, 0, 0

            # 趨勢
            if is_above_ma20 and macd_golden_cross:
                trend_label = "多頭趨勢"
                trend_score = 2
            elif is_above_ma20:
                trend_label = "高檔整理"
                trend_score = 1
            elif macd_golden_cross:
                trend_label = "反彈初期"
                trend_score = 0
            else:
                trend_label = "空頭趨勢"
                trend_score = -2

            # 心理
            if curr_rsi >= 75:
                psy_label = "過熱"
                psy_score = -1
            elif curr_rsi <= 25:
                psy_label = "超跌"
                psy_score = 1
            else:
                psy_label = "中性"
                psy_score = 0

            # 動能
            if curr_macd > curr_sig and curr_hist > prev_hist:
                momo_label = "動能增強"
                momo_score = 1
            elif curr_macd < curr_sig and curr_hist < prev_hist:
                momo_label = "動能轉弱"
                momo_score = -1
            else:
                momo_label = "動能整理"
                momo_score = 0

            # =============================
            # 🎯 2. 籌碼 + ATR
            # =============================
            score = trend_score + psy_score + momo_score
            
            try:
                total_net = f_net + d_net
            except:
                total_net, f_net, d_net = 0, 0, 0

            if f_net > 0 and d_net > 0:
                chip_label = "法人同步買入"
                score += 2
            elif total_net > 0:
                chip_label = "法人偏多"
                score += 1
            elif total_net < 0:
                chip_label = "法人賣出"
                score -= 1
            else:
                chip_label = "中性"

            atr_stop = data['ATR_Trailing'].iloc[-1]

            if price < atr_stop:
                atr_label = "跌破支撐"
                score -= 1
            else:
                atr_label = "支撐有效"

            # =============================
            # 🎯 3. 最終評級
            # =============================
            if score >= 4:
                rec = "強勢多頭"
                color = "#26A69A"
            elif score >= 2:
                rec = "偏多"
                color = "#00C853"
            elif score >= 0:
                rec = "盤整"
                color = "#FFD600"
            else:
                rec = "偏空"
                color = "#EF5350"

            # =============================
            # 🎨 UI（TradingView卡片）
            # =============================
            st.markdown(f"""
            <div style="
            background:#131722;
            border:1px solid #2A2E39;
            border-radius:12px;
            padding:20px;
            ">

            <h2 style="color:{color}; text-align:center; margin:0;">
            {rec}
            </h2>

            <p style="text-align:center; color:#9BA3AF;">
            綜合評分：{score}
            </p>

            <hr style="border:0.5px solid #2A2E39;">

            <div style="display:flex; justify-content:space-between;">

            <div>
            <p style="color:#9BA3AF;">趨勢</p>
            <p style="color:white;">{trend_label}</p>
            </div>

            <div>
            <p style="color:#9BA3AF;">動能</p>
            <p style="color:white;">{momo_label}</p>
            </div>

            <div>
            <p style="color:#9BA3AF;">心理</p>
            <p style="color:white;">{psy_label}</p>
            </div>

            <div>
            <p style="color:#9BA3AF;">籌碼</p>
            <p style="color:white;">{chip_label}</p>
            </div>

            <div>
            <p style="color:#9BA3AF;">ATR</p>
            <p style="color:white;">{atr_label}</p>
            </div>

            </div>
            </div>
            """, unsafe_allow_html=True)

            st.caption(f"""
            📌 判讀摘要：
            - 趨勢：{trend_label}
            - 動能：{momo_label}
            - 心理：RSI {curr_rsi:.1f}
            - 籌碼：{chip_label}
            - 風控：{atr_label}
            """)

# ==============================================================================
# Tab 4: 產經動態 (移入 Tab)
# ==============================================================================
with tab_news:
    if show_news and ticker_input:
        st.subheader("📰 台灣產經新聞")

        try:
            # =============================
            # 🔍 1. 關鍵字強化（核心升級）
            # =============================
            stock_code = ticker_input.split('.')[0]

            # 👉 你可以自己維護這個 mapping（非常重要）
            stock_map = {
                "2330": ["台積電", "TSMC", "半導體"],
                "2356": ["英業達", "Inventec", "電子代工"],
                "2618": ["長榮航", "EVA", "交通空運"]
            }

            keywords = [stock_code]

            if stock_code in stock_map:
                keywords += stock_map[stock_code]

            # =============================
            # 🧠 2. 多關鍵字搜尋（提高命中率）
            # =============================
            all_news = []

            for kw in keywords:
                df_tmp = fetch_news_data_cached(kw)
                if df_tmp is not None and not df_tmp.empty:
                    all_news.append(df_tmp)

            # 合併
            if all_news:
                df_news = pd.concat(all_news, ignore_index=True)
            else:
                df_news = pd.DataFrame()

            # =============================
            # 🔄 3. fallback（抓產業新聞）
            # =============================
            if df_news.empty:
                st.warning("⚠️ 個股新聞較少，改為顯示產業新聞")

                fallback_keywords = ["台股", "半導體", "電子產業"]

                for kw in fallback_keywords:
                    df_tmp = fetch_news_data_cached(kw)
                    if df_tmp is not None and not df_tmp.empty:
                        df_news = df_tmp
                        break

            # =============================
            # 📊 4. 整理資料
            # =============================
            if not df_news.empty:
                df_news = df_news.drop_duplicates(subset=['title'], keep='first')

                if 'date' in df_news.columns:
                    df_news = df_news.sort_values(by='date', ascending=False)

                # =============================
                # 🎨 5. UI 優化（專業版）
                # =============================
                for _, row in df_news.head(8).iterrows():

                    date_str = row.get('date', '')[:10]
                    title = row.get('title', '無標題')
                    summary = row.get('summary', '無摘要')
                    link = row.get('link', '#')

                    st.markdown(f"""
                    <div style="
                        background:#131722;
                        border:1px solid #2A2E39;
                        border-radius:10px;
                        padding:12px;
                        margin-bottom:8px;
                    ">
                        <p style="color:#9BA3AF; font-size:12px; margin:0;">
                            {date_str}
                        </p>
                        <p style="color:white; font-size:14px; margin:5px 0;">
                            {title}
                        </p>
                        <p style="color:#9BA3AF; font-size:13px;">
                            {summary}
                        </p>
                        <a href="{link}" target="_blank" style="color:#4FC3F7;">
                            查看全文 →
                        </a>
                    </div>
                    """, unsafe_allow_html=True)

            else:
                st.info("⚠️ 目前沒有相關新聞資料")

        except Exception as e:
            st.error(f"新聞抓取失敗：{e}")
