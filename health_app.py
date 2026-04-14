import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# --- EXPECTED COLUMNS FOR GOOGLE SHEETS ---
EXPECTED_COLS = {
    'settings': ['id', 'weight_target', 'cal_target', 'prot_target', 'carb_target', 'fat_target', 'sod_target', 'water_target'],
    'daily_log': ['date', 'weight', 'bp_sys', 'bp_dia', 'calories', 'sodium', 'protein', 'carbs', 'fat', 'water_oz', 'active_cals'],
    'food_diary': ['id', 'date', 'recipe_name', 'calories', 'sodium', 'carbs', 'fat', 'protein'],
    'recipes': ['id', 'name', 'category', 'calories', 'sodium', 'carbs', 'fat', 'protein', 'ingredients'],
    'ingredients': ['id', 'name', 'serving_size', 'calories', 'protein', 'carbs', 'fat', 'sodium'],
    'workouts': ['id', 'date', 'type', 'duration_min', 'calories_burned'],
    'body_metrics': ['date', 'weight', 'body_fat', 'lean_mass', 'bmr'] # <-- Added Smart Scale table
}

# --- GOOGLE SHEETS HELPER FUNCTIONS ---
def get_data(worksheet):
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        df = conn.read(worksheet=worksheet, ttl="10m")
        df = df.dropna(how='all')
    except Exception as e:
        if worksheet == 'settings':
            st.error("⚠️ Google Sheets is busy syncing! Please wait 60 seconds and refresh the page.")
            st.stop()
        df = pd.DataFrame()
        
    expected = EXPECTED_COLS[worksheet]
    
    if df.empty or len(df.columns) == 0:
        df = pd.DataFrame(columns=expected)
        
    for col in expected:
        if col not in df.columns:
            if col in ['date', 'name', 'category', 'recipe_name', 'serving_size', 'ingredients', 'type']:
                df[col] = ""
            else:
                df[col] = 0.0
        else:
            if col not in ['date', 'name', 'category', 'recipe_name', 'serving_size', 'ingredients', 'type']:
                df[col] = df[col].astype(str).str.replace(',', '', regex=False)
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
                
    return df

def write_data(worksheet, df):
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = df[EXPECTED_COLS[worksheet]]
    conn.update(worksheet=worksheet, data=df)
    st.cache_data.clear()

# --- MATH HELPERS ---
def calculate_streak(df_log):
    if df_log.empty: return 0
    df = df_log.copy()
    df['date'] = pd.to_datetime(df['date'], format='%m-%d-%Y', errors='coerce').dropna().sort_values(ascending=False)
    logged_dates = set(df_log[(df_log['weight'] > 0) | (df_log['calories'] > 0)]['date'])
    today_str = datetime.now().strftime('%m-%d-%Y')
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%m-%d-%Y')
    
    streak, curr_date = 0, datetime.now()
    if today_str in logged_dates:
        streak += 1
        curr_date -= timedelta(days=1)
    elif yesterday_str in logged_dates:
        curr_date -= timedelta(days=1)
    else: 
        return 0
        
    while curr_date.strftime('%m-%d-%Y') in logged_dates:
        streak += 1
        curr_date -= timedelta(days=1)
    return streak

# --- DATABASE LOGIC ---
def sync_daily_totals(log_date):
    fd = get_data('food_diary')
    day_fd = fd[fd['date'] == log_date]
    cal = day_fd['calories'].sum() if not day_fd.empty else 0
    sod = day_fd['sodium'].sum() if not day_fd.empty else 0
    carb = day_fd['carbs'].sum() if not day_fd.empty else 0
    fat = day_fd['fat'].sum() if not day_fd.empty else 0
    prot = day_fd['protein'].sum() if not day_fd.empty else 0
    
    wk = get_data('workouts')
    day_wk = wk[wk['date'] == log_date]
    burn = day_wk['calories_burned'].sum() if not day_wk.empty else 0

    dl = get_data('daily_log')
    
    if log_date in dl['date'].values:
        idx = dl.index[dl['date'] == log_date].tolist()[0]
        dl.at[idx, 'calories'] = cal
        dl.at[idx, 'sodium'] = sod
        dl.at[idx, 'carbs'] = carb
        dl.at[idx, 'fat'] = fat
        dl.at[idx, 'protein'] = prot
        dl.at[idx, 'active_cals'] = burn
    else:
        new_row = {'date': log_date, 'weight': 0.0, 'bp_sys': 0.0, 'bp_dia': 0.0, 'calories': cal, 'sodium': sod, 'protein': prot, 'carbs': carb, 'fat': fat, 'water_oz': 0.0, 'active_cals': burn}
        dl = pd.concat([dl, pd.DataFrame([new_row])], ignore_index=True)
        
    write_data('daily_log', dl)

def log_to_diary(log_date, name, cal, sod, carb, fat, prot):
    fd = get_data('food_diary')
    new_id = 1 if fd.empty else int(fd['id'].max()) + 1
    new_row = {'id': new_id, 'date': log_date, 'recipe_name': name, 'calories': cal, 'sodium': sod, 'carbs': carb, 'fat': fat, 'protein': prot}
    fd = pd.concat([fd, pd.DataFrame([new_row])], ignore_index=True)
    write_data('food_diary', fd)
    sync_daily_totals(log_date)

def update_water(date, amount):
    dl = get_data('daily_log')
    if date in dl['date'].values:
        idx = dl.index[dl['date'] == date].tolist()[0]
        dl.at[idx, 'water_oz'] = max(0, float(dl.at[idx, 'water_oz']) + amount)
    else:
        new_row = {'date': date, 'weight': 0.0, 'bp_sys': 0.0, 'bp_dia': 0.0, 'calories': 0.0, 'sodium': 0.0, 'protein': 0.0, 'carbs': 0.0, 'fat': 0.0, 'water_oz': max(0, amount), 'active_cals': 0.0}
        dl = pd.concat([dl, pd.DataFrame([new_row])], ignore_index=True)
    write_data('daily_log', dl)

def save_daily_metrics(date, weight, bp_sys, bp_dia):
    dl = get_data('daily_log')
    if date in dl['date'].values:
        idx = dl.index[dl['date'] == date].tolist()[0]
        dl.at[idx, 'weight'] = weight
        dl.at[idx, 'bp_sys'] = bp_sys
        dl.at[idx, 'bp_dia'] = bp_dia
    else:
        new_row = {'date': date, 'weight': weight, 'bp_sys': bp_sys, 'bp_dia': bp_dia, 'calories': 0.0, 'sodium': 0.0, 'protein': 0.0, 'carbs': 0.0, 'fat': 0.0, 'water_oz': 0.0, 'active_cals': 0.0}
        dl = pd.concat([dl, pd.DataFrame([new_row])], ignore_index=True)
    write_data('daily_log', dl)
    st.success("Health metrics saved!")

def recalculate_all_macros():
    fd = get_data('food_diary')
    wk = get_data('workouts')
    dl = get_data('daily_log')
    
    dates = set(fd['date'].unique()).union(set(wk['date'].unique()))
    
    for d in dates:
        if str(d).strip() == "": continue
        cal = fd[fd['date'] == d]['calories'].sum()
        sod = fd[fd['date'] == d]['sodium'].sum()
        carb = fd[fd['date'] == d]['carbs'].sum()
        fat = fd[fd['date'] == d]['fat'].sum()
        prot = fd[fd['date'] == d]['protein'].sum()
        burn = wk[wk['date'] == d]['calories_burned'].sum()
        
        if d in dl['date'].values:
            idx = dl.index[dl['date'] == d].tolist()[0]
            dl.at[idx, 'calories'] = cal
            dl.at[idx, 'sodium'] = sod
            dl.at[idx, 'carbs'] = carb
            dl.at[idx, 'fat'] = fat
            dl.at[idx, 'protein'] = prot
            dl.at[idx, 'active_cals'] = burn
        else:
            new_row = {'date': d, 'weight': 0.0, 'bp_sys': 0.0, 'bp_dia': 0.0, 'calories': cal, 'sodium': sod, 'protein': prot, 'carbs': carb, 'fat': fat, 'water_oz': 0.0, 'active_cals': burn}
            dl = pd.concat([dl, pd.DataFrame([new_row])], ignore_index=True)
            
    write_data('daily_log', dl)
    st.success("✅ All historical macros synced with Google Sheets!")
    st.rerun()

# --- CHART HELPERS ---
def make_heatmap(df_log):
    df = df_log.copy()
    if df.empty: return None
    df['date'] = pd.to_datetime(df['date'], format='%m-%d-%Y', errors='coerce')
    df = df.dropna(subset=['date'])
    df = df[df['date'] >= datetime.now() - timedelta(days=90)]
    if df.empty: return None
    
    df['Activity'] = np.where((df['calories'] > 0) | (df['weight'] > 0), 'Logged Data', 'No Data')
    return alt.Chart(df).mark_rect(cornerRadius=4).encode(
        x=alt.X('yearmonthdate(date):O', title='', axis=alt.Axis(format="%b %d", labelAngle=-45)),
        y=alt.Y('day(date):O', title='', sort=['Sun','Mon','Tue','Wed','Thu','Fri','Sat']),
        color=alt.Color('Activity:N', scale=alt.Scale(domain=['No Data', 'Logged Data'], range=['#2b2b2b', '#2ca02c']), legend=None),
        tooltip=[alt.Tooltip('date:T', format='%m-%d-%Y'), 'weight', 'calories']
    ).properties(height=200).configure_view(strokeWidth=0)

def make_macro_bar_chart(df, col_name, target_val, color, title):
    df_clean = df.copy()
    df_clean['date'] = df_clean['date'].astype(str)
    df_clean = df_clean.dropna(subset=['date', col_name])
    df_clean = df_clean[(df_clean['date'] != '') & (df_clean[col_name] > 0)]
    if df_clean.empty: return None
        
    df_clean['date'] = pd.to_datetime(df_clean['date'], format='%m-%d-%Y', errors='coerce')
    df_clean = df_clean.dropna(subset=['date']).sort_values('date')
    df_clean['7-Day Avg'] = df_clean[col_name].rolling(window=7, min_periods=1).mean()
    df_clean['Date Label'] = df_clean['date'].dt.strftime('%m-%d')
    
    base = alt.Chart(df_clean).encode(x=alt.X('Date Label:N', title='', sort=df_clean['date'].tolist(), axis=alt.Axis(labelAngle=-45)))
    bars = base.mark_bar(color=color, opacity=0.6).encode(y=alt.Y(f'{col_name}:Q', title=title), tooltip=[alt.Tooltip('date:T', format='%m-%d-%Y'), alt.Tooltip(f'{col_name}:Q', title=title)])
    avg_line = base.mark_line(color='#1f77b4', size=3).encode(y=alt.Y('7-Day Avg:Q'), tooltip=[alt.Tooltip('date:T', format='%m-%d-%Y'), alt.Tooltip('7-Day Avg:Q', title='7-Day Avg', format='.0f')])
    target = alt.Chart(pd.DataFrame({'target': [target_val]})).mark_rule(color='red', strokeDash=[5,5], size=2).encode(y='target:Q')
    
    return (bars + avg_line + target).properties(height=250).interactive()

def make_weight_chart(df):
    df_w = df.copy()
    df_w = df_w.dropna(subset=['date', 'weight'])
    df_w = df_w[df_w['weight'] > 0]
    if df_w.empty: return None
    
    df_w['date'] = pd.to_datetime(df_w['date'], format='%m-%d-%Y', errors='coerce')
    df_w = df_w.dropna(subset=['date']).sort_values('date')
    df_w['7-Day Avg'] = df_w['weight'].rolling(window=7, min_periods=1).mean()
    
    min_w, max_w = df_w['weight'].min() - 0.5, df_w['weight'].max() + 0.5
    
    base = alt.Chart(df_w).encode(x=alt.X('date:T', title='', axis=alt.Axis(format="%m-%d", labelAngle=-45)))
    actual = base.mark_line(point=True, color='#a9a9a9', strokeDash=[2,2], size=1).encode(y=alt.Y('weight:Q', scale=alt.Scale(domain=[min_w, max_w], clamp=True), title='Weight (lbs)'), tooltip=[alt.Tooltip('date:T', format='%m-%d-%Y'), 'weight'])
    trend = base.mark_line(color='#1f77b4', size=4).encode(y=alt.Y('7-Day Avg:Q'), tooltip=[alt.Tooltip('date:T', format='%m-%d-%Y'), alt.Tooltip('7-Day Avg:Q', format='.1f')])
    return (actual + trend).properties(height=250).interactive()

def make_bp_chart(df):
    df_bp = df.copy()
    df_bp = df_bp.dropna(subset=['date', 'bp_sys', 'bp_dia'])
    df_bp = df_bp[(df_bp['bp_sys'] > 0) & (df_bp['bp_dia'] > 0)]
    if df_bp.empty: return None
    
    df_bp['date'] = pd.to_datetime(df_bp['date'], format='%m-%d-%Y', errors='coerce')
    df_bp = df_bp.dropna(subset=['date'])
    
    melted_bp = df_bp.melt(id_vars=['date'], value_vars=['bp_sys', 'bp_dia'], var_name='Type', value_name='mmHg').dropna()
    melted_bp['Type'] = melted_bp['Type'].replace({'bp_sys': 'Systolic', 'bp_dia': 'Diastolic'})
    min_bp, max_bp = melted_bp['mmHg'].min() - 5, melted_bp['mmHg'].max() + 5
    
    base = alt.Chart(melted_bp).encode(x=alt.X('date:T', title='', axis=alt.Axis(format="%m-%d", labelAngle=-45)))
    lines = base.mark_line(point=alt.OverlayMarkDef(size=80), size=3).encode(y=alt.Y('mmHg:Q', scale=alt.Scale(domain=[min_bp, max_bp], clamp=True), title='Blood Pressure'), color=alt.Color('Type:N', legend=alt.Legend(title=None, orient='bottom')), tooltip=[alt.Tooltip('date:T', format='%m-%d-%Y'), 'Type:N', 'mmHg:Q'])
    t_sys = alt.Chart(pd.DataFrame({'target': [120]})).mark_rule(color='red', strokeDash=[5,5], opacity=0.4, size=2).encode(y='target:Q')
    t_dia = alt.Chart(pd.DataFrame({'target': [80]})).mark_rule(color='red', strokeDash=[5,5], opacity=0.4, size=2).encode(y='target:Q')
    return (lines + t_sys + t_dia).properties(height=250).interactive()

def make_macro_donut(prot, carb, fat):
    p_cal, c_cal, f_cal = prot * 4, carb * 4, fat * 9
    total = p_cal + c_cal + f_cal
    if total <= 0: return None
    
    source = pd.DataFrame({"Macro": ["Protein", "Carbs", "Fat"], "Calories": [p_cal, c_cal, f_cal], "Grams": [prot, carb, fat]})
    source = source[source['Calories'] > 0].copy()
    source['Percent'] = (source['Calories'] / total * 100).round(0).astype(int).astype(str) + '%'
    
    base = alt.Chart(source).encode(theta=alt.Theta("Calories:Q", stack=True))
    
    donut = base.mark_arc(innerRadius=45, outerRadius=90, stroke="#fff").encode(
        color=alt.Color("Macro:N", scale=alt.Scale(domain=["Protein", "Carbs", "Fat"], range=["#ff7f0e", "#9467bd", "#8c564b"]), legend=alt.Legend(title=None, orient='bottom')),
        tooltip=["Macro", alt.Tooltip("Grams:Q", title="Grams"), alt.Tooltip("Calories:Q", title="Calories"), alt.Tooltip("Percent:N", title="Percent")]
    )
    
    text = base.mark_text(radius=68, size=14, color="white", fontWeight="bold").encode(text="Percent:N")
    return (donut + text).properties(height=220).interactive()

# --- PAGE FUNCTIONS ---
def page_dashboard(s, today):
    dl_df = get_data("daily_log")
    today_log = dl_df[dl_df['date'] == today] if not dl_df.empty else pd.DataFrame()
    
    st.title("Daily Dashboard")
    c_head1, c_head2 = st.columns([2, 1])
    with c_head1:
        streak = calculate_streak(dl_df)
        if streak > 0: st.markdown(f"### 🔥 Current Logging Streak: **{streak} Days**")
    with c_head2:
        heatmap = make_heatmap(dl_df)
        if heatmap: st.altair_chart(heatmap, use_container_width=True)

    if not dl_df.empty:
        df_recent = dl_df.copy()
        df_recent['date'] = pd.to_datetime(df_recent['date'], format='%m-%d-%Y', errors='coerce')
        df_recent = df_recent.dropna(subset=['date']).sort_values('date', ascending=False).head(7)
        st.info(f"📊 **7-Day Trend Averages:** Weight: **{df_recent[df_recent['weight'] > 0]['weight'].mean():.1f} lbs** | Cal: **{df_recent[df_recent['calories'] > 0]['calories'].mean():.0f}** | Prot: **{df_recent[df_recent['protein'] > 0]['protein'].mean():.0f}g** | Carb: **{df_recent[df_recent['carbs'] > 0]['carbs'].mean():.0f}g** | Fat: **{df_recent[df_recent['fat'] > 0]['fat'].mean():.0f}g**")

    df_w_prog = dl_df[dl_df['weight'] > 0].copy() if not dl_df.empty else pd.DataFrame()
    if not df_w_prog.empty and len(df_w_prog) >= 2:
        df_w_prog['date'] = pd.to_datetime(df_w_prog['date'], format='%m-%d-%Y', errors='coerce')
        df_w_prog = df_w_prog.dropna(subset=['date']).sort_values('date')
        
        start_w, start_d = df_w_prog.iloc[0]['weight'], df_w_prog.iloc[0]['date']
        curr_w, curr_d = df_w_prog.iloc[-1]['weight'], df_w_prog.iloc[-1]['date']
        total_change = start_w - curr_w
        days_diff = (curr_d - start_d).days
        weekly_change = (total_change / days_diff * 7) if days_diff > 0 else 0.0
        
        df_recent_14 = df_w_prog[df_w_prog['date'] >= curr_d - timedelta(days=14)]
        recent_text = ""
        if len(df_recent_14) >= 2 and (curr_d - df_recent_14.iloc[0]['date']).days > 0:
            rec_total_change = df_recent_14.iloc[0]['weight'] - curr_w
            rec_weekly_change = (rec_total_change / (curr_d - df_recent_14.iloc[0]['date']).days * 7)
            recent_text = f" | 📅 **Recent (14d):** Avg {'Lost' if rec_total_change >= 0 else 'Gained'} **{abs(rec_weekly_change):.2f} lbs/wk**"

        st.success(f"🏆 **Weight Journey:** Total {'Lost' if total_change >= 0 else 'Gained'}: **{abs(total_change):.1f} lbs** (Since {start_d.strftime('%m/%d/%y')}) | Lifetime Avg: **{abs(weekly_change):.2f} lbs/wk**" + recent_text)

    st.subheader(f"Health Metrics for {today}")
    with st.form("metrics_form"):
        col1, col2, col3 = st.columns(3)
        w = col1.number_input("Weight (lbs)", value=float(today_log['weight'].iloc[0]) if not today_log.empty else 0.0, step=0.1)
        sys = col2.number_input("Systolic", value=float(today_log['bp_sys'].iloc[0]) if not today_log.empty and today_log['bp_sys'].iloc[0] > 0 else 120.0, step=1.0)
        dia = col3.number_input("Diastolic", value=float(today_log['bp_dia'].iloc[0]) if not today_log.empty and today_log['bp_dia'].iloc[0] > 0 else 80.0, step=1.0)
        if st.form_submit_button("Save Metrics"):
            save_daily_metrics(today, w, sys, dia)
            st.rerun()

    st.markdown("---")
    t_cal = float(today_log['calories'].iloc[0]) if not today_log.empty else 0
    t_prot = float(today_log['protein'].iloc[0]) if not today_log.empty else 0
    t_carb = float(today_log['carbs'].iloc[0]) if not today_log.empty else 0
    t_fat = float(today_log['fat'].iloc[0]) if not today_log.empty else 0
    t_sod = float(today_log['sodium'].iloc[0]) if not today_log.empty else 0
    t_wat = float(today_log['water_oz'].iloc[0]) if not today_log.empty else 0
    t_burn = float(today_log['active_cals'].iloc[0]) if not today_log.empty else 0
    
    col_metrics, col_donut = st.columns([2, 1])
    with col_metrics:
        st.subheader("Today's Nutrition Totals")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Net Calories", f"{int(t_cal - t_burn)} / {int(s['cal_target'])}", help=f"{int(t_cal)} in - {int(t_burn)} burned")
        m1.progress(min(max((t_cal - t_burn) / s['cal_target'] if s['cal_target'] > 0 else 0.0, 0.0), 1.0))
        m2.metric("Protein", f"{int(t_prot)} / {int(s['prot_target'])}")
        m2.progress(min(t_prot / s['prot_target'] if s['prot_target'] > 0 else 0.0, 1.0))
        m3.metric("Carbs", f"{int(t_carb)} / {int(s['carb_target'])}")
        m3.progress(min(t_carb / s['carb_target'] if s['carb_target'] > 0 else 0.0, 1.0))
        m4.metric("Fat", f"{int(t_fat)} / {int(s['fat_target'])}")
        m4.progress(min(t_fat / s['fat_target'] if s['fat_target'] > 0 else 0.0, 1.0))
        m5.metric("Sodium", f"{int(t_sod)}")
        m5.progress(min(t_sod / s['sod_target'] if s['sod_target'] > 0 else 0.0, 1.0))

    with col_donut:
        st.write("**Macro Breakdown (Cals)**")
        donut = make_macro_donut(t_prot, t_carb, t_fat)
        if donut: st.altair_chart(donut, use_container_width=True)
        else: st.info("Log meals to see chart.")

    st.markdown("---")
    c_w, c_wo = st.columns(2)
    with c_w:
        st.write(f"**💧 Water Intake:** {int(t_wat)} / {s['water_target']} oz")
        st.progress(min(t_wat / s['water_target'] if s['water_target'] > 0 else 0.0, 1.0))
        btn1, btn2 = st.columns(2)
        if btn1.button("➖ Remove 8 oz", use_container_width=True): 
            update_water(today, -8)
            st.rerun()
        if btn2.button("➕ Add 8 oz", use_container_width=True):
            update_water(today, 8)
            st.rerun()
            
    with c_wo:
        st.write(f"**🏋️ Active Calories:** {int(t_burn)} burned")
        with st.popover("Log Workout"):
            w_type = st.text_input("Activity (e.g. Running)")
            w_cals = st.number_input("Calories Burned", min_value=0.0)
            if st.button("Save Workout"):
                wk = get_data('workouts')
                new_id = 1 if wk.empty else int(wk['id'].max()) + 1
                new_row = {'id': new_id, 'date': today, 'type': w_type, 'duration_min': 0.0, 'calories_burned': w_cals}
                wk = pd.concat([wk, pd.DataFrame([new_row])], ignore_index=True)
                write_data('workouts', wk)
                sync_daily_totals(today)
                st.rerun()

    st.markdown("---")
    st.subheader("📉 Body Composition Trends")
    bm_df = get_data('body_metrics')
    
    if not bm_df.empty and len(bm_df) > 0:
        chart_df = bm_df.copy()
        chart_df['date'] = pd.to_datetime(chart_df['date'], format='%m-%d-%Y')
        
        base = alt.Chart(chart_df).encode(x=alt.X('date:T', title='Date'))
        
        line_weight = base.mark_line(color='#1f77b4', point=True).encode(
            y=alt.Y('weight:Q', title='Weight (lbs)', scale=alt.Scale(zero=False))
        )
        line_bf = base.mark_line(color='#d62728', point=True).encode(
            y=alt.Y('body_fat:Q', title='Body Fat %', scale=alt.Scale(zero=False))
        )
        
        dual_chart = alt.layer(line_weight, line_bf).resolve_scale(y='independent')
        st.altair_chart(dual_chart, use_container_width=True)
    else:
        st.info("No scale data logged yet! Head to the 'Smart Scale Sync' page to log your first weigh-in.")
        
    st.markdown("---")
    st.subheader("📈 Progress & Macro Trends")
    if not dl_df.empty:
        c_a, c_b = st.columns(2)
        with c_a:
            st.write("**Weight Progress**")
            w_chart = make_weight_chart(dl_df)
            if w_chart: st.altair_chart(w_chart, use_container_width=True)
        with c_b:
            st.write("**Blood Pressure**")
            bp_chart = make_bp_chart(dl_df)
            if bp_chart: st.altair_chart(bp_chart, use_container_width=True)

        c1, c2, c3 = st.columns(3)
        with c1:
            st.write("**Calories**")
            cal_chart = make_macro_bar_chart(dl_df, 'calories', s['cal_target'], '#2ca02c', 'Calories (kcal)')
            if cal_chart: st.altair_chart(cal_chart, use_container_width=True)
        with c2:
            st.write("**Protein**")
            prot_chart = make_macro_bar_chart(dl_df, 'protein', s['prot_target'], '#ff7f0e', 'Protein (g)')
            if prot_chart: st.altair_chart(prot_chart, use_container_width=True)
        with c3:
            st.write("**Carbs**")
            carb_chart = make_macro_bar_chart(dl_df, 'carbs', s['carb_target'], '#9467bd', 'Carbs (g)')
            if carb_chart: st.altair_chart(carb_chart, use_container_width=True)

        c4, c5, c6 = st.columns(3)
        with c4:
            st.write("**Fat**")
            fat_chart = make_macro_bar_chart(dl_df, 'fat', s['fat_target'], '#8c564b', 'Fat (g)')
            if fat_chart: st.altair_chart(fat_chart, use_container_width=True)
        with c5:
            st.write("**Sodium**")
            sod_chart = make_macro_bar_chart(dl_df, 'sodium', s['sod_target'], '#d62728', 'Sodium (mg)')
            if sod_chart: st.altair_chart(sod_chart, use_container_width=True)
        with c6:
            st.write("**Water**")
            wat_chart = make_macro_bar_chart(dl_df, 'water_oz', s['water_target'], '#1f77b4', 'Water (oz)')
            if wat_chart: st.altair_chart(wat_chart, use_container_width=True)
                
        c7, c8, c9 = st.columns(3)
        with c7:
            st.write("**Active Calories Burned**")
            burn_chart = make_macro_bar_chart(dl_df, 'active_cals', 0, '#ff7f0e', 'Active Cals (kcal)')
            if burn_chart: st.altair_chart(burn_chart, use_container_width=True)

    st.markdown("---")
    with st.expander("🛠️ Advanced: Edit Historical Daily Log"):
        if not dl_df.empty:
            display_df = dl_df.copy()
            display_df['date_obj'] = pd.to_datetime(display_df['date'], format='%m-%d-%Y', errors='coerce')
            display_df = display_df.sort_values(by='date_obj', ascending=False).drop(columns=['date_obj']).reset_index(drop=True)
            
            edited_daily_log = st.data_editor(display_df, num_rows="dynamic", use_container_width=True, key="dl_edit")
            
            if st.button("💾 Save Changes", key="save_dl"):
                save_df = edited_daily_log.copy()
                save_df['date_obj'] = pd.to_datetime(save_df['date'], format='%m-%d-%Y', errors='coerce')
                save_df = save_df.sort_values(by='date_obj', ascending=True).drop(columns=['date_obj']).reset_index(drop=True)
                
                write_data('daily_log', save_df)
                st.success("Historical Log updated!")
                st.rerun()

    with st.expander("🚑 Fix Wrong Meal Dates (Shift back 1 day)"):
        wrong_date = st.date_input("Select the date where meals are CURRENTLY listed:", key="wrong_date")
        wrong_date_str = wrong_date.strftime("%m-%d-%Y")
        correct_date_str = (wrong_date - timedelta(days=1)).strftime("%m-%d-%Y")
        
        if st.button(f"Shift Meals Back to {correct_date_str}", use_container_width=True):
            fd = get_data('food_diary')
            fd.loc[fd['date'] == wrong_date_str, 'date'] = correct_date_str
            write_data('food_diary', fd)
            sync_daily_totals(wrong_date_str)
            sync_daily_totals(correct_date_str)
            st.success(f"Moved meals to {correct_date_str}.")
            st.rerun()

    with st.expander("🔄 Recalculate All Historical Macros"):
        if st.button("Sync & Recalculate Everything Now", use_container_width=True):
            recalculate_all_macros()

def page_history():
    st.title("📜 Daily History Summary")
    lookup_date = st.date_input("📅 Select Date to Review", value=datetime.today(), format="MM/DD/YYYY")
    lookup_date_str = lookup_date.strftime("%m-%d-%Y")
    
    dl_df = get_data("daily_log")
    dl_df = dl_df[dl_df['date'] == lookup_date_str]
    fd_df = get_data("food_diary")
    fd_df = fd_df[fd_df['date'] == lookup_date_str]
    rec_df = get_data("recipes")
    
    st.markdown("---")
    
    if not dl_df.empty:
        r = dl_df.iloc[0]
        t_cal = float(r['calories']) if pd.notna(r['calories']) else 0
        t_prot = float(r['protein']) if pd.notna(r['protein']) else 0
        t_carb = float(r['carbs']) if pd.notna(r['carbs']) else 0
        t_fat = float(r['fat']) if pd.notna(r['fat']) else 0
        t_sod = float(r['sodium']) if pd.notna(r['sodium']) else 0
        t_water = float(r['water_oz']) if pd.notna(r['water_oz']) else 0
        t_burn = float(r['active_cals']) if pd.notna(r['active_cals']) else 0

        col_hist_metrics, col_hist_donut = st.columns([2, 1])
        with col_hist_metrics:
            st.subheader(f"📊 Nutrition Totals for {lookup_date_str}")
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Net Cals", f"{int(t_cal - t_burn)}")
            m2.metric("Protein", f"{int(t_prot)}g")
            m3.metric("Carbs", f"{int(t_carb)}g")
            m4.metric("Fat", f"{int(t_fat)}g")
            m5.metric("Sodium", f"{int(t_sod)}mg")
            st.write(f"💧 **Water:** {int(t_water)} oz | 🏋️ **Burned:** {int(t_burn)} kcal | ⚖️ **Weight:** {r['weight']} lbs | 🩸 **BP:** {r['bp_sys']}/{r['bp_dia']}")
            
        with col_hist_donut:
            st.write("**Macro Breakdown**")
            donut = make_macro_donut(t_prot, t_carb, t_fat)
            if donut: st.altair_chart(donut, use_container_width=True)
    else:
        st.subheader(f"📊 Nutrition Totals for {lookup_date_str}")
        st.info(f"No nutrition totals logged for {lookup_date_str}.")
        
    st.markdown("---")
    st.subheader(f"🍴 Meals Eaten")
    if not fd_df.empty:
        merged_df = pd.merge(fd_df, rec_df, how='left', left_on='recipe_name', right_on='name')
        for index, row in merged_df.iterrows():
            cal = float(row['calories_x']) if pd.notna(row['calories_x']) else float(row['calories'])
            prot = float(row['protein_x']) if pd.notna(row['protein_x']) else float(row['protein'])
            carb = float(row['carbs_x']) if pd.notna(row['carbs_x']) else float(row['carbs'])
            fat = float(row['fat_x']) if pd.notna(row['fat_x']) else float(row['fat'])
            sod = float(row['sodium_x']) if pd.notna(row['sodium_x']) else float(row['sodium'])
            
            with st.expander(f"**{row['recipe_name']}** | {int(cal)} kcal | {int(prot)}g Prot | {int(carb)}g Carb | {int(fat)}g Fat"):
                if pd.notna(row['ingredients']) and str(row['ingredients']).strip() != "":
                    st.markdown(f"**Notes:** {row['ingredients']}")
                
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("➕ Add to Today", key=f"relog_{index}_{row['recipe_name']}"):
                        today = datetime.now().strftime("%m-%d-%Y")
                        log_to_diary(today, row['recipe_name'], cal, sod, carb, fat, prot)
                        st.success(f"Added to today!")
                with b2:
                    if st.button("💾 Save to Recipes", key=f"saverec_{index}_{row['recipe_name']}"):
                        rec = get_data('recipes')
                        if row['recipe_name'] not in rec['name'].values:
                            new_id = 1 if rec.empty else int(rec['id'].max()) + 1
                            new_row = {'id': new_id, 'name': row['recipe_name'], 'category': 'General', 'calories': cal, 'sodium': sod, 'carbs': carb, 'fat': fat, 'protein': prot, 'ingredients': row['ingredients']}
                            rec = pd.concat([rec, pd.DataFrame([new_row])], ignore_index=True)
                            write_data('recipes', rec)
                            st.success(f"Saved '{row['recipe_name']}'!")
                        else: st.warning("Already in recipes.")

def page_diary(today):
    st.title("Food Diary")
    selected_date = st.date_input("📅 Select Date to Log For", value=datetime.today(), format="MM/DD/YYYY")
    selected_date_str = selected_date.strftime("%m-%d-%Y")
    if selected_date_str != today: 
        st.warning(f"Logging for a past date: **{selected_date_str}**")

    tab_saved, tab_build, tab_quick, tab_edit = st.tabs(["📖 Add Saved Meals", "🧮 Build Custom Meal", "⚡ Quick Log", "🛠️ Edit Entries"])

    with tab_saved:
        all_recipes = get_data("recipes")
        if not all_recipes.empty:
            col1, col2 = st.columns([1, 2])
            with col1:
                search = st.text_input("🔍 Search meals")
                cat_filter = st.multiselect("Filter by Category", options=sorted(all_recipes['category'].unique().tolist()))
            
            filtered_df = all_recipes
            if search: filtered_df = filtered_df[filtered_df['name'].str.contains(search, case=False)]
            if cat_filter: filtered_df = filtered_df[filtered_df['category'].isin(cat_filter)]

            with col2:
                selected_recipes = st.multiselect("Select recipes to log:", options=filtered_df['name'].tolist())
                if selected_recipes:
                    selected_rows = filtered_df[filtered_df['name'].isin(selected_recipes)]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Cals", selected_rows['calories'].sum())
                    c2.metric("Protein", f"{selected_rows['protein'].sum()}g")
                    c3.metric("Carbs", f"{selected_rows['carbs'].sum()}g")
                    c4.metric("Fat", f"{selected_rows['fat'].sum()}g")
                    
                    if st.button(f"Add {len(selected_recipes)} Meals to {selected_date_str}", use_container_width=True):
                        fd = get_data('food_diary')
                        new_rows = []
                        new_id = 1 if fd.empty else int(fd['id'].max()) + 1
                        for _, row in selected_rows.iterrows():
                            new_rows.append({
                                'id': new_id, 'date': selected_date_str, 'recipe_name': row['name'], 
                                'calories': row['calories'], 'sodium': row['sodium'], 'carbs': row['carbs'], 
                                'fat': row['fat'], 'protein': row['protein']
                            })
                            new_id += 1
                        fd = pd.concat([fd, pd.DataFrame(new_rows)], ignore_index=True)
                        write_data('food_diary', fd)
                        sync_daily_totals(selected_date_str)
                        st.success("Meals logged!")
                        st.rerun()
        else:
            st.warning("No recipes found. Add some in Manage Recipes.")

    with tab_build:
        st.info("Build a custom meal directly from your pantry ingredients and log it for this date.")
        all_ing = get_data("ingredients")
        if all_ing.empty:
            st.warning("Your pantry is empty! Add ingredients in the 'Manage Recipes' -> 'My Ingredient Pantry' tab first.")
        else:
            selected_diary_ing = st.multiselect("Select Ingredients for this meal:", options=all_ing['name'].tolist(), key="diary_build_ing")
            if selected_diary_ing:
                st.write("Specify how many servings of each you used:")
                total_cal, total_prot, total_carb, total_fat, total_sod = 0, 0, 0, 0, 0
                
                for name in selected_diary_ing:
                    row = all_ing[all_ing['name'] == name].iloc[0]
                    servings = st.number_input(f"Servings of {name} ({row['serving_size']})", min_value=0.0, value=1.0, step=0.5, key=f"diary_srv_{name}")
                    total_cal += float(row['calories']) * servings
                    total_prot += float(row['protein']) * servings
                    total_carb += float(row['carbs']) * servings
                    total_fat += float(row['fat']) * servings
                    total_sod += float(row['sodium']) * servings
                    
                st.markdown("---")
                st.write("### Total Meal Macros:")
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Cals", f"{int(total_cal)}")
                c2.metric("Protein", f"{int(total_prot)}g")
                c3.metric("Carbs", f"{int(total_carb)}g")
                c4.metric("Fat", f"{int(total_fat)}g")
                c5.metric("Sodium", f"{int(total_sod)}mg")
                
                meal_name = st.text_input("What did you call this meal?", value="Custom Meal")
                if st.button(f"Log '{meal_name}' to {selected_date_str}", use_container_width=True):
                    log_to_diary(selected_date_str, meal_name, total_cal, total_sod, total_carb, total_fat, total_prot)
                    st.success(f"Logged '{meal_name}' successfully!")
                    st.rerun()

    with tab_quick:
        st.info("Type snacks directly into the grid. Click button to log all.")
        blank_df = pd.DataFrame({"Food Name": [""], "Calories": [0.0], "Protein (g)": [0.0], "Carbs (g)": [0.0], "Fat (g)": [0.0], "Sodium (mg)": [0.0]})
        quick_logs = st.data_editor(blank_df, num_rows="dynamic", use_container_width=True, key=f"ql_edit_{selected_date_str}")
        
        if st.button(f"Add Quick Items to {selected_date_str}", use_container_width=True):
            valid_logs = quick_logs[quick_logs["Food Name"].str.strip() != ""]
            if not valid_logs.empty:
                fd = get_data('food_diary')
                new_rows = []
                new_id = 1 if fd.empty else int(fd['id'].max()) + 1
                for _, row in valid_logs.iterrows():
                    new_rows.append({
                        'id': new_id, 'date': selected_date_str, 'recipe_name': str(row["Food Name"]),
                        'calories': float(row["Calories"]), 'sodium': float(row["Sodium (mg)"]),
                        'carbs': float(row["Carbs (g)"]), 'fat': float(row["Fat (g)"]), 'protein': float(row["Protein (g)"])
                    })
                    new_id += 1
                fd = pd.concat([fd, pd.DataFrame(new_rows)], ignore_index=True)
                write_data('food_diary', fd)
                sync_daily_totals(selected_date_str)
                st.success("Quick-logged items!")
                st.rerun()

    with tab_edit:
        diary_df = get_data("food_diary")
        diary_df = diary_df[diary_df['date'] == selected_date_str]
        if not diary_df.empty:
            edited_diary = st.data_editor(diary_df, num_rows="dynamic", use_container_width=True, key=f"d_edit_{selected_date_str}")
            if st.button(f"💾 Save Changes for {selected_date_str}"):
                edited_diary = edited_diary.where(pd.notnull(edited_diary), None)
                fd = get_data('food_diary')
                fd = fd[fd['date'] != selected_date_str]
                fd = pd.concat([fd, edited_diary], ignore_index=True)
                write_data('food_diary', fd)
                sync_daily_totals(selected_date_str)
                st.success("Diary updated!")
                st.rerun()
        else: st.info(f"No meals for {selected_date_str}.")

def page_recipes():
    st.title("Manage Recipes")
    tab_build, tab_pantry, tab_saved = st.tabs(["🧮 Smart Recipe Builder", "🥫 My Ingredient Pantry", "📚 Saved Recipes"])

    with tab_pantry:
        st.subheader("Add Base Ingredients")
        st.info("Add standard ingredients here (e.g. 'Chicken Breast (4oz)', 'Olive Oil (1 tbsp)'). You'll use these to auto-build recipes.")
        with st.form("new_ing_form", clear_on_submit=True):
            col_n, col_s = st.columns(2)
            ing_name = col_n.text_input("Ingredient Name")
            ing_serv = col_s.text_input("Serving Size (e.g. 100g, 1 cup)")
            
            c1, c2, c3, c4, c5 = st.columns(5)
            i_cal = c1.number_input("Cals", min_value=0.0)
            i_prot = c2.number_input("Prot (g)", min_value=0.0)
            i_carb = c3.number_input("Carbs (g)", min_value=0.0)
            i_fat = c4.number_input("Fat (g)", min_value=0.0)
            i_sod = c5.number_input("Sod (mg)", min_value=0.0)
            
            if st.form_submit_button("Add to Pantry") and ing_name:
                ing = get_data('ingredients')
                new_id = 1 if ing.empty else int(ing['id'].max()) + 1
                new_row = {'id': new_id, 'name': ing_name, 'serving_size': ing_serv, 'calories': i_cal, 'protein': i_prot, 'carbs': i_carb, 'fat': i_fat, 'sodium': i_sod}
                ing = pd.concat([ing, pd.DataFrame([new_row])], ignore_index=True)
                write_data('ingredients', ing)
                st.success(f"Added {ing_name} to pantry!")
                st.rerun()
        
        st.markdown("---")
        st.write("**Manage Pantry Database:**")
        all_ing = get_data("ingredients")
        if not all_ing.empty:
            edited_ing = st.data_editor(all_ing, num_rows="dynamic", use_container_width=True)
            if st.button("💾 Save Pantry Changes"):
                write_data('ingredients', edited_ing)
                st.success("Pantry updated!")
                st.rerun()

    with tab_build:
        st.subheader("Build a Recipe")
        all_ing = get_data("ingredients")
        if all_ing.empty:
            st.warning("Your pantry is empty! Add ingredients in the 'My Ingredient Pantry' tab first.")
        else:
            selected_ing_names = st.multiselect("Select Ingredients for this meal:", options=all_ing['name'].tolist())
            if selected_ing_names:
                st.write("Specify how many servings of each you used:")
                total_cal, total_prot, total_carb, total_fat, total_sod = 0, 0, 0, 0, 0
                
                for name in selected_ing_names:
                    row = all_ing[all_ing['name'] == name].iloc[0]
                    servings = st.number_input(f"Servings of {name} ({row['serving_size']})", min_value=0.0, value=1.0, step=0.5, key=f"srv_{name}")
                    total_cal += float(row['calories']) * servings
                    total_prot += float(row['protein']) * servings
                    total_carb += float(row['carbs']) * servings
                    total_fat += float(row['fat']) * servings
                    total_sod += float(row['sodium']) * servings
                    
                st.markdown("---")
                st.write("### Total Recipe Macros:")
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Cals", f"{int(total_cal)}")
                c2.metric("Protein", f"{int(total_prot)}g")
                c3.metric("Carbs", f"{int(total_carb)}g")
                c4.metric("Fat", f"{int(total_fat)}g")
                c5.metric("Sodium", f"{int(total_sod)}mg")
                
                with st.form("save_built_recipe"):
                    r_name = st.text_input("Name your new recipe:")
                    r_cat = st.selectbox("Category", ["Breakfast", "Lunch", "Dinner", "Snack", "Shake"])
                    if st.form_submit_button("Save as New Recipe") and r_name:
                        rec = get_data('recipes')
                        new_id = 1 if rec.empty else int(rec['id'].max()) + 1
                        new_row = {'id': new_id, 'name': r_name, 'category': r_cat, 'calories': total_cal, 'sodium': total_sod, 'carbs': total_carb, 'fat': total_fat, 'protein': total_prot, 'ingredients': f"Auto-built from: {', '.join(selected_ing_names)}"}
                        rec = pd.concat([rec, pd.DataFrame([new_row])], ignore_index=True)
                        write_data('recipes', rec)
                        st.success(f"'{r_name}' saved to your recipes!")

    with tab_saved:
        st.subheader("Manual Recipe Entry & Editor")
        with st.form("new_recipe_form", clear_on_submit=True):
            name = st.text_input("Recipe Name")
            cat = st.selectbox("Category", ["Breakfast", "Lunch", "Dinner", "Snack", "Shake"])
            
            c1, c2, c3, c4, c5 = st.columns(5)
            cal = c1.number_input("Cals", min_value=0.0)
            prot = c2.number_input("Prot (g)", min_value=0.0)
            carb = c3.number_input("Carbs (g)", min_value=0.0)
            fat = c4.number_input("Fat (g)", min_value=0.0)
            sod = c5.number_input("Sod (mg)", min_value=0.0)
            ing = st.text_area("Ingredients & Notes")
            
            if st.form_submit_button("Save Manual Recipe") and name:
                rec = get_data('recipes')
                new_id = 1 if rec.empty else int(rec['id'].max()) + 1
                new_row = {'id': new_id, 'name': name, 'category': cat, 'calories': cal, 'sodium': sod, 'carbs': carb, 'fat': fat, 'protein': prot, 'ingredients': ing}
                rec = pd.concat([rec, pd.DataFrame([new_row])], ignore_index=True)
                write_data('recipes', rec)
                st.success(f"'{name}' saved!")
                st.rerun()

        st.markdown("---")
        all_recipes = get_data("recipes")
        if not all_recipes.empty:
            edited_recipes = st.data_editor(all_recipes, num_rows="dynamic", use_container_width=True)
            if st.button("💾 Save Recipe Database Changes"):
                write_data('recipes', edited_recipes)
                st.success("Recipes updated!")
                st.rerun()

def page_body_comp():
    st.title("⚖️ Smart Scale Sync")
    
    with st.form("scale_entry"):
        st.write("Log today's Wyze Scale data:")
        col1, col2 = st.columns(2)
        
        with col1:
            log_date = st.date_input("Date", datetime.today())
            weight = st.number_input("Weight (lbs)", min_value=0.0, format="%.1f")
            body_fat = st.number_input("Body Fat %", min_value=0.0, format="%.1f")
        with col2:
            lean_mass = st.number_input("Lean Body Mass (lbs)", min_value=0.0, format="%.1f")
            bmr = st.number_input("BMR (kcal)", min_value=0, step=1)
            
        if st.form_submit_button("💾 Save Metrics"):
            bm_df = get_data('body_metrics')
            
            new_row = pd.DataFrame([{
                'date': log_date.strftime('%m-%d-%Y'),
                'weight': weight,
                'body_fat': body_fat,
                'lean_mass': lean_mass,
                'bmr': bmr
            }])
            
            updated_df = pd.concat([bm_df, new_row], ignore_index=True)
            write_data('body_metrics', updated_df)
            
            st.success("Scale data logged successfully! Check the Dashboard for your updated chart.")

    st.markdown("---")
    with st.expander("🛠️ Advanced: Edit Past Scale Entries"):
        bm_df = get_data('body_metrics')
        if not bm_df.empty:
            # Sort newest to oldest for easy editing
            display_df = bm_df.copy()
            display_df['date_obj'] = pd.to_datetime(display_df['date'], format='%m-%d-%Y', errors='coerce')
            display_df = display_df.sort_values(by='date_obj', ascending=False).drop(columns=['date_obj']).reset_index(drop=True)
            
            edited_bm = st.data_editor(display_df, num_rows="dynamic", use_container_width=True, key="bm_edit")
            
            if st.button("💾 Save Scale Changes"):
                # Sort back chronologically before saving to Google Sheets
                save_df = edited_bm.copy()
                save_df['date_obj'] = pd.to_datetime(save_df['date'], format='%m-%d-%Y', errors='coerce')
                save_df = save_df.sort_values(by='date_obj', ascending=True).drop(columns=['date_obj']).reset_index(drop=True)
                
                write_data('body_metrics', save_df)
                st.success("Scale data updated!")
                st.rerun()
        else:
            st.info("No scale data to edit yet.")
            
# --- MAIN APP ROUTING ---
def main():
    st.set_page_config(page_title="Health Tracker V4.0", layout="wide")

    s_df = get_data("settings")
    if s_df.empty:
        s_df = pd.DataFrame([{'id': 1, 'weight_target': 175.0, 'cal_target': 1650, 'prot_target': 150, 'carb_target': 150, 'fat_target': 55, 'sod_target': 1500, 'water_target': 64}])
        write_data('settings', s_df)
    s = s_df.iloc[0]

    if 'page' not in st.session_state: st.session_state.page = "Dashboard"
    today = datetime.now().strftime("%m-%d-%Y")

    st.sidebar.title("Menu")
    if st.sidebar.button("📊 Daily Dashboard", use_container_width=True): st.session_state.page = "Dashboard"
    if st.sidebar.button("📜 History Lookup", use_container_width=True): st.session_state.page = "History"
    if st.sidebar.button("🍴 Food Diary", use_container_width=True): st.session_state.page = "Diary"
    if st.sidebar.button("📝 Manage Recipes", use_container_width=True): st.session_state.page = "Recipes"
    if st.sidebar.button("⚖️ Smart Scale Sync", use_container_width=True): st.session_state.page = "Scale"
    
    st.sidebar.markdown("---")
    st.sidebar.header("🎯 Daily Targets")
    weight_target = st.sidebar.number_input("Target Weight (lbs)", value=float(s['weight_target']), step=1.0)
    cal_target = st.sidebar.number_input("Calories (kcal)", value=int(s['cal_target']), step=50)
    prot_target = st.sidebar.number_input("Protein (g)", value=int(s['prot_target']), step=5)
    carb_target = st.sidebar.number_input("Carbs (g)", value=int(s['carb_target']), step=10)
    fat_target = st.sidebar.number_input("Fat (g)", value=int(s['fat_target']), step=5)
    sod_target = st.sidebar.number_input("Sodium (mg)", value=int(s['sod_target']), step=50)
    water_target = st.sidebar.number_input("Water (oz)", value=int(s['water_target']), step=8)
    
    if st.sidebar.button("💾 Save Targets", use_container_width=True):
        s_df.at[0, 'weight_target'] = weight_target
        s_df.at[0, 'cal_target'] = cal_target
        s_df.at[0, 'prot_target'] = prot_target
        s_df.at[0, 'carb_target'] = carb_target
        s_df.at[0, 'fat_target'] = fat_target
        s_df.at[0, 'sod_target'] = sod_target
        s_df.at[0, 'water_target'] = water_target
        write_data('settings', s_df)
        st.sidebar.success("Targets locked in!")
        st.rerun()

    # Route to correct page logic
    if st.session_state.page == "Dashboard": page_dashboard(s, today)
    elif st.session_state.page == "History": page_history()
    elif st.session_state.page == "Diary": page_diary(today)
    elif st.session_state.page == "Recipes": page_recipes()
    elif st.session_state.page == "Scale": page_body_comp()

if __name__ == "__main__":
    main()
