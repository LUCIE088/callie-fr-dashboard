import re
import calendar
import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as px_go
import streamlit as st

# ---------------- 1. 页面基本配置 ----------------
st.set_page_config(
    page_title="Callie FR 数据看板", 
    page_icon="https://flagcdn.com/w80/fr.png", 
    layout="wide"
)

# ---------------- 2. 统一看板名称 ----------------
st.title("Callie FR 数据看板")
st.caption("数据源：Google Sheet | 支持全局时间联动、跨周期对比与目标进度追踪")

# 真实 Google Sheet 链接
SHEET_URL = "https://docs.google.com/spreadsheets/d/1GLAGMkVx5DMXylG0bbdvkzuqTd8IVfDANhcRrAX6LFU/edit?usp=sharing"

# 星期映射字典 (英文缩写)
WEEKDAY_MAP = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"
}

# ---------------- 3. 读取 Google Sheet 主表数据 (ALL) ----------------
@st.cache_data(ttl=1800)  # 每 30 分钟自动刷新一次数据
def load_and_transform_data():
    sheet_id_match = re.search(r"/d/([a-zA-Z0-9-_]+)", SHEET_URL)
    if not sheet_id_match:
        raise ValueError("无效的 Google Sheet 链接！")
    sheet_id = sheet_id_match.group(1)

    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=ALL"
    raw_df = pd.read_csv(csv_url)

    raw_df = raw_df.iloc[0:18].copy()
    metric_col = raw_df.columns[0]

    df_transposed = raw_df.set_index(metric_col).T.reset_index()
    df_transposed.rename(columns={"index": "Date_Raw"}, inplace=True)

    df_transposed["Date"] = pd.to_datetime(
        df_transposed["Date_Raw"], errors="coerce"
    )
    df_transposed = df_transposed.dropna(subset=["Date"])

    df_transposed["Weekday"] = df_transposed["Date"].dt.weekday.map(WEEKDAY_MAP)
    df_transposed["Date_Label"] = (
        df_transposed["Date"].dt.strftime("%Y-%m-%d")
        + " ("
        + df_transposed["Weekday"]
        + ")"
    )

    for col in df_transposed.columns:
        if col not in ["Date_Raw", "Date", "Weekday", "Date_Label", "星期"]:
            clean_series = (
                df_transposed[col]
                .astype(str)
                .str.replace("$", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.strip()
            )
            df_transposed[col] = pd.to_numeric(clean_series, errors="coerce")

    df_transposed = df_transposed.sort_values(by="Date").reset_index(drop=True)

    if (
        "Superset SEO销售额" in df_transposed.columns
        and "Superset 总销售额" in df_transposed.columns
    ):
        df_transposed["SEO销售额占比(%)"] = (
            df_transposed["Superset SEO销售额"]
            / df_transposed["Superset 总销售额"]
            * 100
        ).round(2)

    return df_transposed, sheet_id


# ---------------- 4. 读取第二个表单 (SEO销售额目标完成情况) ----------------
@st.cache_data(ttl=1800)
def load_sales_target_data(sheet_id):
    try:
        # 表单名：SEO销售额目标完成情况
        csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=SEO%E9%94%80%E5%94%AE%E9%A2%9D%E7%9B%AE%E6%A0%87%E5%AE%8C%E6%80%90%E6%83%85%E5%86%B5"
        target_df = pd.read_csv(csv_url, header=None)
        
        # C 列为 FR 站数据 (索引为 2)
        fr_col = target_df.iloc[:, 2]
        
        # 行号 724 (索引 723) 为总目标额
        target_val_raw = fr_col.iloc[723] if len(fr_col) >= 724 else None
        
        target_val = 0.0
        if pd.notna(target_val_raw):
            clean_str = str(target_val_raw).replace("$", "").replace(",", "").strip()
            try:
                target_val = float(clean_str)
            except ValueError:
                target_val = 0.0

        # 如果 724 行读取不到，降级提取 689-719 行 (索引 688:719) 求和
        if target_val <= 0:
            sub_rows = fr_col.iloc[688:719]
            clean_sub = sub_rows.astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False).str.strip()
            target_val = pd.to_numeric(clean_sub, errors="coerce").sum()

        return target_val
    except Exception as e:
        # 默认备用逻辑
        return 46900.0


try:
    df, sheet_id = load_and_transform_data()
    sales_target_august = load_sales_target_data(sheet_id)

    min_d = df["Date"].min().to_pydatetime()
    max_d = df["Date"].max().to_pydatetime()

    # 默认选中的时间范围：上一个完整自然周（上周一 至 上周日）
    this_week_monday = max_d - pd.Timedelta(days=max_d.weekday())
    last_week_monday = this_week_monday - pd.Timedelta(days=7)
    last_week_sunday = last_week_monday + pd.Timedelta(days=6)

    default_start = max(last_week_monday, min_d)
    default_end = min(last_week_sunday, max_d)
    default_range = [default_start, default_end]

    # =========================================================================
    # 📌 侧边栏置顶：全局统一时间选择器
    # =========================================================================
    st.sidebar.header("🗓️ 全局时间筛选器")
    st.sidebar.caption("在此处调整时间，下方所有图表将自动同步更新！")
    
    selected_date_range = st.sidebar.date_input(
        "📅 选择看板分析时间段：",
        value=default_range,
        min_value=min_d,
        max_value=max_d,
        key="global_date_picker"
    )

    if isinstance(selected_date_range, (list, tuple)) and len(selected_date_range) == 2:
        curr_start, curr_end = selected_date_range[0], selected_date_range[1]
    else:
        curr_start, curr_end = default_start, default_end

    days_span = (curr_end - curr_start).days + 1
    prev_end = curr_start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=days_span - 1)

    df_curr = df[(df["Date"] >= pd.Timestamp(curr_start)) & (df["Date"] <= pd.Timestamp(curr_end))].copy()
    df_prev = df[(df["Date"] >= pd.Timestamp(prev_start)) & (df["Date"] <= pd.Timestamp(prev_end))].copy()

    st.sidebar.info(
        f"**当前选择本期：**\n{curr_start.strftime('%Y-%m-%d')} ~ {curr_end.strftime('%Y-%m-%d')} ({days_span}天)\n\n"
        f"**自动对比上期：**\n{prev_start.strftime('%Y-%m-%d')} ~ {prev_end.strftime('%Y-%m-%d')}"
    )

    # =========================================================================
    # 🎯 顶部分栏：目标完成进度卡片 (销售额 & 流量)
    # =========================================================================
    latest_date = max_d
    current_year = latest_date.year
    current_month = latest_date.month
    current_day = latest_date.day
    _, days_in_month = calendar.monthrange(current_year, current_month)

    # 1. 动态过滤出本月所有已产生的数据
    df_this_month = df[
        (df["Date"].dt.year == current_year) & 
        (df["Date"].dt.month == current_month)
    ]

    # --- 销售额统计 ---
    actual_sales_this_month = (
        df_this_month["Superset SEO销售额"].sum() 
        if "Superset SEO销售额" in df_this_month.columns else 0.0
    )
    target_sales_this_month = sales_target_august if sales_target_august > 0 else 46900.0
    
    sales_pct = (actual_sales_this_month / target_sales_this_month * 100) if target_sales_this_month > 0 else 0.0
    time_pct = (current_day / days_in_month * 100)

    # 提示语逻辑
    if sales_pct >= time_pct:
        sales_status_text = "🔥 销售额超前！"
    else:
        sales_status_text = "✨ 销售额努力冲刺中！"

    # --- 流量统计 ---
    actual_traffic_this_month = (
        df_this_month["SEO 总流量"].sum() 
        if "SEO 总流量" in df_this_month.columns else 0.0
    )
    # 流量目标留用预留位（默认预设 95,800，可自定义修改）
    DEFAULT_TRAFFIC_TARGET = 95800.0
    target_traffic_this_month = DEFAULT_TRAFFIC_TARGET
    
    traffic_pct = (actual_traffic_this_month / target_traffic_this_month * 100) if target_traffic_this_month > 0 else 0.0

    if traffic_pct >= time_pct:
        traffic_status_text = "🚀 流量表现强劲！"
    else:
        traffic_status_text = "✨ 流量蓄力中，冲鸭！"

    # 渲染目标卡片 CSS HTML
    st.markdown("""
    <style>
    .target-card {
        background-color: #FFFFFF;
        border: 1px solid #EAEAEA;
        border-radius: 12px;
        padding: 18px 22px;
        box-shadow: 0px 2px 6px rgba(0,0,0,0.02);
        margin-bottom: 20px;
    }
    .card-header-title {
        font-size: 18px;
        font-weight: 700;
        color: #111827;
        margin-bottom: 14px;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .metric-label {
        font-size: 13px;
        color: #6B7280;
        margin-bottom: 2px;
        display: flex;
        align-items: center;
        gap: 4px;
    }
    .metric-value {
        font-size: 22px;
        font-weight: 800;
        color: #111827;
        margin-bottom: 12px;
    }
    .badge-pct {
        display: inline-block;
        background-color: #E6F4EA;
        color: #137333;
        font-size: 12px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 12px;
        margin-top: 4px;
    }
    .progress-bar-bg {
        background-color: #F3F4F6;
        border-radius: 10px;
        height: 16px;
        width: 100%;
        position: relative;
        overflow: hidden;
        margin-top: 4px;
    }
    .progress-bar-fill-sales {
        background: linear-gradient(90deg, #FF9A9E 0%, #FECFEF 99%, #FECFEF 100%);
        background-color: #FF5376;
        height: 100%;
        border-radius: 10px;
    }
    .progress-bar-fill-time {
        background-color: #60A5FA;
        height: 100%;
        border-radius: 10px;
    }
    .progress-bar-fill-traffic {
        background: linear-gradient(90deg, #A1C4FD 0%, #C2E9FB 100%);
        background-color: #3B82F6;
        height: 100%;
        border-radius: 10px;
    }
    .flag-icon {
        position: absolute;
        right: 8px;
        top: 0px;
        font-size: 11px;
        line-height: 16px;
    }
    </style>
    """, unsafe_allow_html=True)

    col_target1, col_target2 = st.columns(2)

    # 1. 销售额目标进度卡片
    with col_target1:
        sales_bar_width = min(sales_pct, 100.0)
        time_bar_width = min(time_pct, 100.0)
        
        st.markdown(f"""
        <div class="target-card">
            <div class="card-header-title">💰 销售额目标进度</div>
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <div style="width: 35%;">
                    <div class="metric-label">🎯 本月销售总目标</div>
                    <div class="metric-value">${target_sales_this_month:,.2f}</div>
                    <div class="metric-label">💰 累计实际完成</div>
                    <div class="metric-value" style="margin-bottom: 2px;">${actual_sales_this_month:,.2f}</div>
                    <div><span class="badge-pct">↑ 进度 {sales_pct:.1f}%</span></div>
                </div>
                <div style="width: 62%;">
                    <div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; margin-bottom: 4px;">
                        <span>{sales_status_text}</span>
                        <span style="color: #E11D48; font-weight: 700;">{sales_pct:.1f}%</span>
                    </div>
                    <div class="progress-bar-bg" style="margin-bottom: 18px;">
                        <div style="width: {sales_bar_width}%; height: 100%; background: #FF5376; border-radius: 10px; position: relative;">
                            <span style="position: absolute; right: -8px; top: -2px; font-size: 14px;">🚀</span>
                        </div>
                        <span class="flag-icon">🏁</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 12px; color: #6B7280; margin-bottom: 4px;">
                        <span>⏳ 时间进度 ({current_day} / {days_in_month} 天)</span>
                        <span>{time_pct:.1f}%</span>
                    </div>
                    <div class="progress-bar-bg" style="height: 8px;">
                        <div class="progress-bar-fill-time" style="width: {time_bar_width}%;"></div>
                    </div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 2. SEO流量目标进度卡片
    with col_target2:
        traffic_bar_width = min(traffic_pct, 100.0)
        
        st.markdown(f"""
        <div class="target-card">
            <div class="card-header-title">🌊 SEO流量目标进度</div>
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <div style="width: 35%;">
                    <div class="metric-label">🎯 本月流量总目标</div>
                    <div class="metric-value">{int(target_traffic_this_month):,}</div>
                    <div class="metric-label">🌊 累计实际流量</div>
                    <div class="metric-value" style="margin-bottom: 2px;">{int(actual_traffic_this_month):,}</div>
                    <div><span class="badge-pct">↑ 进度 {traffic_pct:.1f}%</span></div>
                </div>
                <div style="width: 62%;">
                    <div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; margin-bottom: 4px;">
                        <span>{traffic_status_text}</span>
                        <span style="color: #2563EB; font-weight: 700;">{traffic_pct:.1f}%</span>
                    </div>
                    <div class="progress-bar-bg" style="margin-bottom: 18px;">
                        <div style="width: {traffic_bar_width}%; height: 100%; background: #2563EB; border-radius: 10px; position: relative;">
                            <span style="position: absolute; right: -8px; top: -2px; font-size: 14px;">🚀</span>
                        </div>
                        <span class="flag-icon">🏁</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 12px; color: #6B7280; margin-bottom: 4px;">
                        <span>⏳ 时间进度 ({current_day} / {days_in_month} 天)</span>
                        <span>{time_pct:.1f}%</span>
                    </div>
                    <div class="progress-bar-bg" style="height: 8px;">
                        <div class="progress-bar-fill-time" style="width: {time_bar_width}%;"></div>
                    </div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 辅助函数：生成单日常规对比折线图 (法国蓝红配色)
    def create_comparison_figure(df_c, df_p, metric_cols, title, y_title="数值"):
        fig = px_go.Figure()
        for i, col in enumerate(metric_cols):
            if col in df_c.columns:
                line_color = "#002654" if i == 0 else "#1D70B8"
                fig.add_trace(px_go.Scatter(
                    x=df_c["Date_Label"],
                    y=df_c[col],
                    name=f"[本期] {col}",
                    line=dict(color=line_color, width=3),
                    mode="lines+markers"
                ))
        
        df_p_aligned = df_p.reset_index(drop=True)
        df_c_aligned = df_c.reset_index(drop=True)
        
        for i, col in enumerate(metric_cols):
            if col in df_p_aligned.columns:
                line_color = "#CE1126" if i == 0 else "#E66371"
                fig.add_trace(px_go.Scatter(
                    x=df_c_aligned["Date_Label"],
                    y=df_p_aligned[col],
                    name=f"[上期] {col}",
                    line=dict(color=line_color, width=2, dash="dash"),
                    mode="lines"
                ))

        fig.update_layout(
            title=title,
            hovermode="x unified",
            xaxis_title="Date",
            yaxis_title=y_title,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        return fig

    # 辅助函数：绘制“总数值对比”柱状图 (法国蓝红配色)
    def create_total_bar_chart(df_c, df_p, metric_cols, title, y_title="累计总数", is_currency=True):
        categories = []
        c_totals = []
        p_totals = []

        for col in metric_cols:
            if col in df_c.columns:
                categories.append(col)
                c_totals.append(df_c[col].sum())
                p_totals.append(df_p[col].sum() if col in df_p.columns else 0.0)

        fmt_func = (lambda v: f"${v:,.2f}") if is_currency else (lambda v: f"{int(v):,}")

        fig = px_go.Figure()
        fig.add_trace(px_go.Bar(
            x=categories,
            y=c_totals,
            name="本期总额" if is_currency else "本期总量",
            marker_color="#002654",
            text=[fmt_func(v) for v in c_totals],
            textposition="auto"
        ))
        fig.add_trace(px_go.Bar(
            x=categories,
            y=p_totals,
            name="上期总额" if is_currency else "上期总量",
            marker_color="#CE1126",
            text=[fmt_func(v) for v in p_totals],
            textposition="auto"
        ))

        fig.update_layout(
            title=title,
            barmode="group",
            yaxis_title=y_title,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        return fig

    # =========================================================================
    # 📊 1. 核心指标周期对比表格
    # =========================================================================
    st.header("📊 核心数据周期对比 (本期 vs 上期)")
    
    curr_str = f"{curr_start.strftime('%m/%d')}-{curr_end.strftime('%m/%d')}"
    prev_str = f"{prev_start.strftime('%m/%d')}-{prev_end.strftime('%m/%d')}"
    comp_label = f"环比前 {days_span} 天"

    metrics_config = [
        {"name": "销售额 (Superset)", "col": "Superset SEO销售额", "type": "currency"},
        {"name": "流量 (GA4 SEO总流量)", "col": "SEO 总流量", "type": "number"},
        {"name": "流量 (Blog)", "col": "SEO Blog流量", "type": "number"},
        {"name": "流量 (站内)", "col": "SEO 站内流量", "type": "number"},
        {"name": "流量 (AI Assistant)", "col": "AI Assistant 流量", "type": "number"},
        {"name": "销售额 (AI Assistant)", "col": "AI Assistant 销售额", "type": "currency"},
        {"name": "点击 (GSC)", "col": "点击 (GSC)", "type": "number"},
        {"name": "点击 (非品牌词点击)", "col": "点击 (非品牌词点击)", "type": "number"},
        {"name": "点击 (Blog)", "col": "点击 (Blog)", "type": "number"},
        {"name": "点击 (非Blog)", "col": "点击 (非Blog)", "type": "number"},
        {"name": "点击 (非品牌词非Blog)", "col": "点击 (非品牌词非Blog)", "type": "number"},
        {"name": "点击 (非品牌词非Blog非utm)", "col": "点击 (非品牌词非Blog非utm)", "type": "number"},
    ]

    table_rows = []
    for m in metrics_config:
        col_name = m["col"]
        m_type = m["type"]
        
        v_curr = df_curr[col_name].sum() if col_name in df_curr.columns else 0.0
        v_prev = df_prev[col_name].sum() if col_name in df_prev.columns else 0.0

        if v_prev > 0:
            growth = ((v_curr - v_prev) / v_prev) * 100
            growth_str = f"{growth:+.2f}%"
        elif v_prev == 0 and v_curr > 0:
            growth_str = "+100.00%"
        else:
            growth_str = "0.00%"

        if m_type == "currency":
            curr_fmt = f"${v_curr:,.2f}"
            prev_fmt = f"${v_prev:,.2f}"
        else:
            curr_fmt = f"{int(v_curr):,}"
            prev_fmt = f"{int(v_prev):,}"

        table_rows.append({
            "日期指标": m["name"],
            f"上期 ({prev_str})": prev_fmt,
            f"本期 ({curr_str})": curr_fmt,
            comp_label: growth_str
        })

    comp_df = pd.DataFrame(table_rows)

    def style_growth(val):
        if val.startswith("+"):
            return f"<span style='color: #002654; font-weight: bold;'>{val}</span>"
        elif val.startswith("-"):
            return f"<span style='color: #CE1126; font-weight: bold;'>{val}</span>"
        return f"<span>{val}</span>"

    comp_df[comp_label] = comp_df[comp_label].apply(style_growth)

    st.write(comp_df.to_html(escape=False, index=False), unsafe_allow_html=True)
    st.markdown("---")

    # =========================================================================
    # 图表 1：Superset 销售额对比与占比
    # =========================================================================
    st.header("1. 销售额表现（Superset）")
    col_sup1, col_sup2 = st.columns([2, 1.2])

    with col_sup1:
        df_p_aligned = df_prev.reset_index(drop=True)
        df_c_aligned = df_curr.reset_index(drop=True)

        fig1 = px_go.Figure()
        fig1.add_trace(px_go.Bar(
            x=df_c_aligned["Date_Label"],
            y=df_c_aligned.get("Superset 总销售额", [0]*len(df_c_aligned)),
            name="[本期] Superset 总销售额 ($)",
            marker_color="#002654"
        ))
        fig1.add_trace(px_go.Bar(
            x=df_c_aligned["Date_Label"],
            y=df_p_aligned.get("Superset 总销售额", [0]*len(df_p_aligned)),
            name="[上期] Superset 总销售额 ($)",
            marker_color="#CE1126",
            opacity=0.5
        ))
        if "Superset SEO销售额" in df_c_aligned.columns:
            fig1.add_trace(px_go.Scatter(
                x=df_c_aligned["Date_Label"],
                y=df_c_aligned["Superset SEO销售额"],
                name="[本期] Superset SEO销售额 ($)",
                line=dict(color="#1D70B8", width=3)
            ))
        if "Superset SEO销售额" in df_p_aligned.columns:
            fig1.add_trace(px_go.Scatter(
                x=df_c_aligned["Date_Label"],
                y=df_p_aligned["Superset SEO销售额"],
                name="[上期] Superset SEO销售额 ($)",
                line=dict(color="#E66371", width=2, dash="dash")
            ))

        fig1.update_layout(
            title="Superset 每日销售额走势 (本期 vs 上期)",
            hovermode="x unified",
            barmode="group",
            xaxis_title="Date",
            yaxis=dict(title="销售额 ($)"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig1, use_container_width=True)

    with col_sup2:
        tab_sup_all, tab_sup_seo = st.tabs(["📊 总销售额与 SEO 销售额", "🎯 仅看 SEO 销售额"])
        
        with tab_sup_all:
            fig1_total_all = create_total_bar_chart(
                df_curr, df_prev, 
                ["Superset 总销售额", "Superset SEO销售额"], 
                "Superset 所选周期销售总额对比",
                y_title="累计总销售额 ($)",
                is_currency=True
            )
            st.plotly_chart(fig1_total_all, use_container_width=True)
            
        with tab_sup_seo:
            fig1_total_seo = create_total_bar_chart(
                df_curr, df_prev, 
                ["Superset SEO销售额"], 
                "Superset SEO 销售额对比 (独立缩放)",
                y_title="SEO 累计销售额 ($)",
                is_currency=True
            )
            st.plotly_chart(fig1_total_seo, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 2：GA4 销售额对比
    # =========================================================================
    st.header("2. 销售额表现（GA4）")
    col_ga1, col_ga2 = st.columns([2, 1.2])

    with col_ga1:
        fig2 = create_comparison_figure(
            df_curr, df_prev, 
            ["GA4 网站总销售额", "GA4 SEO销售额"], 
            "GA4 每日销售额趋势 (本期 vs 上期)", 
            y_title="金额 ($)"
        )
        st.plotly_chart(fig2, use_container_width=True)

    with col_ga2:
        tab_ga_all, tab_ga_seo = st.tabs(["📊 总销售额与 SEO 销售额", "🎯 仅看 SEO 销售额"])
        
        with tab_ga_all:
            fig2_total_all = create_total_bar_chart(
                df_curr, df_prev, 
                ["GA4 网站总销售额", "GA4 SEO销售额"], 
                "GA4 所选周期销售总额对比",
                y_title="累计总销售额 ($)",
                is_currency=True
            )
            st.plotly_chart(fig2_total_all, use_container_width=True)
            
        with tab_ga_seo:
            fig2_total_seo = create_total_bar_chart(
                df_curr, df_prev, 
                ["GA4 SEO销售额"], 
                "GA4 SEO 销售额对比 (独立缩放)",
                y_title="SEO 累计销售额 ($)",
                is_currency=True
            )
            st.plotly_chart(fig2_total_seo, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 3：多渠道流量对比
    # =========================================================================
    st.header("3. 多渠道流量对比")
    col_tr1, col_tr2 = st.columns([2, 1.2])

    with col_tr1:
        fig3 = create_comparison_figure(
            df_curr, df_prev, 
            ["SEO 总流量", "SEO Blog流量", "SEO 站内流量"], 
            "SEO 渠道流量趋势与上期对比", 
            y_title="访客量 (Sessions)"
        )
        st.plotly_chart(fig3, use_container_width=True)

    with col_tr2:
        fig3_total = create_total_bar_chart(
            df_curr, df_prev, 
            ["SEO 总流量", "SEO Blog流量", "SEO 站内流量"], 
            "多渠道所选周期总流量对比",
            y_title="累计总访客量 (Sessions)",
            is_currency=False
        )
        st.plotly_chart(fig3_total, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 4：跳出率
    # =========================================================================
    st.header("4. 网站跳出率 Bounce Rate对比")
    fig4 = create_comparison_figure(
        df_curr, df_prev, 
        ["跳出率"], 
        "每日跳出率波动与上期对比", 
        y_title="跳出率 (%)"
    )
    fig4.update_layout(yaxis_range=[0, 100])
    st.plotly_chart(fig4, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 5：AI Assistant (GEO) 表现
    # =========================================================================
    st.header("5. AI Assistant 表现 (GEO 销售与流量)")
    col_ai1, col_ai2, col_ai3 = st.columns([1.1, 1.1, 1.2])

    with col_ai1:
        fig5_sales = create_comparison_figure(
            df_curr, df_prev, 
            ["AI Assistant 销售额"], 
            "AI Assistant 每日销售额 ($)", 
            y_title="销售额 ($)"
        )
        st.plotly_chart(fig5_sales, use_container_width=True)

    with col_ai2:
        fig5_traffic = create_comparison_figure(
            df_curr, df_prev, 
            ["AI Assistant 流量"], 
            "AI Assistant 每日引流 (Sessions)", 
            y_title="访客量"
        )
        st.plotly_chart(fig5_traffic, use_container_width=True)

    with col_ai3:
        tab_ai_sales, tab_ai_traffic = st.tabs(["💰 销售总额对比", "👥 流量总数对比"])
        
        with tab_ai_sales:
            fig5_total_sales = create_total_bar_chart(
                df_curr, df_prev, 
                ["AI Assistant 销售额"], 
                "AI Assistant 销售总额对比",
                y_title="累计总销售额 ($)",
                is_currency=True
            )
            st.plotly_chart(fig5_total_sales, use_container_width=True)

        with tab_ai_traffic:
            fig5_total_traffic = create_total_bar_chart(
                df_curr, df_prev, 
                ["AI Assistant 流量"], 
                "AI Assistant 引流总数对比",
                y_title="累计总访客量 (Sessions)",
                is_currency=False
            )
            st.plotly_chart(fig5_total_traffic, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 6：谷歌收录数据
    # =========================================================================
    st.header("6. 谷歌收录数据对比 ")
    fig6 = create_comparison_figure(
        df_curr, df_prev, 
        ["收录", "Blog 收录"], 
        "总收录量与 Blog 专项收录量趋势", 
        y_title="页数"
    )
    st.plotly_chart(fig6, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 7：外链与外链域名广度
    # =========================================================================
    st.header("7. 外链与外链域名广度 (Backlinks)")
    col_link1, col_link2 = st.columns(2)

    with col_link1:
        fig7_links = create_comparison_figure(
            df_curr, df_prev, 
            ["外链"], 
            "外链总数走势与上期对比", 
            y_title="外链数"
        )
        st.plotly_chart(fig7_links, use_container_width=True)

    with col_link2:
        fig7_domains = create_comparison_figure(
            df_curr, df_prev, 
            ["外链域名广度"], 
            "外链参照域名广度与上期对比", 
            y_title="域名数"
        )
        st.plotly_chart(fig7_domains, use_container_width=True)

    with st.expander("📄 点击查看转换后的完整数据表"):
        st.dataframe(df.sort_values(by="Date", ascending=False))

except Exception as e:
    st.error(
        f"⚠️ 数据加载失败！请确保 Google Sheet 的 Share 权限设置为“Anyone with the link can view”。\n\n错误信息: {e}"
    )
