import streamlit as st
import pandas as pd
import datetime
import os
from streamlit_gsheets import GSheetsConnection
from src.calc import predict_single_house, aggregate_shipments, adjust_to_shipping_days

# --- Page Config ---
st.set_page_config(page_title="スプレーマム出荷予測", layout="wide")

st.title("🌱 スプレーマム出荷予測アプリ")

# --- Sidebar: Common Settings ---
st.sidebar.header("共通設定")

# 1. Shipping Adjustment
st.sidebar.subheader("出荷日調整")
enable_shipping_adjust = st.sidebar.checkbox("月・水・土 集約", value=True, help="出荷予測日を月・水・土曜日に寄せます (日,月->月 / 火,水->水 / 木,金,土->土)")

# 2. Seasonal Coefficients
st.sidebar.subheader("基本係数 (季節別)")
st.sidebar.caption("収穫予定日に応じて適用されます")
col_season1, col_season2 = st.sidebar.columns(2)
with col_season1:
    coeff_spring = st.number_input("春 (3-5月)", value=1.5, step=0.1, key="coeff_spring")
    coeff_summer = st.number_input("夏 (6-8月)", value=1.4, step=0.1, key="coeff_summer")
with col_season2:
    coeff_autumn = st.number_input("秋 (9-11月)", value=1.3, step=0.1, key="coeff_autumn")
    coeff_winter = st.number_input("冬 (12-2月)", value=1.2, step=0.1, key="coeff_winter")

seasonal_coeffs = {
    3: coeff_spring, 4: coeff_spring, 5: coeff_spring,
    6: coeff_summer, 7: coeff_summer, 8: coeff_summer,
    9: coeff_autumn, 10: coeff_autumn, 11: coeff_autumn,
    12: coeff_winter, 1: coeff_winter, 2: coeff_winter
}

def get_coeff_for_date(target_date: datetime.date) -> float:
    return seasonal_coeffs.get(target_date.month, 1.2)

# 2. Distribution Ratio (14 inputs)
# 2. Distribution Ratio
st.sidebar.subheader("出荷分配率")
pattern_type = st.sidebar.radio("パターン選択", ["14日間", "9日間"], index=1)

if pattern_type == "9日間":
    days_count = 9
    # Default 9-day pattern (User provided)
    current_defaults = [
        0.0224, 0.1269, 0.2148, 0.2218, 0.1746, 0.1212, 0.0783, 0.0325, 0.0075
    ]
    key_prefix = "9d"
else:
    days_count = 14
    # Default 14-day pattern (User provided)
    current_defaults = [
        0.0314, 0.0952, 0.1404, 0.1543, 0.1442, 0.1218, 0.0958,
        0.0716, 0.0515, 0.0358, 0.0244, 0.0162, 0.0106, 0.0068
    ]
    key_prefix = "14d"

st.sidebar.caption("合計が1になるようにしてください")
ratio_cols = st.sidebar.columns(2)

user_ratios = []
for i in range(days_count):
    col = ratio_cols[i % 2]
    val = col.number_input(
        f"{i+1}日目", 
        min_value=0.0, 
        max_value=1.0, 
        value=current_defaults[i],
        step=0.01,
        format="%.4f",
        key=f"ratio_{key_prefix}_{i}"
    )
    user_ratios.append(val)

# Normalize Check
total_ratio = sum(user_ratios)
if not (0.999 < total_ratio < 1.001):
    st.sidebar.warning(f"合計が {total_ratio:.3f} です。正規化して計算します。")
    normalized_ratios = [r / total_ratio for r in user_ratios]
else:
    normalized_ratios = user_ratios


# --- Main Content ---
# Previously Tab 2 (Aggregation) is now the main view
st.header("複数ハウス集計")


# Template for manual entry
default_data = [
    {
        "producer": "テスト生産者",
        "house_name": "A-1", 
        "variety": "ピンク", 
        "color": "ピンク",
        "shape": "シングル",
        "area_tsubo": 100, 
        "blackout_date": datetime.date.today(),
        "coeff": None, # Should auto-calc
        "weeks": 7
    },
    {
        "producer": "テスト生産者",
        "house_name": "B-2", 
        "variety": "ホワイト", 
        "color": "白",
        "shape": "デコラ",
        "area_tsubo": 150, 
        "blackout_date": datetime.date.today() + datetime.timedelta(days=5),
        "coeff": None, # Should auto-calc
        "weeks": 7
    }
]

# --- Local Data Persistence ---
DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "master_data.csv")

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def load_local_data():
    if os.path.exists(DATA_FILE):
        try:
            df = pd.read_csv(DATA_FILE)
            if 'blackout_date' in df.columns:
                # Force conversion to date objects (handled as object in DF, but specific type for Streamlit)
                # Streamlit DateColumn expects date objects or strings YYYY-MM-DD.
                # Mix of string/date causes issues. Let's standardize to date objects.
                df['blackout_date'] = pd.to_datetime(df['blackout_date'], errors='coerce').dt.date
            
            if 'producer' in df.columns:
                 df['producer'] = df['producer'].fillna("").astype(str)
            else:
                 df['producer'] = ""

            return df
        except:
            return pd.DataFrame(default_data)
    else:
        return pd.DataFrame(default_data)

def save_local_data(df):
    ensure_data_dir()
    df.to_csv(DATA_FILE, index=False)

def merge_datasets(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """

    Merges new_df into existing_df based on key columns: producer, house_name, variety, blackout_date.
    Updates existing records, appends new ones.
    """
    # Helper to standardize DATE column for merging
    def standardize_date(df):
        d = df.copy()
        # Convert blackout_date to datetime.date object if possible, or ISO string
        # Safer to use ISO string for indexing/matching? Or object.
        # Let's try to convert to datetime then date.
        d['blackout_date'] = pd.to_datetime(d['blackout_date'], errors='coerce').dt.date
        return d

    if new_df.empty:
        return existing_df
    if existing_df.empty:
        # Must standardize new_df before returning to ensure types match app expectations
        new_std = standardize_date(new_df)
        if 'producer' not in new_std.columns:
            new_std['producer'] = ""
        new_std['producer'] = new_std['producer'].fillna("")
        return new_std
        
    # Ensure keys are consistent (str, date object)
    # Added "producer" to key. If missing in old data, fill with "".
    key_cols = ['producer', 'house_name', 'variety', 'blackout_date']
    
    if 'producer' not in existing_df.columns:
        existing_df['producer'] = ""
    if 'producer' not in new_df.columns:
        new_df['producer'] = ""
    
    # Fill NaN producer with empty string to avoid matching issues
    existing_df['producer'] = existing_df['producer'].fillna("")
    new_df['producer'] = new_df['producer'].fillna("")
    
    old_std = standardize_date(existing_df)
    new_std = standardize_date(new_df)
    
    # Set index
    old_std.set_index(key_cols, inplace=True)
    new_std.set_index(key_cols, inplace=True)
    
    # Update old with new
    # update() modifies in place, aligning on index.
    old_std.update(new_std)
    
    # Append rows that are in new but not in old
    # Identify new indices
    new_indices = new_std.index.difference(old_std.index)
    to_append = new_std.loc[new_indices]
    
    final_df = pd.concat([old_std, to_append])
    
    return final_df.reset_index()

# Initialize Session State for Data
if 'master_df' not in st.session_state:
    st.session_state['master_df'] = load_local_data()

# --- Bulk Edit Sidebar ---
with st.sidebar.expander("一括編集 (データ修正)", expanded=False):
    st.caption("選択した条件のデータを一括で変更します")
    
    # Filters
    master_df = st.session_state['master_df']
    if not master_df.empty:
        if 'producer' not in master_df.columns:
            master_df['producer'] = ""
            
        # 0. Producer Selection
        producers = ["全て"] + list(master_df['producer'].unique())
        target_producer = st.selectbox("生産者を選択", producers)

        # 1. House Selection
        houses = ["全て"] + list(master_df['house_name'].unique())
        target_house = st.selectbox("ハウスを選択", houses)
        
        # 2. Variety Selection
        varieties = ["全て"] + list(master_df['variety'].unique())
        target_variety = st.selectbox("品種を選択", varieties)
        
        st.divider()
        
        # Actions
        adj_weeks = st.number_input("週数を増減 (週)", value=0.0, step=0.5, format="%.1f")
        adj_days = st.number_input("消灯日をシフト (日)", value=0, step=1)
        
        if st.button("適用 (一括変更)"):
            # Apply changes
            mask = pd.Series([True] * len(master_df))
            if target_producer != "全て":
                mask &= (master_df['producer'] == target_producer)
            if target_house != "全て":
                mask &= (master_df['house_name'] == target_house)
            if target_variety != "全て":
                mask &= (master_df['variety'] == target_variety)
            
            # Update Weeks
            if adj_weeks != 0:
                 # Ensure numeric first
                 master_df.loc[mask, 'weeks'] = pd.to_numeric(master_df.loc[mask, 'weeks'], errors='coerce').fillna(7.0)
                 master_df.loc[mask, 'weeks'] += adj_weeks
            
            # Update Date
            if adj_days != 0:
                # Ensure date
                # We need to handle mixed types safely. DataEditor usually keeps them as strings or dates depending on config.
                # Let's try to convert to datetime, add, then back to object if needed?
                # Best to ensure 'blackout_date' is datetime/date object in the DF
                try:
                    current_dates = pd.to_datetime(master_df.loc[mask, 'blackout_date'])
                    new_dates = current_dates + datetime.timedelta(days=adj_days)
                    # Store back as string YYYY-MM-DD or date object
                    master_df.loc[mask, 'blackout_date'] = new_dates.dt.date
                except Exception as e:
                    st.error(f"日付変換エラー: {e}")
            
            st.session_state['master_df'] = master_df
            save_local_data(master_df)
            st.success("更新しました！")
            st.rerun()





def merge_and_switch_callback(new_df):
    """Callback to merge external data and switch view."""
    current_master = st.session_state.get('master_df', pd.DataFrame())
    merged_df = merge_datasets(current_master, new_df)
    
    st.session_state['master_df'] = merged_df
    save_local_data(merged_df)
    # Switch view by updating the session state key for the radio widget
    st.session_state['input_method'] = "画面入力(ローカル保存)"
    # st.success is tricky in callback (it might show up on next run or not). 
    # But usually notifications should be persistent or we can't easily show it *before* switch.
    # The switch itself is the feedback.

input_method = st.radio("入力方法", ["画面入力(ローカル保存)", "CSVアップロード", "Googleスプレッドシート"], key="input_method")

input_df = None

if input_method == "画面入力(ローカル保存)":
    # Ensure column order for display
    display_cols = ["producer", "house_name", "variety", "blackout_date", "color", "shape", "area_tsubo", "weeks", "coeff"]
    
    # Reorder master_df if it has these columns (handling potential missing ones gracefully)
    # Sort columns: display_cols first, then any others
    # We will pass this to column_order, not modify the DF itself to avoid reset issues
    all_cols = st.session_state['master_df'].columns.tolist()
    final_col_order = [c for c in display_cols if c in all_cols] + [c for c in all_cols if c not in display_cols]

    # Ensure types for Editor (Safe check - do once or check if needed)
    if 'producer' in st.session_state['master_df'].columns:
        pass

    # Use session state dataframe
    # key="editor" -> Data is accessible via st.session_state["editor"] in the callback
    # Use session state dataframe
    edited_df = st.data_editor(
        st.session_state['master_df'],
        num_rows="dynamic",
        column_order=final_col_order,
        column_config={
            "producer": st.column_config.TextColumn("生産者"),
            "house_name": st.column_config.TextColumn("ハウス名"),
            "variety": st.column_config.TextColumn("品種"),
            "blackout_date": st.column_config.DateColumn("消灯日", format="YYYY-MM-DD"),
            "color": st.column_config.TextColumn("花色"),
            "shape": st.column_config.TextColumn("花形"),
            "weeks": st.column_config.NumberColumn("週数", min_value=1.0, max_value=20.0, step=0.5, format="%.1f"),
            "coeff": st.column_config.NumberColumn("係数", format="%.1f"),
        },
        key="editor"
    )
    
    col_save, col_clear = st.columns([1, 1])
    with col_save:
        if st.button("変更を保存 (ファイル書き込み)", type="primary"):
            # Commit changes to session state AND file
            st.session_state['master_df'] = edited_df
            save_local_data(edited_df)
            st.success("保存しました！")
            st.rerun() # Refresh to reset editor with new base data
    
    input_df = edited_df
    
    with col_clear:
        # Reset Button with Confirmation
        if 'confirm_reset' not in st.session_state:
            st.session_state['confirm_reset'] = False

        if not st.session_state['confirm_reset']:
            if st.button("全データを消去 (リセット)", type="secondary"):
                st.session_state['confirm_reset'] = True
                st.rerun()
        else:
            st.warning("本当に全データを消去しますか？")
            col_res_1, col_res_2 = st.columns(2)
            with col_res_1:
                if st.button("はい、消去", type="primary"):
                    # Reset to default data (or empty structure)
                    cols = ["producer", "house_name", "variety", "blackout_date", "color", "shape", "area_tsubo", "weeks", "coeff"]
                    empty_df = pd.DataFrame(columns=cols)
                    
                    st.session_state['master_df'] = empty_df
                    save_local_data(empty_df)
                    st.session_state['confirm_reset'] = False
                    st.success("消去しました")
                    st.rerun()
            with col_res_2:
                if st.button("キャンセル"):
                    st.session_state['confirm_reset'] = False
                    st.rerun()
    
elif input_method == "Googleスプレッドシート":
    st.info("secrets.toml に設定されたGoogleスプレッドシートからデータを読み込みます。")
    
    # Create a connection object
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        # Read the data
        # If worksheet is named something else, specify `worksheet="SheetName"` in read() or secrets.
        # ttl=0 ensures we fetch fresh data on rerun/reload
        # You might want to cache it slightly if it's slow, but for "reflecting changes" immediately, ttl=0 or manual button is good.
        if st.button("スプレッドシートを再読み込み", key="reload_gsheet"):
            st.cache_data.clear()
            st.rerun()

        input_df = conn.read()
        
        # --- Logic Shared with CSV Upload (Normalization) ---
        if input_df is not None and not input_df.empty:
             # Support for Japanese Headers (Same as CSV)
            jp_map = {
                "生産者": "producer", "producer": "producer",
                "ハウス名": "house_name",
                "品種名": "variety", "品種": "variety",
                "面積": "area_tsubo", "面積(坪)": "area_tsubo", "面積（坪）": "area_tsubo",
                "消灯日": "blackout_date",
                "係数": "coeff",
                "週数": "weeks", "開花所要週数": "weeks",
                "花色": "color",
                "花形": "shape"
            }
            input_df = input_df.rename(columns=jp_map)
            
            # Basic validation similar to CSV
            required_cols = {'house_name', 'variety', 'area_tsubo', 'blackout_date'}
            if not required_cols.issubset(input_df.columns):
                 st.error(f"スプレッドシートに必要な列が不足しています: {required_cols - set(input_df.columns)}")
                 input_df = None


        if input_df is not None and not input_df.empty:
            st.button(
                "ローカル保存データに統合 (Merge)", 
                key="merge_gs_to_local",
                on_click=merge_and_switch_callback,
            )
            
        # Always allow saving to initialize an empty sheet
        st.divider()
        st.caption("※以下のボタンを押すと、現在アプリに表示されているデータをスプレッドシートに書き込みます（初期化にも使えます）。")
        if st.button("現在の全データをスプレッドシートに上書き保存", key="save_local_to_gs"):
            try:
                # Define Export Map
                export_map = {
                    "producer": "生産者",
                    "house_name": "ハウス名",
                    "variety": "品種",
                    "area_tsubo": "面積",
                    "blackout_date": "消灯日",
                    "coeff": "係数",
                    "weeks": "週数",
                    "color": "花色",
                    "shape": "花形"
                }
                
                # Prepare Data
                save_df = st.session_state['master_df'].copy()
                
                # Ensure Date format
                if 'blackout_date' in save_df.columns:
                    save_df['blackout_date'] = pd.to_datetime(save_df['blackout_date']).dt.strftime('%Y-%m-%d')
                
                # Rename
                save_df = save_df.rename(columns=export_map)
                
                # Write to Sheet
                conn.update(data=save_df)
                st.success("スプレッドシートに保存しました！")
                
            except Exception as e:
                st.error(f"保存エラー: {e}")



    except Exception as e:
        st.error(f"Googleスプレッドシート接続エラー: {e}")
        st.info("secrets.toml の設定や、シートの共有設定を確認してください。")
        input_df = None

else:
    st.subheader("ファイルアップロード")
    uploaded_file = st.file_uploader("ファイル (CSV/Excel) をアップロード", type=["csv", "xlsx"])

    st.info("CSV列順序 (ヘッダーなし/あり共通): house_name, variety, area_tsubo, blackout_date, coeff, weeks, color, shape")
    if uploaded_file:
        try:
            # DEBUG INFO
            st.write(f"Filename Code sees: {uploaded_file.name}")
            
            # Determine file type and read accordingly
            if uploaded_file.name.lower().endswith('.xlsx'):
                try:
                    # Determine header row dynamically
                    # Read first few rows without header
                    temp_df = pd.read_excel(uploaded_file, header=None, nrows=10)
                    header_row_idx = 0
                    
                    found_header = False
                    for i, row in temp_df.iterrows():
                        # Check if row contains key keywords
                        row_text = " ".join([str(x) for x in row.values])
                        if "品種" in row_text and ("ハウス" in row_text or "生産者" in row_text):
                            header_row_idx = i
                            found_header = True
                            break
                    
                    # Read with correct header
                    uploaded_file.seek(0)
                    input_df = pd.read_excel(uploaded_file, header=header_row_idx)
                    
                except Exception as e:
                    st.error(f"Excel読み込みエラー: {e}")
                    input_df = None
            else:
                # CSV logic (with fallback)
                try:
                    input_df = pd.read_csv(uploaded_file, encoding='utf-8')
                except UnicodeDecodeError:
                    uploaded_file.seek(0)
                    input_df = pd.read_csv(uploaded_file, encoding='cp932')
                except Exception as e:
                     st.error(f"CSV読み込みエラー: {e}")
                     input_df = None
            
            # Support for Japanese Headers (e.g. from Google Forms)
            
            # Support for Japanese Headers (e.g. from Google Forms)
            jp_map = {
                "生産者": "producer", "producer": "producer",
                "ハウス名": "house_name",
                "品種名": "variety", "品種": "variety",
                "面積": "area_tsubo", "面積(坪)": "area_tsubo", "面積（坪）": "area_tsubo",
                "消灯日": "blackout_date",
                "係数": "coeff",
                "週数": "weeks", "開花所要週数": "weeks",
                "花色": "color",
                "花形": "shape"
            }
            # Rename columns if they match keys
            input_df = input_df.rename(columns=jp_map)
            
            # Check if essential columns are present
            required_cols = {'house_name', 'variety', 'area_tsubo', 'blackout_date'}
            current_cols = set(input_df.columns)
            
            # If missing essential columns, try reading as headerless
            if not required_cols.issubset(current_cols):
                # Reset file pointer
                uploaded_file.seek(0)
                # Read without header
                input_df = pd.read_csv(uploaded_file, header=None)
                
                # Heuristic to detect column order
                # Schema A (Standard/Legacy): house_name(0), variety(1), area_tsubo(2), blackout_date(3), ...
                # Schema B (Grouped): house_name(0), variety(1), color(2), shape(3), area_tsubo(4), blackout_date(5), ...
                # New Schema C (With Producer): producer(0), house_name(1), ...? Or just append.
                # Let's assume standard A/B for headerless. If producer is needed, use header.
                
                def is_numeric_col(col_idx):
                    if col_idx >= input_df.shape[1]: return False
                    try:
                        pd.to_numeric(input_df.iloc[:, col_idx], errors='raise')
                        return True
                    except:
                        return False

                # Check Column 2
                if is_numeric_col(2):
                    # Likely Schema A
                    col_names = ["house_name", "variety", "area_tsubo", "blackout_date", "coeff", "weeks", "color", "shape"]
                elif is_numeric_col(4):
                    # Likely Schema B
                    col_names = ["house_name", "variety", "color", "shape", "area_tsubo", "blackout_date", "coeff", "weeks"]
                else:
                    # Fallback to Schema A
                        col_names = ["house_name", "variety", "area_tsubo", "blackout_date", "coeff", "weeks", "color", "shape"]

                num_cols = input_df.shape[1]
                if num_cols > len(col_names):
                    input_df.columns = col_names + [f"col_{i}" for i in range(len(col_names), num_cols)]
                else:
                    input_df.columns = col_names[:num_cols]

        except Exception as e:
            st.error(f"CSV読み込みエラー: {e}")
            input_df = None
            

    if input_df is not None and not input_df.empty:
         st.button(
             "ローカル保存データに統合 (Merge)", 
             key="merge_csv_to_local",
             on_click=merge_and_switch_callback,
             args=(input_df,)
         )

    if input_df is not None:
        # Ensure date column is datetime (Header based or Headerless logic converges here)
        if 'blackout_date' in input_df.columns:
            # Note: Actual date parsing logic will happen inside the loop or we can do it here for validation.
            # But previously existing logic did it inside loop or just ensured column existence.
            # The previous code tried to convert it here:
            # input_df['blackout_date'] = pd.to_datetime(input_df['blackout_date']).dt.date
            # But we changed logic to handle it in loop safely. Let's just keep the column check or skip.
            pass
        
        # Fill missing coeff with None to trigger auto-calc in loop if possible, 
        # OR we handle it directly in loop effectively.
        if 'coeff' not in input_df.columns:
            input_df['coeff'] = pd.NA
        
        # Fill missing weeks
        if 'weeks' not in input_df.columns:
            input_df['weeks'] = 7
        else:
            input_df['weeks'] = input_df['weeks'].fillna(7)

# --- Calculation Trigger ---

if input_df is not None and not input_df.empty:
    col_dl, col_calc = st.columns([1, 1])
    with col_dl:
        # Download Input Data as CSV
        csv_input = input_df.to_csv(index=False).encode('utf-8_sig')
        st.download_button(
            label="入力データをCSV保存",
            data=csv_input,
            file_name=f"input_data_{datetime.date.today()}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col_calc:
        if st.button("集計実行", key="calc_multi", use_container_width=True):
        
            all_predictions = []
            
            for index, row in input_df.iterrows():
                # Safe Parsing
                try:
                    prod = str(row.get('producer', ''))
                    h_name = str(row.get('house_name', f"House_{index}"))
                    var = str(row.get('variety', "Unknown"))
                    area = float(row.get('area_tsubo', 0))
                    
                    # Date handling
                    b_date_raw = row.get('blackout_date')
                    try:
                        # Use pandas to handle various formats (YYYY/MM/DD, YYYY-MM-DD, etc)
                        ts = pd.to_datetime(b_date_raw)
                        if pd.isna(ts):
                                raise ValueError("Fields is NaT")
                        b_date = ts.date()
                    except:
                        st.warning(f"行 {index}: 日付が無効です ({b_date_raw}) -> スキップします")
                        continue
                        
                    
                    w_raw = row.get('weeks')
                    if pd.isna(w_raw) or w_raw == "":
                        w = 7.0
                    else:
                        w = float(w_raw)
                    
                    # Coeff Logic: If missing or NaN, calculate from season
                    c_raw = row.get('coeff')
                    if pd.isna(c_raw) or c_raw == "":
                            # Calculate flowering date
                            f_date = b_date + datetime.timedelta(days=int(round(w*7)))
                            c = get_coeff_for_date(f_date)
                    else:
                            c = float(c_raw)
                    
                    # New fields
                    clr = str(row.get('color', ''))
                    shp = str(row.get('shape', ''))
                    
                    preds = predict_single_house(
                        h_name, var, area, b_date, c, 
                        days_to_start=int(round(w*7)), 
                        color=clr,
                        shape=shp,
                        distribution_ratio=normalized_ratios,
                        producer=prod
                    )
                    
                    if enable_shipping_adjust:
                        preds = adjust_to_shipping_days(preds)

                    all_predictions.extend(preds)
                    
                except Exception as e:
                    st.error(f"行 {index} の処理中にエラー: {e}")
            
            if all_predictions:
                    st.session_state['all_predictions'] = all_predictions
            else:
                    if 'all_predictions' in st.session_state:
                        del st.session_state['all_predictions']

    # Check session state for persistence
    if 'all_predictions' in st.session_state and st.session_state['all_predictions']:
        full_df = pd.DataFrame(st.session_state['all_predictions'])
        # Auto-detect View Date Range
        view_start_date = full_df['date'].min()
        view_end_date = full_df['date'].max()
        
        mask = (full_df['date'] >= view_start_date) & (full_df['date'] <= view_end_date)
        view_df = full_df.loc[mask].copy()
        
        if view_df.empty:
            st.warning(f"指定された期間 ({view_start_date} ~ {view_end_date}) のデータはありません。")
        else:
            st.divider()
            st.subheader(f"週間集計 ({view_start_date} ~ {view_end_date})")

            # Aggregation Settings
            agg_options = ["producer", "variety", "color", "shape", "house_name"]
            selected_aggs = st.multiselect("集計キー (列)", agg_options, default=["color", "shape", "variety"])
            
            if not selected_aggs:
                st.warning("集計キーを選択してください。")
            else:
                # Pivot: Index=Date, Col=Selected Keys, Val=Sum(Boxes)
                # We need to fillna for missing keys if any, though our logic ensures strings
                pivot_df = view_df.pivot_table(
                    index='date', 
                    columns=selected_aggs, 
                    values='boxes', 
                    aggfunc='sum',
                    fill_value=0
                )
                
                # --- Visualization (Altair) ---
                st.subheader("出荷予測グラフ (色・花形別)")
                
                # Chart always groups by Color and Shape for consistent visual "density" and coloring
                chart_df = view_df.groupby(['date', 'color', 'shape'])['boxes'].sum().reset_index()
                
                # Color Mapping
                # We map Japanese color names to Hex
                domain_colors = ['白', 'ホワイト', '黄', 'イエロー', 'ピンク', '赤', 'レッド', 'オレンジ', '茶', '紫', 'パープル', '緑', 'グリーン']
                range_colors =  ['#e0e0e0', '#e0e0e0', '#fff176', '#fff176', '#f48fb1', '#e57373', '#e57373', '#ffb74d', '#8d6e63', '#ba68c8', '#ba68c8', '#81c784', '#81c784']
                
                import altair as alt
                
                chart = alt.Chart(chart_df).mark_bar().encode(
                    x=alt.X('date:T', title='日付', axis=alt.Axis(format='%Y-%m-%d')),
                    y=alt.Y('boxes:Q', title='出荷箱数'),
                    color=alt.Color('color:N', scale=alt.Scale(domain=domain_colors, range=range_colors), title='花色', legend=alt.Legend(orient='bottom')),
                    opacity=alt.Opacity('shape:N', title='花形', legend=alt.Legend(orient='bottom')),
                    tooltip=['date', 'color', 'shape', 'boxes']
                ).interactive()

                st.altair_chart(chart, use_container_width=True)

                # Add Daily Total Column for the Table (Preserve MultiIndex structure)
                pivot_df['Total'] = pivot_df.sum(axis=1)

                # Display Table
                st.subheader("集計表 (カスタム集計)")
                st.dataframe(pivot_df, use_container_width=True)
                
                # --- Downloads ---
                st.subheader("ダウンロード")
                
                # 1. Summary CSV (Pivot-like or Flat Summary)
                # Group by selected aggs
                group_cols = ['date'] + selected_aggs
                agg_df = view_df.groupby(group_cols)['boxes'].sum().reset_index()
                csv_agg = agg_df.to_csv(index=False).encode('utf-8_sig')
                
                st.download_button(
                    "集計CSV (Current View)",
                    data=csv_agg,
                    file_name=f"shipment_summary_{view_start_date}.csv",
                    mime="text/csv"
                )
            
            # 2. Detailed CSV (Always available)
            detail_df = view_df[['date', 'producer', 'house_name', 'variety', 'color', 'shape', 'boxes']]
            csv_detail = detail_df.to_csv(index=False).encode('utf-8_sig')
            
            st.download_button(
                "詳細CSV (All Data)",
                data=csv_detail,
                file_name=f"shipment_detail_{view_start_date}.csv",
                mime="text/csv"
            )
