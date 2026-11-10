"""Management-ready Excel and PDF reporting from dashboard-filtered data."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from analytics import ForecastResult, realized_sales


INK = "#142b3b"
TEAL = "#008b76"
BLUE = "#4d78a8"
MUTED = "#718393"


def _summary(frame: pd.DataFrame) -> pd.DataFrame:
    eligible = realized_sales(frame)
    revenue = float(eligible["Revenue"].sum())
    profit = float(eligible["Profit"].sum())
    return pd.DataFrame(
        [
            ("Net revenue", revenue),
            ("Gross profit", profit),
            ("Profit margin", profit / revenue if revenue else 0.0),
            ("Orders", int(eligible["Order_ID"].nunique())),
            ("Units sold", int(eligible["Quantity"].sum())),
            ("Customers", int(eligible["Customer_ID"].nunique())),
        ],
        columns=["Metric", "Value"],
    )


def _grouped_performance(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    eligible = realized_sales(frame)
    result = (
        eligible.groupby(column, observed=True, as_index=False)
        .agg(
            Revenue=("Revenue", "sum"),
            Profit=("Profit", "sum"),
            Orders=("Order_ID", "nunique"),
        )
    )
    result["Margin"] = np.where(result["Revenue"] > 0, result["Profit"] / result["Revenue"], 0)
    return result.sort_values("Revenue", ascending=False)


def build_excel_report(
    frame: pd.DataFrame,
    rfm: pd.DataFrame,
    cohort_counts: pd.DataFrame,
    cohort_retention: pd.DataFrame,
    forecast: ForecastResult,
    quality_report: dict[str, Any],
) -> bytes:
    """Create an in-memory workbook containing executive, customer and forecast views."""
    buffer = BytesIO()
    quality_rows = [
        {
            "Metric": key,
            "Value": json.dumps(value, default=str) if isinstance(value, (dict, list)) else value,
        }
        for key, value in quality_report.items()
    ]
    monthly = (
        realized_sales(frame)
        .assign(Month=lambda data: data["Order_Date"].dt.to_period("M").astype(str))
        .groupby("Month", observed=True, as_index=False)
        .agg(Revenue=("Revenue", "sum"), Profit=("Profit", "sum"))
    )
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _summary(frame).to_excel(writer, sheet_name="Executive Summary", index=False)
        monthly.to_excel(writer, sheet_name="Monthly Trend", index=False)
        _grouped_performance(frame, "Category").to_excel(writer, sheet_name="Category Performance", index=False)
        _grouped_performance(frame, "Region").to_excel(writer, sheet_name="Regional Performance", index=False)
        rfm.to_excel(writer, sheet_name="Customer RFM", index=False)
        cohort_counts.to_excel(writer, sheet_name="Cohort Counts")
        cohort_retention.to_excel(writer, sheet_name="Cohort Retention")
        forecast.forecast.to_excel(writer, sheet_name="Revenue Forecast", index=False)
        pd.DataFrame(quality_rows).to_excel(writer, sheet_name="Data Quality", index=False)

        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            if worksheet.max_row > 1 and worksheet.max_column > 0:
                worksheet.auto_filter.ref = worksheet.dimensions
            for column_cells in worksheet.columns:
                width = min(max(max(len(str(cell.value or "")) for cell in column_cells) + 2, 12), 34)
                worksheet.column_dimensions[column_cells[0].column_letter].width = width
    return buffer.getvalue()


def build_pdf_report(
    frame: pd.DataFrame,
    rfm: pd.DataFrame,
    cohort_retention: pd.DataFrame,
    forecast: ForecastResult,
    quality_report: dict[str, Any],
    period_label: str,
) -> bytes:
    """Create a concise executive review with business signals and supporting charts."""
    buffer = BytesIO()
    eligible = realized_sales(frame)
    summary = _summary(frame).set_index("Metric")["Value"]
    category_perf = _grouped_performance(frame, "Category")
    region_perf = _grouped_performance(frame, "Region")
    monthly = (
        eligible.assign(Month=eligible["Order_Date"].dt.to_period("M").dt.to_timestamp())
        .groupby("Month", observed=True)[["Revenue", "Profit"]]
        .sum()
        .reset_index()
    )

    top_category = category_perf.iloc[0] if not category_perf.empty else None
    lowest_margin = (
        category_perf.loc[category_perf["Revenue"] > 0].sort_values("Margin").iloc[0]
        if not category_perf.empty
        else None
    )
    champion_share = 0.0
    if not rfm.empty and rfm["Monetary"].sum() > 0:
        champion_share = float(rfm.loc[rfm["Segment"] == "Champions", "Monetary"].sum() / rfm["Monetary"].sum())

    with PdfPages(buffer) as pdf:
        fig = plt.figure(figsize=(11.7, 8.3), facecolor="white")
        fig.text(0.07, 0.92, "NEXUS  /  ENTERPRISE SALES INTELLIGENCE", color=TEAL, fontsize=10, weight="bold")
        fig.text(0.07, 0.86, "Executive performance review", color=INK, fontsize=24, weight="bold")
        fig.text(0.07, 0.82, period_label, color=MUTED, fontsize=10)
        fig.text(0.07, 0.75, "PERFORMANCE SNAPSHOT", color=MUTED, fontsize=9, weight="bold")

        metric_cards = [
            ("NET REVENUE", f"${summary['Net revenue']:,.0f}"),
            ("GROSS PROFIT", f"${summary['Gross profit']:,.0f}"),
            ("PROFIT MARGIN", f"{summary['Profit margin']:.1%}"),
            ("ORDERS", f"{int(summary['Orders']):,}"),
        ]
        for index, (label, value) in enumerate(metric_cards):
            x = 0.07 + index * 0.225
            fig.patches.append(
                plt.Rectangle((x, 0.61), 0.205, 0.105, transform=fig.transFigure, color="#f4f7f8", zorder=0)
            )
            fig.text(x + 0.014, 0.68, label, fontsize=8, color=MUTED, weight="bold")
            fig.text(x + 0.014, 0.635, value, fontsize=17, color=INK, weight="bold")

        fig.text(0.07, 0.55, "Management readout", fontsize=13, color=INK, weight="bold")
        recommendations: list[str] = []
        if top_category is not None:
            recommendations.append(
                f"{top_category['Category']} is the largest revenue category at ${top_category['Revenue']:,.0f}. "
                "Protect availability on leading products and monitor concentration."
            )
        if lowest_margin is not None:
            recommendations.append(
                f"{lowest_margin['Category']} has the lowest category margin at {lowest_margin['Margin']:.1%}. "
                "Review product mix, fulfillment cost and discount depth before scaling promotions."
            )
        recommendations.append(
            f"Champions account for {champion_share:.1%} of customer monetary value. "
            "Prioritize retention and cross-sell experiments for this segment."
        )
        if forecast.backtest_mae is not None:
            recommendations.append(
                f"The seasonal baseline's recent holdout MAE is ${forecast.backtest_mae:,.0f} per month. "
                "Treat the forecast as a planning reference, not a commitment."
            )
        for index, text in enumerate(recommendations):
            fig.text(0.08, 0.49 - index * 0.075, f"{index + 1:02d}", color=TEAL, fontsize=10, weight="bold")
            fig.text(0.12, 0.49 - index * 0.075, text, color=INK, fontsize=9, wrap=True, va="top")

        fig.text(
            0.07,
            0.11,
            f"Source: synthetic retail transactions · {len(eligible):,} realized records · "
            f"{quality_report.get('clean_rows', len(frame)):,} cleaned source rows",
            fontsize=8,
            color=MUTED,
        )
        fig.text(0.07, 0.075, "Analytical findings are descriptive; observed associations are not causal evidence.", fontsize=8, color=MUTED)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig, axes = plt.subplots(2, 1, figsize=(11.7, 8.3), facecolor="white")
        axes[0].plot(monthly["Month"], monthly["Revenue"], color=TEAL, linewidth=2.2, label="Revenue")
        axes[0].plot(monthly["Month"], monthly["Profit"], color=BLUE, linewidth=1.8, label="Profit")
        if not forecast.forecast.empty:
            dates = forecast.forecast["Month"]
            axes[0].plot(dates, forecast.forecast["Forecast_Revenue"], color=INK, linestyle="--", label="Forecast")
            axes[0].fill_between(
                dates,
                forecast.forecast["Lower_95"],
                forecast.forecast["Upper_95"],
                color=INK,
                alpha=0.1,
                label="95% baseline interval",
            )
        axes[0].set_title("Revenue trajectory and planning baseline", loc="left", color=INK, weight="bold", pad=12)
        axes[0].set_ylabel("USD")
        axes[0].grid(axis="y", color="#e9eef0")
        axes[0].legend(frameon=False, ncol=4, fontsize=8)
        axes[0].spines[["top", "right", "left"]].set_visible(False)

        if not category_perf.empty:
            plot_categories = category_perf.sort_values("Revenue")
            axes[1].barh(plot_categories["Category"].astype(str), plot_categories["Revenue"], color=TEAL)
        axes[1].set_title("Category revenue contribution", loc="left", color=INK, weight="bold", pad=12)
        axes[1].set_xlabel("Revenue (USD)")
        axes[1].grid(axis="x", color="#e9eef0")
        axes[1].set_axisbelow(True)
        axes[1].spines[["top", "right", "left"]].set_visible(False)
        fig.tight_layout(pad=2.2)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig, axes = plt.subplots(1, 2, figsize=(11.7, 8.3), facecolor="white")
        segment_summary = (
            rfm.groupby("Segment", observed=True)["Customer_ID"].nunique().sort_values(ascending=True)
            if not rfm.empty
            else pd.Series(dtype=float)
        )
        if not segment_summary.empty:
            axes[0].barh(segment_summary.index.astype(str), segment_summary.values, color=BLUE)
        axes[0].set_title("Customer segments", loc="left", color=INK, weight="bold", pad=12)
        axes[0].set_xlabel("Customers")
        axes[0].grid(axis="x", color="#e9eef0")
        axes[0].set_axisbelow(True)
        axes[0].spines[["top", "right", "left"]].set_visible(False)

        if not cohort_retention.empty:
            retention_values = cohort_retention.to_numpy(dtype=float)
            image = axes[1].imshow(retention_values, aspect="auto", cmap="Greens", vmin=0, vmax=1)
            axes[1].set_yticks(range(len(cohort_retention.index)))
            axes[1].set_yticklabels(cohort_retention.index.astype(str), fontsize=7)
            axes[1].set_xticks(range(len(cohort_retention.columns)))
            axes[1].set_xticklabels([f"M{int(month)}" for month in cohort_retention.columns], fontsize=7)
            fig.colorbar(image, ax=axes[1], fraction=0.045, pad=0.04, label="Retention")
        axes[1].set_title("Cohort retention", loc="left", color=INK, weight="bold", pad=12)
        fig.suptitle("Customer value and loyalty", x=0.07, y=0.97, ha="left", color=INK, fontsize=14, weight="bold")
        fig.tight_layout(rect=(0, 0, 1, 0.94), pad=2)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

    return buffer.getvalue()
