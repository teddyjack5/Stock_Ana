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

# ==========================================
# 0. 核心配置與資料庫工具函數
# ==========================================
def hash_password(password):
    if not password: return None
    return hashlib.sha256(password.encode()).hexdigest()

def load_db(filename):
    """載入庫存 JSON 檔案並處理舊版相容性"""
    default_data = {
        "password_hash" : None,
        "list": {"2356.TW": "英業達", "0050.TW": "元大台灣50"},
        "costs": {
            "2356.TW": {"cost": 49.0, "qty": 1.0},
            "0050.TW": {"cost": 70.0, "qty": 1.0}
        }
    }
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                content = json.load(f)
                # 自動轉換舊格式
                if "groups" in content:
                    first_group_name = list(content["groups"].keys())[0]
                    st.toast(f"🔄 偵測到舊版格式，已自動轉換帳戶")
                    return {
                        "list": content["groups"][first_group_name].get("list", {}),
                        "costs": content["groups"][first_group_name].get("costs", {}),
                        "password_hash": None
                    }
                content.setdefault("list", {})
                content.setdefault("costs", {})
                return content
        except Exception as e:
            st.error(f"讀取 JSON 出錯: {e}")
            return default_data
    return default_data

def save_db(data, filename):
    """儲存資料至 JSON 檔案"""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ==========================================
# 1. 互動式對話框 (Dialogs)
# ==========================================
@st.dialog("📋 全帳戶個股損益明細", width="large")
def show_full_portfolio_report(active_costs, active_list):
    """顯示完整的投資組合損益清單"""
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

@st.dialog("➕ 新增股票至清單")
def add_stock_dialog(db_file):
    """新增股票代號與名稱"""
    col1, col2 = st.columns(2)
    new_id = col1.text_input("股票代號", placeholder="2330.TW").upper()
    new_name = col2.text_input("股票名稱", placeholder="台積電")
    
    st.write("---")
    c1, c2 = st.columns(2)
    if c1.button("取消", use_container_width=True): st.rerun()
    if c2.button("確認加入", type="primary", use_container_width=True):
        if new_id and new_name:
            st.session_state.db["list"][new_id] = new_name
            save_db(st.session_state.db, db_file)
            st.balloons()
            st.toast(f"✅ 已成功加入 {new_name}", icon="💰")
            st.rerun()
        else:
            st.error("請完整填寫代號與名稱")

@st.dialog("⚠️ 刪除確認")
def delete_confirm_dialog(ticker, name, db_file):
    """二次確認刪除動作"""
    st.warning(f"確定要從庫存中刪除 **{name} ({ticker})** 嗎？此動作無法復原。")
    c1, c2 = st.columns(2)
    if c1.button("取消", use_container_width=True): st.rerun()
    if c2.button("確認刪除", type="primary", use_container_width=True):
        st.session_state.db["list"].pop(ticker, None)
        st.session_state.db["costs"].pop(ticker, None)
        save_db(st.session_state.db, db_file)
        st.toast(f"🗑️ 已成功刪除 {name}", icon="🔥")
        st.rerun()

@st.dialog("🚀 全台股法人強勢掃描器", width="large")
def professional_scan_dialog():
    st.write("### 🎯 專業經理人佈局清單")
    st.info("策略邏輯：投信單日買超張數排行 + 股價站穩月線 (MA20)")
    
    # --- 關鍵修正：在函數內初始化 DataLoader ---
    # 這樣可以確保掃描時 API 物件是活著的
    local_dl = DataLoader()
    try:
        local_dl.set_token(token=FINMIND_TOKEN) # 使用外層定義的 TOKEN
    except:
        pass

    try:
        check_date = datetime.now()
        # 下午 3 點後才有當日資料，否則抓前一天
        if check_date.hour < 15:
            check_date -= timedelta(days=1)
        
        # 避開週六與週日
        if check_date.weekday() == 5: # 週六
            check_date -= timedelta(days=1)
        elif check_date.weekday() == 6: # 週日
            check_date -= timedelta(days=2)
            
        target_date = check_date.strftime('%Y-%m-%d')
        st.caption(f"📅 分析基準日：{target_date}")

        with st.spinner("正在掃描法人動向..."):
            # 使用 local_dl 進行抓取
            raw_data = local_dl.taiwan_stock_institutional_investors(
                start_date=target_date,
                end_date=target_date
            )
            
            # 處理 FinMind 回傳格式 (有些版本回傳 dict, 有些回傳 DataFrame)
            if isinstance(raw_data, dict):
                if 'data' in raw_data:
                    df_inst = pd.DataFrame(raw_data['data'])
                else:
                    # 如果 dict 裡沒 'data'，試著直接轉
                    df_inst = pd.DataFrame(raw_data)
            else:
                df_inst = raw_data
        
        if df_inst is None or df_inst.empty:
            st.warning("⚠️ 沒找到法人資料。可能原因：交易所尚未公佈，或今日非交易日。")
            return

        # 篩選投信 (Investment_Trust)
        it_buys = df_inst[
            (df_inst['name'] == 'Investment_Trust') & 
            (df_inst['buy'] > 0)
        ].copy()
        
        if it_buys.empty:
            st.warning("今日投信似乎沒有明顯的買超標的。")
            return

        it_buys['buy_sheets'] = it_buys['buy'] // 1000
        it_top = it_buys.nlargest(15, 'buy_sheets')
        
        results = []
        p_bar = st.progress(0)
        
        for i, (idx, row) in enumerate(it_top.iterrows()):
            stock_id = str(row['stock_id'])
            full_ticker = f"{stock_id}.TW" if ".TW" not in stock_id else stock_id
                
            try:
                # 這裡不變，維持 yfinance 驗證
                df_p = yf.download(full_ticker, period="20d", progress=False)
                if len(df_p) < 15: continue
                
                c_price = float(df_p['Close'].iloc[-1])
                ma20 = float(df_p['Close'].rolling(20).mean().iloc[-1])
                
                if c_price > ma20:
                    results.append({
                        "代號": full_ticker,
                        "買超(張)": int(row['buy_sheets']),
                        "目前價格": f"{c_price:.2f}",
                        "技術狀態": "✅ 月線上強勢"
                    })
            except: continue
            p_bar.progress((i + 1) / len(it_top))

        if results:
            st.success(f"掃描完畢！共 {len(results)} 檔。")
            st.table(pd.DataFrame(results))
        else:
            st.info("今日投信買超股目前技術面較弱，建議觀望。")
            
    except Exception as e:
        st.error(f"掃描過程發生錯誤: {e}")

    if st.button("關閉視窗", use_container_width=True, key="btn_close_pro_scan_v3"):
        st.rerun()

# ==========================================
# 2. 系統初始化與 API 設定
# ==========================================
st.set_page_config(page_title="小鐵的股票分析報告", layout="wide")
st.title("📈 小鐵的股票分析報告")

FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNi0wMS0yOCAwODoyNToyNyIsInVzZXJfaWQiOiJ0ZWRkeWphY2siLCJlbWFpbCI6InRlZGR5amFjazVAeWFob28uY29tLnR3IiwiaXAiOiI0Mi43Mi4yMTEuMTUzIn0.Su4W8X5E9XPN9PZdA03Z6XO6i630kOSvOjcrLowcO-I"
dl = DataLoader()
try: dl.set_token(token=FINMIND_TOKEN)
except: pass

if 'db' not in st.session_state:
    st.session_state.db = {"password_hash": None, "list": {}, "costs": {}}
    st.session_state.current_file = None

# ==========================================
# 3. 側邊欄：帳戶管理與安全性
# ==========================================
st.sidebar.title("📁 帳戶與庫存")

# 帳戶檔案切換
db_files = [f for f in os.listdir('.') if f.endswith('.json') and f != "package.json"]
if not db_files: db_files = ["my_stock_db.json"]
current_db_file = st.sidebar.selectbox("📂 切換帳戶庫存", db_files)

# 檔案切換偵測
if st.session_state.current_file != current_db_file:
    st.session_state.db = load_db(current_db_file)
    st.session_state.current_file = current_db_file

# 新增帳戶
new_db_name = st.sidebar.text_input("➕ 建立新帳戶名稱", placeholder="例如: 退休基金")
if st.sidebar.button("建立新帳戶"):
    if new_db_name:
        full_name = f"{new_db_name}.json" if not new_db_name.endswith('.json') else new_db_name
        save_db({"list": {}, "costs": {}}, full_name)
        st.rerun()

# 刪除帳戶 (危險區域)
with st.sidebar.expander("🗑️ 危險區域 (刪除帳戶)"):
    st.warning(f"確定要刪除【{current_db_file}】？")
    if st.checkbox("我確定要永久刪除", key="confirm_del_db"):
        if st.button("💥 執行刪除", type="primary"):
            if len(db_files) > 1:
                os.remove(current_db_file)
                st.session_state.current_file = None
                st.rerun()
            else: st.error("至少需保留一個帳戶")

st.sidebar.divider()

# 密碼驗證邏輯
is_authenticated = False
if st.session_state.db.get("password_hash") is None:
    st.sidebar.info("🔓 此帳戶尚未設置密碼")
    if st.sidebar.checkbox("🔒 設置 4 位數密碼"):
        new_pwd = st.sidebar.text_input("輸入新密碼", type="password", max_chars=4)
        if st.sidebar.button("確認設置"):
            st.session_state.db["password_hash"] = hash_password(new_pwd)
            save_db(st.session_state.db, current_db_file)
            st.rerun()
    is_authenticated = True
else:
    input_pwd = st.sidebar.text_input("🔑 輸入 4 位數密碼", type="password", max_chars=4)
    if input_pwd and hash_password(input_pwd) == st.session_state.db["password_hash"]:
        is_authenticated = True
    elif input_pwd: st.sidebar.error("❌ 密碼錯誤")

if not is_authenticated:
    st.warning("🔒 請輸入密碼以開啟報告")
    st.stop()

# ==========================================
# 4. 主介面：資產總覽卡片
# ==========================================
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

st.write(f"### 🏢 帳戶總覽：{current_db_file.replace('.json', '')}")
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

# ==========================================
# 5. 側邊欄：庫存管理與選取
# ==========================================
st.sidebar.subheader("⚙️ 庫存管理")
if st.sidebar.button("➕ 新增股票項目", use_container_width=True):
    add_stock_dialog(current_db_file)

if st.sidebar.button("🔍 查看全帳戶明細", use_container_width=True):
    show_full_portfolio_report(active_costs, active_list)

st.sidebar.write("---")

# 股票選取與同步
def sync_stock_data():
    t_key = st.session_state.get('selected_ticker_key')
    acc = st.session_state.db["costs"].get(t_key, {"cost": 0.0, "qty": 0.0})
    st.session_state.buy_cost = float(acc['cost'])
    st.session_state.buy_qty = float(acc['qty'])

selected_ticker = st.sidebar.selectbox(
    "選取庫存個股", list(active_list.keys()), 
    format_func=lambda x: f"{x} {active_list[x]}",
    key="selected_ticker_key", on_change=sync_stock_data
)

if selected_ticker:
    if st.sidebar.button(f"🗑️ 刪除 {selected_ticker}", use_container_width=True):
        delete_confirm_dialog(selected_ticker, active_list.get(selected_ticker), current_db_file)

st.sidebar.write("---")
custom_search = st.sidebar.text_input("🔍 全域搜尋 (不加入庫存)", "")
ticker_input = custom_search if custom_search else selected_ticker
period = st.sidebar.selectbox("分析時間範圍", ["5d", "1mo", "6mo", "1y", "2y"], index=2)

# 帳務設定
st.sidebar.subheader(f"💰 {ticker_input} 帳務管理")
if "buy_cost" not in st.session_state: sync_stock_data()
u_cost = st.sidebar.number_input("買入單價", key="buy_cost", step=0.1)
u_qty = st.sidebar.number_input("持有張數", key="buy_qty", step=1.0)

if st.sidebar.button("💾 儲存帳務修改"):
    st.session_state.db["costs"][ticker_input] = {"cost": u_cost, "qty": u_qty}
    save_db(st.session_state.db, current_db_file)
    st.sidebar.success("帳務已更新")
    st.rerun()

#智能選股區
st.sidebar.divider()
st.sidebar.subheader("🚀 智能雷達")

# 判斷收盤狀態
now = datetime.now()
is_after_market = now.hour >= 15 # 下午三點後法人數據較完整

button_label = "🔥 查看今日強勢清單" if is_after_market else "⏳ 預覽昨日強勢清單"
if st.sidebar.button(button_label, use_container_width=True, type="primary"):
    professional_scan_dialog()

if is_after_market:
    st.sidebar.caption("✅ 今日收盤數據已就緒")
else:
    st.sidebar.caption("💡 下午 3:00 後將更新今日數據")

show_news = st.sidebar.checkbox("顯示相關新聞", value=True)

# ==========================================
# 6. 技術指標計算函數集
# ==========================================
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

# ==========================================
# 7. 數據處理、繪圖與 AI 診斷區
# ==========================================
if ticker_input:
    data = yf.download(ticker_input, period=period)
    if not data.empty:
        # 數據清理與計算
        if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
        data['MACD'], data['Signal'], data['Hist'] = calculate_macd(data)
        data['ATR'] = calculate_atr(data)
        data['RSI'] = calculate_rsi(data)
        data['MA5'] = data['Close'].rolling(5).mean()
        data['MA20'] = data['Close'].rolling(20).mean()
        data['MA60'] = data['Close'].rolling(60).mean()
        data['ATR_Trailing'] = data['Close'].rolling(20).max() - (data['ATR'] * 2)
        
        curr, prev = data.iloc[-1], data.iloc[-2]
        price = float(curr['Close'])

        # 個股損益試算
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
            i2.metric("投入本金", f"NT$ {int(c*q*1000):,}")
            i3.metric("目前市值", f"NT$ {int(price*q*1000):,}")

        # 指標儀表板
        st.subheader(f"📊 {ticker_input} {active_list.get(ticker_input, '')} 即時概況")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("當前股價", f"{price:.2f}", f"{price - float(prev['Close']):.2f}", delta_color="inverse")
        m2.metric("60日高點", f"{data['High'].tail(60).max():.2f}")
        m3.metric("5MA", f"{float(curr['MA5']):.2f}")
        m4.metric("20MA", f"{float(curr['MA20']):.2f}")
        m5.metric("60MA", f"{float(curr['MA60']):.2f}")
        m6.metric("RSI(14)", f"{float(curr['RSI']):.1f}")

        # 法人籌碼
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

        # 外資持股與月營收圖表
        df_hold = get_foreign_holding(ticker_input)
        if not df_hold.empty:
            st.write("---")
            st.subheader("🏛️ 外資持股中長期變動")
            fig_h = make_subplots(specs=[[{"secondary_y": True}]])
            fig_h.add_trace(go.Scatter(x=data.index, y=data['Close'], name="股價", line=dict(color='gray', width=1)), secondary_y=False)
            fig_h.add_trace(go.Scatter(x=df_hold['date'], y=df_hold['ForeignInvestmentSharesRatio'], name="外資持股%", fill='tozeroy', line=dict(color='#00CCFF')), secondary_y=True)
            fig_h.update_layout(height=400, template="plotly_dark")
            st.plotly_chart(fig_h, use_container_width=True)

        df_rev = get_monthly_revenue(ticker_input)
        if not df_rev.empty:
            st.write("---")
            st.subheader("📈 月營收成長趨勢")
            st.info("💡 **觀查重點**：長條圖代表營收絕對值，紅色折線為 **YoY (年增率)**。若 YoY 持續大於 0 且向上，代表公司處於成長期。")
            df_rev['yoy'] = df_rev['revenue'].pct_change(12) * 100
            fig_r = go.Figure()
            fig_r.add_trace(go.Bar(x=df_rev['date'], y=df_rev['revenue'], name="營收", marker_color='rgba(0, 255, 150, 0.4)'))
            fig_r.add_trace(go.Scatter(x=df_rev['date'], y=df_rev['yoy'], name="年增率", line=dict(color='red'), yaxis="y2"))
            fig_r.update_layout(height=400, template="plotly_dark", yaxis2=dict(overlaying="y", side="right"))
            st.plotly_chart(fig_r, use_container_width=True)
            latest_rev = df_rev['revenue'].iloc[-1] / 100000000
            latest_yoy = df_rev['yoy'].iloc[-1]
            st.info(f"📊 **營收速報**：本月營收為 **{latest_rev:.2f} 億**，較去年同期{'成長' if latest_yoy > 0 else '衰退'} **{abs(latest_yoy):.2f}%**。")

        # 核心 K 線圖
        st.write("---")
        st.subheader(f"📊 {ticker_input} 技術指標全覽")

        # 建立多子圖
        fig_main = make_subplots(
            rows=4, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.06, 
            row_width=[0.2, 0.2, 0.2, 0.4]
        )

        # --- 第 1 欄：K線與多條均線 ---
        # 1. K線圖
        fig_main.add_trace(go.Candlestick(
            x=data.index, open=data['Open'], high=data['High'], 
            low=data['Low'], close=data['Close'], name="K線"
        ), row=1, col=1)

        # 2. 5日均線 (週線) - 使用白色或淺粉色
        fig_main.add_trace(go.Scatter(x=data.index, y=data['MA5'], name="5MA", line=dict(color='#FFFFFF', width=1.5)), row=1, col=1)
        
        # 3. 20日均線 (月線) - 維持橘色
        fig_main.add_trace(go.Scatter(x=data.index, y=data['MA20'], name="20MA", line=dict(color='orange', width=1.5)), row=1, col=1)
        
        # 4. 60日均線 (季線) - 使用亮綠色
        fig_main.add_trace(go.Scatter(x=data.index, y=data['MA60'], name="60MA", line=dict(color='#00FF00', width=1.5)), row=1, col=1)

        # 5. ATR 止損線 - 改為【亮紫色】且【加粗實線】或【明顯虛線】
        fig_main.add_trace(go.Scatter(
            x=data.index, y=data['ATR_Trailing'], 
            name="ATR止損線", 
            line=dict(color='#FF00FF', width=2, dash='longdash') # 👈 亮紫色，長虛線
        ), row=1, col=1)

        # --- 第 2 欄：成交量 ---
        fig_main.add_trace(go.Bar(
            x=data.index, 
            y=data['Volume'], 
            name="成交量", 
            marker_color='rgba(31, 119, 180, 0.7)' # 👈 經典券商藍，0.7 的透明度讓質感更好
        ), row=2, col=1)
        fig_main.add_trace(go.Bar(x=data.index, y=data['Volume'], name="成交量", marker_color='rgba(128,128,128,0.5)'), row=2, col=1)

        # --- 第 3 欄：RSI ---
        fig_main.add_trace(go.Scatter(x=data.index, y=data['RSI'], name="RSI", line=dict(color='yellow')), row=3, col=1)

        # --- 第 4 欄：MACD ---
        fig_main.add_trace(go.Scatter(x=data.index, y=data['MACD'], name="MACD", line=dict(color='#00CCFF')), row=4, col=1)

        # --- 佈局優化 ---
        fig_main.update_layout(
            height=900, 
            template="plotly_dark", 
            xaxis_rangeslider_visible=False,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=60, b=10),
            yaxis1=dict(title="股價"),
            yaxis2=dict(title="成交量"),
            yaxis3=dict(title="RSI"),
            yaxis4=dict(title="MACD")
        )

        st.plotly_chart(fig_main, use_container_width=True)

        latest_rsi = data['RSI'].iloc[-1]
        latest_macd = data['MACD'].iloc[-1]
        latest_signal = data['Signal'].iloc[-1]
        latest_hist = data['Hist'].iloc[-1]
        prev_hist = data['Hist'].iloc[-2]

        diag_rsi, diag_macd = st.columns(2)

        with diag_rsi:
            if latest_rsi > 70:
                st.error(f"🟡 **RSI：目前 {latest_rsi:.1f} (超買過熱)**")
                st.caption("建議：股價進入過熱區，短線不宜追高，留意反轉風險。")
            elif latest_rsi < 30:
                st.success(f"🔵 **RSI：目前 {latest_rsi:.1f} (超跌機會)**")
                st.caption("建議：股價進入超跌區，賣壓可能竭盡，可留意築底買點。")
            else:
                st.info(f"⚪ **RSI：目前 {latest_rsi:.1f} (盤整中性)**")
                st.caption("建議：力道穩定，暫無明顯超買或超跌現象。")

        with diag_macd:
            # 判斷 MACD 柱狀體趨勢
            if latest_hist > 0 and latest_hist > prev_hist:
                st.success(f"📈 **MACD：多頭動能轉強**")
                st.caption("建議：紅柱持續增長，股價處於攻擊波段。")
            elif latest_hist > 0 and latest_hist <= prev_hist:
                st.warning(f"⚠️ **MACD：多頭動能減弱**")
                st.caption("建議：紅柱縮減，漲勢可能趨緩，留意高檔震盪。")
            elif latest_hist < 0 and latest_hist < prev_hist:
                st.error(f"📉 **MACD：空頭動能擴大**")
                st.caption("建議：綠柱增長，趨勢偏弱，建議多看少動。")
            else:
                st.info(f"🔄 **MACD：跌勢收斂**")
                st.caption("建議：綠柱縮減，空方力道減弱，等待金叉轉強訊號。")

        # --- AI 診斷 ---
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

        # --- 綜合總結建議 ---
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





