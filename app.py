import re
import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as px_go
import streamlit as st

# ---------------- 1. 页面基本配置 ----------------
st.set_page_config(
    page_title="Callie FR 数据看板", page_icon="https://flagcdn.com/w80/fr.png", layout="wide"
)

col_flag, col_title = st.columns([0.06, 0.94], gap="small")

with col_flag:
    # 展示法国国旗图片
    st.image("https://flagcdn.com/w80/fr.png", width=55)

with col_title:
    st.title("Callie FR 数据看板")

st.caption("数据源：Google Sheet (ALL 工作表) | 支持周期环比对比与单图表独立时间筛选")

# 真实 Google Sheet 链接
SHEET_URL = "https://docs.google.com/spreadsheets/d/1GLAGMkVx5DMXylG0bbdvkzuqTd8IVfDANhcRrAX6LFU/edit?usp=sharing"

# 星期映射字典
WEEKDAY_MAP = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"
}

# ---------------- 2. 直连读取 Google Sheet 数据 ----------------
@st.cache_data(ttl=1800)  # 每 30 分钟自动刷新一次数据
def load_and_transform_data():
    sheet_id_match = re.search(r"/d/([a-zA-Z0-9-_]+)", SHEET_URL)
    if not sheet_id_match:
        raise ValueError("无效的 Google Sheet 链接！")
    sheet_id = sheet_id_match.group(1)

    # 通过 GViz CSV 接口读取 ALL 工作表
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=ALL"
    raw_df = pd.read_csv(csv_url)

    # 1. 截取前 18 行（指标数据）
    raw_df = raw_df.iloc[0:18].copy()

    # 2. 获取指标列名称
    metric_col = raw_df.columns[0]

    # 3. 转置：横向日期变纵向行
    df_transposed = raw_df.set_index(metric_col).T.reset_index()
    df_transposed.rename(columns={"index": "Date_Raw"}, inplace=True)

    # 4. 解析与清洗日期
    df_transposed["Date"] = pd.to_datetime(
        df_transposed["Date_Raw"], errors="coerce"
    )
    df_transposed = df_transposed.dropna(subset=["Date"])

    # 5. 格式化横坐标标签（格式：2026-07-27 (周一)）
    df_transposed["Weekday"] = df_transposed["Date"].dt.weekday.map(WEEKDAY_MAP)
    df_transposed["Date_Label"] = (
        df_transposed["Date"].dt.strftime("%Y-%m-%d")
        + " ("
        + df_transposed["Weekday"]
        + ")"
    )

    # 6. 自动剔除 $、,、% 并转为数值
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

    # 按时间升序排列
    df_transposed = df_transposed.sort_values(by="Date").reset_index(drop=True)

    # 计算 Superset SEO 销售额占比 (%)
    if (
        "Superset SEO销售额" in df_transposed.columns
        and "Superset 总销售额" in df_transposed.columns
    ):
        df_transposed["SEO销售额占比(%)"] = (
            df_transposed["Superset SEO销售额"]
            / df_transposed["Superset 总销售额"]
            * 100
        ).round(2)

    return df_transposed


# 辅助函数：根据单个图表选择的时间范围过滤数据
def filter_df_by_date(df, date_range):
    if not date_range:
        return df

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date, end_date = date_range
        mask = (df["Date"] >= pd.Timestamp(start_date)) & (
            df["Date"] <= pd.Timestamp(end_date)
        )
        return df.loc[mask]

    elif isinstance(date_range, (list, tuple)) and len(date_range) == 1:
        start_date = date_range[0]
        mask = df["Date"] >= pd.Timestamp(start_date)
        return df.loc[mask]

    return df


try:
    df = load_and_transform_data()
    min_d = df["Date"].min().to_pydatetime()
    max_d = df["Date"].max().to_pydatetime()

    # 默认选中的时间范围：最近一周
    default_start = max_d - pd.Timedelta(days=6)
    if default_start < min_d:
        default_start = min_d
    default_range = [default_start, max_d]

    # =========================================================================
    # 🌟 顶部：核心指标周期对比表格 (周/月/年/自定义)
    # =========================================================================
    st.header("📊 核心数据周期对比 (周/月/年 环比)")
    
    col_mode, col_date = st.columns([1, 2])
    with col_mode:
        compare_mode = st.radio(
            "选择对比周期粒度：",
            ["周 (Week)", "月 (Month)", "自定义时间段"],
            horizontal=True,
            key="compare_mode"
        )
    
    # 根据选择模式计算本期与上期
    if compare_mode == "周 (Week)":
        # 当前最新日期所在周的上周一与上周日作为本期
        curr_end = max_d
        curr_start = max_d - pd.Timedelta(days=6)
        prev_end = curr_start - pd.Timedelta(days=1)
        prev_start = prev_end - pd.Timedelta(days=6)
        comp_label = "环比上周"
    elif compare_mode == "月 (Month)":
        # 默认最近 30 天 vs 再往前 30 天
        curr_end = max_d
        curr_start = max_d - pd.Timedelta(days=29)
        prev_end = curr_start - pd.Timedelta(days=1)
        prev_start = prev_end - pd.Timedelta(days=29)
        comp_label = "环比上月"
    else:
        with col_date:
            custom_range = st.date_input(
                "📅 选择本期时间段（系统将自动计算同等长度的前一周期）：",
                value=default_range,
                min_value=min_d,
                max_value=max_d,
                key="custom_compare_range"
            )
            if isinstance(custom_range, (list, tuple)) and len(custom_range) == 2:
                curr_start, curr_end = custom_range[0], custom_range[1]
                days_diff = (curr_end - curr_start).days
                prev_end = curr_start - pd.Timedelta(days=1)
                prev_start = prev_end - pd.Timedelta(days=days_diff)
            else:
                curr_start, curr_end = default_start, max_d
                prev_start, prev_end = curr_start - pd.Timedelta(days=7), curr_start - pd.Timedelta(days=1)
        comp_label = f"环比前{ (curr_end - curr_start).days + 1 }天"

    # 格式化日期显示字符串 (例如 7/13-7/19)
    curr_str = f"{curr_start.strftime('%m/%d')}-{curr_end.strftime('%m/%d')}"
    prev_str = f"{prev_start.strftime('%m/%d')}-{prev_end.strftime('%m/%d')}"

    # 提取本期与上期数据
    df_curr = df[(df["Date"] >= pd.Timestamp(curr_start)) & (df["Date"] <= pd.Timestamp(curr_end))]
    df_prev = df[(df["Date"] >= pd.Timestamp(prev_start)) & (df["Date"] <= pd.Timestamp(prev_end))]

    # 定义对比维度与列名映射 (指标名 -> Sheet中对应列名 / 格式类型)
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
        
        # 本期值与上期值求和
        v_curr = df_curr[col_name].sum() if col_name in df_curr.columns else 0.0
        v_prev = df_prev[col_name].sum() if col_name in df_prev.columns else 0.0

        # 计算环比增长率
        if v_prev > 0:
            growth = ((v_curr - v_prev) / v_prev) * 100
            growth_str = f"{growth:+.2f}%"
        elif v_prev == 0 and v_curr > 0:
            growth_str = "+100.00%"
        else:
            growth_str = "0.00%"

        # 格式化显示数值
        if m_type == "currency":
            curr_fmt = f"${v_curr:,.2f}"
            prev_fmt = f"${v_prev:,.2f}"
        else:
            curr_fmt = f"{int(v_curr):,}"
            prev_fmt = f"{int(v_prev):,}"

        table_rows.append({
            "日期指标": m["name"],
            prev_str: prev_fmt,
            curr_str: curr_fmt,
            comp_label: growth_str
        })

    comp_df = pd.DataFrame(table_rows)

    # 使用 HTML 渲染高颜值对比表格（支持涨红跌绿/涨绿跌红高亮）
    def style_growth(val):
        if val.startswith("+"):
            return f"<span style='color: #2D6A4F; font-weight: bold;'>{val}</span>"
        elif val.startswith("-"):
            return f"<span style='color: #D90429; font-weight: bold;'>{val}</span>"
        return f"<span>{val}</span>"

    comp_df[comp_label] = comp_df[comp_label].apply(style_growth)

    # 渲染 Markdown 表格
    st.write(
        comp_df.to_html(escape=False, index=False),
        unsafe_allow_html=True
    )
    st.caption("💡 提示：点击类指标若 Google Sheet 中尚未添加对应列，默认显示 0；表格内环比自动依据选择的时间跨度精确计算。")

    st.markdown("---")

    # =========================================================================
    # 图表 1：Superset 销售额对比与占比
    # =========================================================================
    st.header("1. Superset 销售额对比与 SEO 占比")
    d1 = st.date_input(
        "📅 选择时间范围 (Superset 销售额)",
        value=default_range,
        min_value=min_d,
        max_value=max_d,
        key="d1",
    )
    df1 = filter_df_by_date(df, d1)

    fig1 = px_go.Figure()
    fig1.add_trace(
        px_go.Bar(
            x=df1["Date_Label"],
            y=df1.get("Superset 总销售额", df1.iloc[:, 1]),
            name="Superset 总销售额 ($)",
            marker_color="#2D6A4F",
        )
    )
    if "Superset SEO销售额" in df1.columns:
        fig1.add_trace(
            px_go.Scatter(
                x=df1["Date_Label"],
                y=df1["Superset SEO销售额"],
                name="Superset SEO销售额 ($)",
                line=dict(color="#52B788", width=3),
            )
        )
    if "SEO销售额占比(%)" in df1.columns:
        fig1.add_trace(
            px_go.Scatter(
                x=df1["Date_Label"],
                y=df1["SEO销售额占比(%)"],
                name="SEO 销售额占比 (%)",
                yaxis="y2",
                line=dict(color="#D8F3DC", width=2, dash="dot"),
            )
        )

    fig1.update_layout(
        title="Superset 总销售额 vs SEO 销售额与占比走势",
        hovermode="x unified",
        xaxis_title="Date",
        yaxis=dict(title="销售额 ($)"),
        yaxis2=dict(
            title="SEO 占比 (%)", overlaying="y", side="right", showgrid=False
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
        ),
    )
    st.plotly_chart(fig1, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 2：GA4 销售额对比
    # =========================================================================
    st.header("2. GA4 平台销售额对比")
    d2 = st.date_input(
        "📅 选择时间范围 (GA4 销售额)",
        value=default_range,
        min_value=min_d,
        max_value=max_d,
        key="d2",
    )
    df2 = filter_df_by_date(df, d2)

    ga4_cols = [
        c for c in ["GA4 网站总销售额", "GA4 SEO销售额"] if c in df2.columns
    ]
    if ga4_cols:
        fig2 = px.line(
            df2,
            x="Date_Label",
            y=ga4_cols,
            labels={"value": "金额 ($)", "variable": "指标类别", "Date_Label": "Date"},
            color_discrete_map={
                "GA4 网站总销售额": "#1B4332",
                "GA4 SEO销售额": "#74C69D",
            },
            title="GA4 网站总销售额 vs GA4 SEO销售额 趋势",
        )
        fig2.update_layout(hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 3：多渠道流量对比
    # =========================================================================
    st.header("3. 多渠道流量对比")
    d3 = st.date_input(
        "📅 选择时间范围 (流量对比)",
        value=default_range,
        min_value=min_d,
        max_value=max_d,
        key="d3",
    )
    df3 = filter_df_by_date(df, d3)

    traffic_cols = [
        c
        for c in ["网站总流量", "SEO 总流量", "SEO Blog流量", "SEO 站内流量"]
        if c in df3.columns
    ]
    if traffic_cols:
        fig3 = px.line(
            df3,
            x="Date_Label",
            y=traffic_cols,
            labels={
                "value": "访客量 (Sessions)",
                "variable": "流量渠道",
                "Date_Label": "Date",
            },
            color_discrete_sequence=[
                "#081C15",
                "#2D6A4F",
                "#52B788",
                "#B7E4C7"
            ],
            title="网站总流量 / SEO总流量 / Blog流量 / 站内流量全貌对比",
        )
        fig3.update_layout(hovermode="x unified")
        st.plotly_chart(fig3, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 4：跳出率
    # =========================================================================
    st.header("4. 网站跳出率 (Bounce Rate)")
    d4 = st.date_input(
        "📅 选择时间范围 (跳出率)",
        value=default_range,
        min_value=min_d,
        max_value=max_d,
        key="d4",
    )
    df4 = filter_df_by_date(df, d4)

    if "跳出率" in df4.columns:
        fig4 = px.area(
            df4,
            x="Date_Label",
            y="跳出率",
            labels={"跳出率": "跳出率 (%)", "Date_Label": "Date"},
            title="每日跳出率波动趋势",
            color_discrete_sequence=["#95D5B2"],
        )
        fig4.update_layout(hovermode="x unified", yaxis_range=[0, 100])
        st.plotly_chart(fig4, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 5：AI Assistant (GEO) 表现
    # =========================================================================
    st.header("5. AI Assistant 表现 (GEO 销售与流量)")
    d5 = st.date_input(
        "📅 选择时间范围 (AI Assistant)",
        value=default_range,
        min_value=min_d,
        max_value=max_d,
        key="d5",
    )
    df5 = filter_df_by_date(df, d5)

    col_ai1, col_ai2 = st.columns(2)

    with col_ai1:
        if "AI Assistant 销售额" in df5.columns:
            fig5_sales = px.bar(
                df5,
                x="Date_Label",
                y="AI Assistant 销售额",
                labels={"AI Assistant 销售额": "销售额 ($)", "Date_Label": "Date"},
                title="AI Assistant 每日销售额 ($)",
                color_discrete_sequence=["#1B4332"],
            )
            st.plotly_chart(fig5_sales, use_container_width=True)

    with col_ai2:
        if "AI Assistant 流量" in df5.columns:
            fig5_traffic = px.line(
                df5,
                x="Date_Label",
                y="AI Assistant 流量",
                labels={"AI Assistant 流量": "访客量", "Date_Label": "Date"},
                title="AI Assistant 每日引流 (Sessions)",
                color_discrete_sequence=["#40916C"],
            )
            fig5_traffic.update_traces(mode="lines+markers")
            st.plotly_chart(fig5_traffic, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 6：谷歌收录数据
    # =========================================================================
    st.header("6. 谷歌收录数据")
    d6 = st.date_input(
        "📅 选择时间范围 (谷歌收录)",
        value=default_range,
        min_value=min_d,
        max_value=max_d,
        key="d6",
    )
    df6 = filter_df_by_date(df, d6)

    index_cols = [c for c in ["收录", "Blog 收录"] if c in df6.columns]
    if index_cols:
        fig6 = px.line(
            df6,
            x="Date_Label",
            y=index_cols,
            labels={"value": "页数", "variable": "收录类型", "Date_Label": "Date"},
            color_discrete_map={
                "收录": "#2D6A4F",
                "Blog 收录": "#74C69D"
            },
            title="总收录量 vs Blog 专项收录量",
        )
        fig6.update_layout(hovermode="x unified")
        st.plotly_chart(fig6, use_container_width=True)

    st.markdown("---")

    # =========================================================================
    # 图表 7：外链与外链域名广度
    # =========================================================================
    st.header("7. 外链与外链域名广度 (Backlinks)")
    d7 = st.date_input(
        "📅 选择时间范围 (外链)",
        value=default_range,
        min_value=min_d,
        max_value=max_d,
        key="d7",
    )
    df7 = filter_df_by_date(df, d7)

    col_link1, col_link2 = st.columns(2)

    with col_link1:
        if "外链" in df7.columns:
            fig7_links = px.line(
                df7,
                x="Date_Label",
                y="外链",
                labels={"外链": "外链数", "Date_Label": "Date"},
                title="外链总数走势",
                color_discrete_sequence=["#1B4332"],
            )
            st.plotly_chart(fig7_links, use_container_width=True)

    with col_link2:
        if "外链域名广度" in df7.columns:
            fig7_domains = px.line(
                df7,
                x="Date_Label",
                y="外链域名广度",
                labels={"外链域名广度": "域名数", "Date_Label": "Date"},
                title="外链参照域名广度",
                color_discrete_sequence=["#52B788"],
            )
            st.plotly_chart(fig7_domains, use_container_width=True)

    # 底部表格明细
    with st.expander("📄 点击查看转换后的完整数据表"):
        st.dataframe(df.sort_values(by="Date", ascending=False))

except Exception as e:
    st.error(
        f"⚠️ 数据加载失败！请确保 Google Sheet 的 Share 权限设置为“Anyone with the link can view”。\n\n错误信息: {e}"
    )