"""NEXUS — Enterprise Sales Intelligence & Strategic Analytics Platform."""

from __future__ import annotations

import html
import json
import logging
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import seaborn as sns
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from analytics import (
    ForecastResult,
    build_rfm,
    cohort_retention,
    discount_association,
    forecast_revenue,
    monthly_revenue,
    realized_sales,
)
from reporting import build_excel_report, build_pdf_report


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "processed" / "sales_cleaned.csv"
QUALITY_FILE = ROOT / "data" / "processed" / "quality_report.json"
LOGGER = logging.getLogger("nexus")
PALETTE = {
    "ink": "#142b3b",
    "teal": "#008b76",
    "blue": "#4d78a8",
    "amber": "#c78a27",
    "coral": "#c86b5b",
    "muted": "#718393",
}

st.set_page_config(
    page_title="NEXUS | Enterprise Sales Intelligence",
    page_icon="N",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
:root { --ink:#142b3b; --muted:#718393; --teal:#008b76; --line:#e4eaed; --surface:#fff; --canvas:#f4f7f8; --sidebar:#102a3a; }
html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
.stApp { background:var(--canvas); color:var(--ink); }
[data-testid="stSidebar"] { background:var(--sidebar); }
[data-testid="stSidebar"] * { color:#e4edf1 !important; }
[data-testid="stSidebar"] label { font-size:.82rem; }
.block-container { max-width:1600px; padding:1.75rem 2.1rem 2.8rem; }
h1,h2,h3 { font-family:'Manrope',sans-serif !important; color:var(--ink); }
.nexus-brand { font:800 1rem Manrope; letter-spacing:.12em; color:#f4f8fa; padding:.3rem .1rem; }
.nexus-brand span { color:#21b79c; }
.nexus-sub { font-size:.62rem; letter-spacing:.13em; color:#8fa4ad; margin:.1rem 0 1.15rem; }
.eyebrow { font-size:.67rem; font-weight:700; letter-spacing:.15em; color:var(--teal); text-transform:uppercase; }
.hero-title { font:800 1.95rem Manrope; letter-spacing:-.045em; margin:.22rem 0; }
.hero-sub { color:var(--muted); font-size:.88rem; }
.kpi-card { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:17px 18px; min-height:112px; box-shadow:0 2px 6px #18394a05; transition:transform .16s ease, box-shadow .16s ease; }
.kpi-card:hover { transform:translateY(-2px); box-shadow:0 7px 18px #18394a0e; }
.kpi-label { font-size:.69rem; font-weight:700; letter-spacing:.06em; color:var(--muted); }
.kpi-value { font:800 1.62rem Manrope; color:var(--ink); margin-top:.55rem; letter-spacing:-.035em; }
.kpi-note { color:var(--muted); font-size:.7rem; margin-top:.12rem; }
.section-label { font:750 1.02rem Manrope; margin:1.15rem 0 .2rem; }
.section-note { color:var(--muted); font-size:.76rem; margin-bottom:.65rem; }
div[data-testid="stPlotlyChart"] { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:6px; }
.insight { background:#edf7f4; border:1px solid #d5eae4; border-left:3px solid var(--teal); padding:12px 15px; border-radius:0 9px 9px 0; color:#244a4b; font-size:.82rem; }
.footer { color:#8998a1; font-size:.68rem; border-top:1px solid var(--line); padding-top:13px; margin-top:22px; }
div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:10px; overflow:hidden; }
@keyframes reveal { from {opacity:0; transform:translateY(4px)} to {opacity:1; transform:translateY(0)} }
section.main > div { animation:reveal .22s ease-out; }
@media(max-width:800px) { .block-container {padding:1.1rem .85rem 2rem} .hero-title {font-size:1.55rem} }
"""
DARK_CSS = """
:root { --ink:#e7edf0; --muted:#9aabb4; --teal:#34c1a6; --line:#2b3c46; --surface:#1b2b35; --canvas:#14232c; --sidebar:#0e1e27; }
.kpi-card { box-shadow:none; }
.kpi-card:hover { box-shadow:0 7px 18px #00000028; }
.insight { background:#17342f; border-color:#275247; color:#c8e5dc; }
div[data-testid="stPlotlyChart"] { box-shadow:none; }
"""


def apply_theme(theme: str) -> None:
    css = BASE_CSS + (DARK_CSS if theme == "Dark" else "")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


@st.cache_data(show_spinner="Loading cleaned sales data…")
def load_csv_data(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["Order_Date"])
    for column in ["Gender", "Category", "Sub_Category", "Region", "State", "City", "Payment_Method", "Order_Status"]:
        frame[column] = frame[column].astype("category")
    return frame


@st.cache_resource
def mysql_engine():
    database_url = os.environ.get("SALES_DATABASE_URL")
    if not database_url:
        raise RuntimeError("SALES_DATABASE_URL is not configured.")
    return create_engine(database_url, pool_pre_ping=True)


@st.cache_data(show_spinner="Loading sales from MySQL…")
def load_mysql_data() -> pd.DataFrame:
    query = text(
        """
        SELECT
            fs.order_id AS Order_ID,
            d.full_date AS Order_Date,
            c.customer_id AS Customer_ID,
            c.customer_name AS Customer_Name,
            c.gender AS Gender,
            c.age AS Age,
            p.product_id AS Product_ID,
            p.product_name AS Product_Name,
            p.category AS Category,
            p.sub_category AS Sub_Category,
            g.region AS Region,
            g.state AS State,
            g.city AS City,
            fs.quantity AS Quantity,
            fs.unit_price AS Unit_Price,
            fs.discount AS Discount,
            fs.revenue AS Revenue,
            fs.cost AS Cost,
            fs.profit AS Profit,
            fs.payment_method AS Payment_Method,
            fs.order_status AS Order_Status,
            fs.shipping_days AS Shipping_Days
        FROM fact_sales fs
        JOIN dim_date d ON d.date_key = fs.date_key
        JOIN dim_customer c ON c.customer_key = fs.customer_key
        JOIN dim_product p ON p.product_key = fs.product_key
        JOIN dim_geography g ON g.geography_key = fs.geography_key
        """
    )
    frame = pd.read_sql(query, mysql_engine(), parse_dates=["Order_Date"])
    for column in ["Age", "Quantity", "Shipping_Days"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    for column in ["Unit_Price", "Discount", "Revenue", "Cost", "Profit"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    for column in ["Gender", "Category", "Sub_Category", "Region", "State", "City", "Payment_Method", "Order_Status"]:
        frame[column] = frame[column].astype("category")
    return frame


@st.cache_data(show_spinner=False)
def load_quality_report(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def money(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def chart_layout(theme: str) -> dict:
    dark = theme == "Dark"
    background = "#1b2b35" if dark else "#ffffff"
    text_color = "#dce6ea" if dark else PALETTE["ink"]
    grid_color = "#344650" if dark else "#e9eef0"
    return {
        "template": "plotly_dark" if dark else "plotly_white",
        "paper_bgcolor": background,
        "plot_bgcolor": background,
        "font": {"color": text_color, "family": "DM Sans"},
        "xaxis": {"gridcolor": grid_color, "zerolinecolor": grid_color},
        "yaxis": {"gridcolor": grid_color, "zerolinecolor": grid_color},
        "margin": {"l": 12, "r": 12, "t": 28, "b": 12},
    }


def render_kpis(items: list[tuple[str, str, str]]) -> None:
    columns = st.columns(len(items))
    for column, (label, value, note) in zip(columns, items):
        column.markdown(
            f'<div class="kpi-card"><div class="kpi-label">{html.escape(label)}</div>'
            f'<div class="kpi-value">{html.escape(value)}</div>'
            f'<div class="kpi-note">{html.escape(note)}</div></div>',
            unsafe_allow_html=True,
        )


def performance_by(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    eligible = realized_sales(frame)
    if eligible.empty:
        return pd.DataFrame(columns=[column, "Revenue", "Profit", "Margin", "Orders"])
    result = (
        eligible.groupby(column, observed=True, as_index=False)
        .agg(Revenue=("Revenue", "sum"), Profit=("Profit", "sum"), Orders=("Order_ID", "nunique"))
    )
    result["Margin"] = np.where(result["Revenue"] > 0, result["Profit"] / result["Revenue"], 0)
    return result.sort_values("Revenue", ascending=False)


def render_command_center(frame: pd.DataFrame, theme: str, start_date, end_date) -> None:
    st.markdown('<div class="eyebrow">NEXUS · executive command center</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-title">A clear view. A confident next move.</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="hero-sub">Commercial performance across the selected portfolio · '
        f'{start_date:%b %d, %Y} — {end_date:%b %d, %Y}</div>',
        unsafe_allow_html=True,
    )

    eligible = realized_sales(frame)
    revenue = float(eligible["Revenue"].sum())
    profit = float(eligible["Profit"].sum())
    orders = int(eligible["Order_ID"].nunique())
    customers = int(eligible["Customer_ID"].nunique())
    margin = profit / revenue if revenue else 0
    aov = revenue / orders if orders else 0
    render_kpis(
        [
            ("NET REVENUE", money(revenue), "Realized sales, net of reversals"),
            ("GROSS PROFIT", money(profit), f"{margin:.1%} realized margin"),
            ("ORDERS", f"{orders:,}", f"{customers:,} purchasing customers"),
            ("AVERAGE ORDER VALUE", f"${aov:,.0f}", "Revenue per realized order"),
        ]
    )

    st.markdown('<div class="section-label">Revenue trajectory</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-note">Monthly revenue and profit. Hover to inspect individual periods.</div>', unsafe_allow_html=True)
    monthly = monthly_revenue(frame)
    monthly_long = monthly.melt(id_vars="Month", var_name="Measure", value_name="Amount")
    trend = px.line(
        monthly_long, x="Month", y="Amount", color="Measure",
        color_discrete_map={"Revenue": PALETTE["teal"], "Profit": PALETTE["blue"]},
    )
    trend.update_traces(line_width=2.4, hovertemplate="%{x|%b %Y}<br>$%{y:,.0f}<extra></extra>")
    trend.update_layout(height=335, hovermode="x unified", legend=dict(orientation="h", y=1.12, x=0), **chart_layout(theme))
    st.plotly_chart(trend, width="stretch", config={"displayModeBar": False})

    category_perf = performance_by(frame, "Category")
    region_perf = performance_by(frame, "Region")
    category_column, region_column = st.columns([1.15, 1])
    with category_column:
        st.markdown('<div class="section-label">Category contribution</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-note">Scale and margin quality by product category.</div>', unsafe_allow_html=True)
        category_perf = category_perf.sort_values("Revenue")
        categories = px.bar(
            category_perf, x="Revenue", y="Category", orientation="h", color="Margin",
            color_continuous_scale=["#c78a27", "#7bb5a5", "#007f6d"],
            hover_data={"Profit": ":$,.0f", "Margin": ":.1%", "Orders": ":,"},
        )
        categories.update_layout(height=330, coloraxis_colorbar_title="Margin", **chart_layout(theme))
        st.plotly_chart(categories, width="stretch", config={"displayModeBar": False})
    with region_column:
        st.markdown('<div class="section-label">Regional performance</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-note">Revenue and profit contribution by market.</div>', unsafe_allow_html=True)
        regions = px.scatter(
            region_perf, x="Revenue", y="Profit", size="Revenue", color="Region",
            color_discrete_sequence=[PALETTE["teal"], PALETTE["blue"], PALETTE["amber"], PALETTE["coral"]],
            hover_name="Region", hover_data={"Revenue": ":$,.0f", "Profit": ":$,.0f", "Margin": ":.1%"},
        )
        regions.update_layout(height=330, **chart_layout(theme))
        st.plotly_chart(regions, width="stretch", config={"displayModeBar": False})

    st.markdown('<div class="section-label">Management signals</div>', unsafe_allow_html=True)
    signal_cols = st.columns([1.15, 0.85])
    products = (
        eligible.groupby(["Product_Name", "Category"], observed=True, as_index=False)
        .agg(Revenue=("Revenue", "sum"), Profit=("Profit", "sum"), Units=("Quantity", "sum"))
        .sort_values("Revenue", ascending=False)
        .head(10)
    )
    with signal_cols[0]:
        st.dataframe(
            products.style.format({"Revenue": "${:,.0f}", "Profit": "${:,.0f}", "Units": "{:,.0f}"}),
            width="stretch",
            hide_index=True,
            column_config={"Product_Name": "Product", "Category": "Category", "Revenue": "Revenue", "Profit": "Profit", "Units": "Units"},
        )
    with signal_cols[1]:
        statuses = frame.groupby("Order_Status", observed=True).size().rename("Orders").reset_index()
        mix = px.pie(statuses, names="Order_Status", values="Orders", hole=0.66)
        mix.update_layout(height=315, legend=dict(orientation="h", y=-0.08), **chart_layout(theme))
        st.plotly_chart(mix, width="stretch", config={"displayModeBar": False})

    if not category_perf.empty:
        leading = category_perf.sort_values("Revenue", ascending=False).iloc[0]
        weakest = category_perf.sort_values("Margin").iloc[0]
        st.markdown(
            f'<div class="insight"><b>Decision brief</b> · {html.escape(str(leading["Category"]))} leads realized revenue at '
            f'{money(float(leading["Revenue"]))}. {html.escape(str(weakest["Category"]))} has the lowest category margin '
            f'({weakest["Margin"]:.1%}); review discount depth and unit economics before expanding promotions.</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-label">Seasonality at a glance</div>', unsafe_allow_html=True)
    heatmap_data = eligible.assign(
        Month=eligible["Order_Date"].dt.month,
        Weekday=pd.Categorical(
            eligible["Order_Date"].dt.day_name(),
            categories=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            ordered=True,
        ),
    ).pivot_table(index="Month", columns="Weekday", values="Revenue", aggfunc="sum", observed=False, fill_value=0)
    fig, axis = plt.subplots(figsize=(12, 3.0))
    dark = theme == "Dark"
    sns.heatmap(
        heatmap_data,
        cmap=sns.light_palette("#34c1a6" if dark else PALETTE["teal"], as_cmap=True),
        linewidths=0.45,
        linecolor="#31434d" if dark else "#f1f4f5",
        cbar_kws={"label": "Revenue ($)", "shrink": 0.8},
        ax=axis,
    )
    axis.set_yticklabels([pd.Timestamp(2000, int(month), 1).strftime("%b") for month in heatmap_data.index])
    axis.set_xlabel("Order weekday", color=PALETTE["muted"])
    axis.set_ylabel("")
    axis.tick_params(axis="both", labelsize=8, colors="#dce6ea" if dark else PALETTE["muted"], length=0)
    fig.patch.set_facecolor("#1b2b35" if dark else "#ffffff")
    axis.set_facecolor("#1b2b35" if dark else "#ffffff")
    fig.tight_layout()
    st.pyplot(fig, width="stretch")
    plt.close(fig)


def render_customer_intelligence(frame: pd.DataFrame, theme: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    st.markdown('<div class="eyebrow">NEXUS · customer intelligence</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-title">Know the value. Protect the relationship.</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-sub">RFM customer value segmentation and acquisition-cohort retention.</div>', unsafe_allow_html=True)
    rfm = build_rfm(frame)
    counts, retention = cohort_retention(frame)
    if rfm.empty:
        st.info("No realized transactions are available in the selected scope for customer analytics.")
        return rfm, counts, retention

    champions = rfm.loc[rfm["Segment"] == "Champions"]
    champion_value_share = float(champions["Monetary"].sum() / rfm["Monetary"].sum()) if rfm["Monetary"].sum() else 0
    repeat_rate = float((rfm["Frequency"] > 1).mean())
    render_kpis(
        [
            ("ACTIVE CUSTOMERS", f"{len(rfm):,}", "Distinct purchasing customers"),
            ("REPEAT CUSTOMER RATE", f"{repeat_rate:.1%}", "More than one realized order"),
            ("CHAMPION VALUE SHARE", f"{champion_value_share:.1%}", "Share of customer revenue"),
            ("MEDIAN CUSTOMER VALUE", money(float(rfm["Monetary"].median())), "Lifetime revenue in scope"),
        ]
    )

    left, right = st.columns([1, 1.15])
    with left:
        segment_summary = (
            rfm.groupby("Segment", observed=True, as_index=False)
            .agg(Customers=("Customer_ID", "nunique"), Revenue=("Monetary", "sum"))
            .sort_values("Revenue")
        )
        chart = px.bar(segment_summary, x="Revenue", y="Segment", orientation="h", color="Revenue", color_continuous_scale=["#a8cfc4", PALETTE["teal"]])
        chart.update_layout(height=350, coloraxis_showscale=False, **chart_layout(theme))
        st.markdown('<div class="section-label">Segment value</div>', unsafe_allow_html=True)
        st.plotly_chart(chart, width="stretch", config={"displayModeBar": False})
    with right:
        st.markdown('<div class="section-label">Cohort retention</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-note">Share of each acquisition-month cohort returning in later months.</div>', unsafe_allow_html=True)
        if not retention.empty:
            matrix = go.Figure(
                go.Heatmap(
                    z=retention.to_numpy(dtype=float),
                    x=[f"Month {int(value)}" for value in retention.columns],
                    y=retention.index.astype(str),
                    zmin=0,
                    zmax=1,
                    colorscale=[[0, "#f2f5f6"], [0.45, "#9acdbd"], [1, "#087d69"]],
                    colorbar={"title": "Retention", "tickformat": ".0%"},
                    texttemplate="%{z:.0%}",
                    hovertemplate="Cohort %{y}<br>%{x}<br>Retention: %{z:.1%}<extra></extra>",
                )
            )
            matrix.update_layout(height=350, **chart_layout(theme))
            st.plotly_chart(matrix, width="stretch", config={"displayModeBar": False})
        else:
            st.info("Cohort history is not available in the selected scope.")

    st.markdown('<div class="section-label">Customer value register</div>', unsafe_allow_html=True)
    st.dataframe(
        rfm[["Customer_ID", "Customer_Name", "Segment", "Recency_Days", "Frequency", "Monetary", "RFM_Score"]]
        .style.format({"Monetary": "${:,.2f}"}),
        width="stretch",
        hide_index=True,
        column_config={
            "Customer_ID": "Customer ID", "Customer_Name": "Customer", "Recency_Days": "Recency (days)",
            "Frequency": "Orders", "Monetary": "Lifetime revenue", "RFM_Score": "RFM score",
        },
    )
    with st.expander("RFM segment definitions"):
        st.markdown(
            "- **Champions:** recent, frequent customers with high lifetime value.\n"
            "- **Loyal customers:** consistently active customers with repeat orders.\n"
            "- **Recent customers:** newly active customers to nurture.\n"
            "- **At risk:** historically frequent customers who have not purchased recently.\n"
            "- **Needs attention / Develop customers:** lower-frequency customers for tailored re-engagement."
        )

    association = discount_association(frame)
    if association["rho"] is not None:
        rho = float(association["rho"])
        p_value = float(association["p_value"])
        interpretation = "negative" if rho < -0.1 else "positive" if rho > 0.1 else "weak"
        st.caption(
            f"Discount–margin rank association: {rho:+.2f} (p={p_value:.3g}, n={association['observations']:,}). "
            f"This is an observational {interpretation} association, not evidence that discounts caused margin changes."
        )
    return rfm, counts, retention


def render_forecast(frame: pd.DataFrame, theme: str, horizon: int) -> ForecastResult:
    st.markdown('<div class="eyebrow">NEXUS · revenue forecast & planning</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-title">Plan from the signal, not the noise.</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-sub">An interpretable seasonal trend baseline for scenario planning, not a financial commitment.</div>', unsafe_allow_html=True)
    result = forecast_revenue(frame, horizon=horizon)
    if result.forecast.empty:
        st.warning("At least 12 complete months of realized revenue history are required for the baseline forecast.")
        history = result.history
        if not history.empty:
            st.line_chart(history.set_index("Month")["Revenue"], width="stretch")
        return result

    forecast_value = float(result.forecast["Forecast_Revenue"].sum())
    recent_actual = float(result.history.tail(min(3, len(result.history)))["Revenue"].mean())
    next_month = float(result.forecast.iloc[0]["Forecast_Revenue"])
    change = next_month / recent_actual - 1 if recent_actual else 0
    render_kpis(
        [
            (f"NEXT {horizon}-MONTH BASELINE", money(forecast_value), "Point forecast total"),
            ("NEXT MONTH", money(next_month), f"{change:+.1%} vs. recent monthly average"),
            (
                "RECENT HOLDOUT MAE",
                money(result.backtest_mae) if result.backtest_mae is not None else "Not available",
                "Last periods held out from fit" if result.backtest_mae is not None else "More history required",
            ),
            ("MODEL", result.model, "Seasonal trend · Ridge regression"),
        ]
    )

    figure = go.Figure()
    figure.add_trace(go.Scatter(x=result.history["Month"], y=result.history["Revenue"], name="Actual revenue", mode="lines", line={"color": PALETTE["teal"], "width": 2.3}))
    figure.add_trace(go.Scatter(x=result.forecast["Month"], y=result.forecast["Forecast_Revenue"], name="Baseline forecast", mode="lines+markers", line={"color": PALETTE["blue"], "width": 2.2, "dash": "dash"}))
    figure.add_trace(
        go.Scatter(
            x=pd.concat([result.forecast["Month"], result.forecast["Month"].iloc[::-1]]),
            y=pd.concat([result.forecast["Upper_95"], result.forecast["Lower_95"].iloc[::-1]]),
            fill="toself",
            fillcolor="rgba(77,120,168,0.14)",
            line={"color": "rgba(77,120,168,0)"},
            hoverinfo="skip",
            name="95% baseline interval",
        )
    )
    figure.update_layout(height=420, hovermode="x unified", **chart_layout(theme))
    figure.update_yaxes(title="Revenue (USD)", tickprefix="$", tickformat="~s")
    figure.update_xaxes(title=None)
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

    st.markdown('<div class="section-label">Forecast schedule</div>', unsafe_allow_html=True)
    st.dataframe(
        result.forecast.style.format({"Forecast_Revenue": "${:,.0f}", "Lower_95": "${:,.0f}", "Upper_95": "${:,.0f}"}),
        width="stretch",
        hide_index=True,
        column_config={"Month": st.column_config.DateColumn("Month", format="MMM YYYY")},
    )
    st.info(
        "Method note: monthly realized revenue is modeled with a linear trend and annual seasonal terms. "
        "The interval is a residual-based planning band; it does not capture structural breaks, promotions, "
        "stock constraints or external events. Validate against business plans before use."
    )
    return result


def render_data_reporting(
    frame: pd.DataFrame,
    all_sales: pd.DataFrame,
    rfm: pd.DataFrame,
    counts: pd.DataFrame,
    retention: pd.DataFrame,
    forecast: ForecastResult,
    quality_report: dict,
    theme: str,
    scope_signature: str,
) -> None:
    st.markdown('<div class="eyebrow">NEXUS · data assurance & reporting</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-title">Trusted inputs. Decision-ready outputs.</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-sub">Review quality controls, inspect the current scope and produce a management pack.</div>', unsafe_allow_html=True)

    if not quality_report:
        quality_report = {
            "clean_rows": len(all_sales),
            "missing_values_after": {str(column): int(value) for column, value in all_sales.isna().sum().items() if value},
        }
    missing_count = sum(quality_report.get("missing_values_after", {}).values())
    violations = sum(quality_report.get("business_rule_violations_after", {}).values())
    render_kpis(
        [
            ("SOURCE ROWS", f"{len(all_sales):,}", "Loaded transaction records"),
            ("FILTERED ROWS", f"{len(frame):,}", "Current analytical scope"),
            ("QUALITY EXCEPTIONS", f"{missing_count + violations:,}", "Post-clean missing values and rule violations"),
            ("IQR OUTLIERS FLAGGED", f"{sum(quality_report.get('iqr_outlier_counts', {}).values()):,}", "Flagged for review; not auto-dropped"),
        ]
    )
    quality_frame = pd.DataFrame(
        [
            {
                "Control": key.replace("_", " ").title(),
                "Result": json.dumps(value, default=str) if isinstance(value, (dict, list)) else str(value),
            }
            for key, value in quality_report.items()
        ]
    )
    st.markdown('<div class="section-label">Quality control register</div>', unsafe_allow_html=True)
    st.dataframe(quality_frame, width="stretch", hide_index=True)

    with st.expander("Preview current data scope"):
        st.dataframe(frame.head(100), width="stretch", hide_index=True)

    st.markdown('<div class="section-label">Management reporting</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-note">Exports use the active date, region, category and order-status filters.</div>', unsafe_allow_html=True)
    export_col, report_col = st.columns(2)
    with export_col:
        if st.button("Prepare Excel management pack", type="primary", key="prepare_excel"):
            st.session_state["nexus_excel"] = {
                "signature": scope_signature,
                "data": build_excel_report(frame, rfm, counts, retention, forecast, quality_report),
            }
        excel_export = st.session_state.get("nexus_excel")
        if excel_export and excel_export["signature"] == scope_signature:
            st.download_button(
                "Download Excel workbook",
                data=excel_export["data"],
                file_name="nexus_sales_management_pack.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_excel",
            )
    with report_col:
        if st.button("Prepare PDF business brief", key="prepare_pdf"):
            period_label = f"{frame['Order_Date'].min():%b %Y} — {frame['Order_Date'].max():%b %Y}"
            st.session_state["nexus_pdf"] = {
                "signature": scope_signature,
                "data": build_pdf_report(frame, rfm, retention, forecast, quality_report, period_label),
            }
        pdf_export = st.session_state.get("nexus_pdf")
        if pdf_export and pdf_export["signature"] == scope_signature:
            st.download_button(
                "Download PDF business brief",
                data=pdf_export["data"],
                file_name="nexus_executive_business_brief.pdf",
                mime="application/pdf",
                key="download_pdf",
            )

    st.download_button(
        "Download filtered transaction CSV",
        data=frame.to_csv(index=False, date_format="%Y-%m-%d"),
        file_name="nexus_filtered_sales.csv",
        mime="text/csv",
        key="download_filtered_csv",
    )

    st.markdown('<div class="section-label">Power BI handoff</div>', unsafe_allow_html=True)
    st.markdown(
        "Connect Power BI to the MySQL star schema or import the cleaned CSV. Relate the date, customer, "
        "product and geography dimensions to the transaction fact table (one-to-many, single direction). "
        "Starter DAX measures are in `powerbi/measures.dax`; mark the date dimension as the model date table."
    )


apply_theme("Light")
st.sidebar.markdown('<div class="nexus-brand"><span>N</span>EXUS</div>', unsafe_allow_html=True)
st.sidebar.markdown('<div class="nexus-sub">ENTERPRISE SALES INTELLIGENCE</div>', unsafe_allow_html=True)
theme = st.sidebar.selectbox("Appearance", ["Light", "Dark"], index=0)
if theme == "Dark":
    apply_theme(theme)

mysql_available = bool(os.environ.get("SALES_DATABASE_URL"))
if mysql_available:
    source = st.sidebar.radio("Data source", ["Cleaned CSV", "MySQL"], horizontal=True)
else:
    source = "Cleaned CSV"
    st.sidebar.caption("Data source · cleaned CSV")

page = st.sidebar.radio(
    "Workspace",
    ["Executive Command Center", "Customer Intelligence", "Forecast & Planning", "Data & Reporting"],
    label_visibility="collapsed",
)
st.sidebar.markdown("---")
st.sidebar.markdown("#### Portfolio filters")

if source == "MySQL":
    try:
        sales = load_mysql_data()
    except SQLAlchemyError:
        LOGGER.exception("NEXUS could not load data from MySQL.")
        st.error("MySQL data could not be loaded. Check SALES_DATABASE_URL, connectivity, and schema.sql; technical details are in the server logs.")
        st.stop()
else:
    if not DATA_FILE.exists():
        st.error("Cleaned sales data is missing. Run `python scripts/generate_data.py` and `python scripts/clean_data.py` first.")
        st.stop()
    sales = load_csv_data(DATA_FILE)

date_min = sales["Order_Date"].min().date()
date_max = sales["Order_Date"].max().date()
selected_dates = st.sidebar.date_input(
    "Order date range",
    value=(date_min, date_max),
    min_value=date_min,
    max_value=date_max,
)
region_options = sorted(sales["Region"].dropna().astype(str).unique())
category_options = sorted(sales["Category"].dropna().astype(str).unique())
selected_regions = st.sidebar.multiselect("Region", region_options, default=region_options)
selected_categories = st.sidebar.multiselect("Product category", category_options, default=category_options)
include_reversed = st.sidebar.toggle("Include cancelled & returned", value=False)
horizon = st.sidebar.select_slider("Forecast horizon", options=[3, 6, 9, 12], value=6)

if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
    start_date, end_date = selected_dates
else:
    start_date = end_date = selected_dates

in_scope = (
    sales["Order_Date"].dt.date.between(start_date, end_date)
    & sales["Region"].astype(str).isin(selected_regions)
    & sales["Category"].astype(str).isin(selected_categories)
)
filtered = sales.loc[in_scope].copy()
if not include_reversed:
    filtered = filtered.loc[~filtered["Order_Status"].isin(["Cancelled", "Returned"])]

st.sidebar.markdown("---")
st.sidebar.caption(f"{len(filtered):,} records in current scope")
st.sidebar.caption("Synthetic demonstration data · Not company results")
if st.sidebar.button("Refresh cached data"):
    st.cache_data.clear()
    st.rerun()

if filtered.empty:
    st.warning("No transactions match these filters. Expand the date range or select more regions/categories.")
    st.stop()

quality_report = load_quality_report(QUALITY_FILE) if source == "Cleaned CSV" else {}
signature = repr(
    (
        source,
        start_date,
        end_date,
        tuple(selected_regions),
        tuple(selected_categories),
        include_reversed,
        horizon,
        len(filtered),
    )
)

if page == "Executive Command Center":
    render_command_center(filtered, theme, start_date, end_date)
elif page == "Customer Intelligence":
    render_customer_intelligence(filtered, theme)
elif page == "Forecast & Planning":
    render_forecast(filtered, theme, horizon)
else:
    rfm = build_rfm(filtered)
    cohort_counts, retention = cohort_retention(filtered)
    forecast_result = forecast_revenue(filtered, horizon=horizon)
    render_data_reporting(
        filtered,
        sales,
        rfm,
        cohort_counts,
        retention,
        forecast_result,
        quality_report,
        theme,
        signature,
    )

st.markdown(
    '<div class="footer">NEXUS · ENTERPRISE SALES INTELLIGENCE &amp; STRATEGIC ANALYTICS · '
    f'{len(filtered):,} scoped records · Source: {html.escape(source)}</div>',
    unsafe_allow_html=True,
)
