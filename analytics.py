"""Reusable customer and sales analytics for the NEXUS dashboard."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, t
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


EXCLUDED_STATUSES = {"Cancelled", "Returned"}


@dataclass(frozen=True)
class ForecastResult:
    history: pd.DataFrame
    forecast: pd.DataFrame
    backtest_mae: float | None
    model: str


def realized_sales(frame: pd.DataFrame) -> pd.DataFrame:
    """Return rows that represent realized commercial activity."""
    return frame.loc[~frame["Order_Status"].isin(EXCLUDED_STATUSES)].copy()


def monthly_revenue(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate realized revenue and profit by calendar month, retaining empty months."""
    eligible = realized_sales(frame)
    if eligible.empty:
        return pd.DataFrame(columns=["Month", "Revenue", "Profit"])

    values = eligible.assign(Month=eligible["Order_Date"].dt.to_period("M"))
    monthly = values.groupby("Month", observed=True)[["Revenue", "Profit"]].sum()
    full_months = pd.period_range(monthly.index.min(), monthly.index.max(), freq="M")
    monthly = monthly.reindex(full_months, fill_value=0).rename_axis("Month").reset_index()
    monthly["Month"] = monthly["Month"].dt.to_timestamp()
    return monthly


def _quintile_score(values: pd.Series, *, reverse: bool = False) -> pd.Series:
    score = np.ceil(values.rank(method="first", pct=True) * 5).clip(1, 5).astype("int8")
    return 6 - score if reverse else score


def build_rfm(frame: pd.DataFrame) -> pd.DataFrame:
    """Build recency/frequency/monetary scores and transparent action segments."""
    eligible = realized_sales(frame)
    columns = [
        "Customer_ID", "Customer_Name", "Gender", "Age", "Last_Order",
        "Recency_Days", "Frequency", "Monetary", "R_Score", "F_Score",
        "M_Score", "RFM_Score", "Segment",
    ]
    if eligible.empty:
        return pd.DataFrame(columns=columns)

    rfm = (
        eligible.groupby("Customer_ID", observed=True, as_index=False)
        .agg(
            Customer_Name=("Customer_Name", "first"),
            Gender=("Gender", "first"),
            Age=("Age", "first"),
            Last_Order=("Order_Date", "max"),
            Frequency=("Order_ID", "nunique"),
            Monetary=("Revenue", "sum"),
        )
    )
    as_of = eligible["Order_Date"].max().normalize() + pd.Timedelta(days=1)
    rfm["Recency_Days"] = (as_of - rfm["Last_Order"].dt.normalize()).dt.days
    rfm["R_Score"] = _quintile_score(rfm["Recency_Days"], reverse=True)
    rfm["F_Score"] = _quintile_score(rfm["Frequency"])
    rfm["M_Score"] = _quintile_score(rfm["Monetary"])
    rfm["RFM_Score"] = rfm[["R_Score", "F_Score", "M_Score"]].astype(str).agg("".join, axis=1)

    recent = rfm["R_Score"] >= 4
    frequent = rfm["F_Score"] >= 4
    valuable = rfm["M_Score"] >= 4
    rfm["Segment"] = np.select(
        [
            recent & frequent & valuable,
            (rfm["R_Score"] >= 3) & (rfm["F_Score"] >= 3),
            recent & (rfm["F_Score"] <= 2),
            (rfm["R_Score"] <= 2) & (rfm["F_Score"] >= 3),
            (rfm["R_Score"] <= 2) & (rfm["F_Score"] <= 2),
        ],
        ["Champions", "Loyal customers", "Recent customers", "At risk", "Needs attention"],
        default="Develop customers",
    )
    return rfm[columns].sort_values(["Monetary", "Frequency"], ascending=False).reset_index(drop=True)


def cohort_retention(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return cohort customer counts and month-over-month retention percentages."""
    eligible = realized_sales(frame)
    if eligible.empty:
        empty = pd.DataFrame()
        return empty, empty

    activity = eligible[["Customer_ID", "Order_Date"]].copy()
    activity["Activity_Month"] = activity["Order_Date"].dt.to_period("M")
    first_month = activity.groupby("Customer_ID", observed=True)["Activity_Month"].min()
    activity["Cohort_Month"] = activity["Customer_ID"].map(first_month)
    activity["Cohort_Index"] = (
        (activity["Activity_Month"].dt.year - activity["Cohort_Month"].dt.year) * 12
        + activity["Activity_Month"].dt.month
        - activity["Cohort_Month"].dt.month
        + 1
    )

    counts = activity.groupby(
        ["Cohort_Month", "Cohort_Index"], observed=True
    )["Customer_ID"].nunique().unstack(fill_value=0)
    counts.index = counts.index.astype(str)
    retention = counts.div(counts.get(1, pd.Series(index=counts.index, dtype=float)), axis=0)
    return counts, retention


def _forecast_features(periods: pd.PeriodIndex, origin: pd.Period) -> np.ndarray:
    step = (periods.year - origin.year) * 12 + periods.month - origin.month
    angle = 2 * np.pi * (periods.month - 1) / 12
    return np.column_stack(
        [
            step.astype(float),
            np.sin(angle),
            np.cos(angle),
            np.sin(2 * angle),
            np.cos(2 * angle),
        ]
    )


def forecast_revenue(frame: pd.DataFrame, horizon: int = 6) -> ForecastResult:
    """Fit a seasonal trend baseline and return a holdout error and uncertainty band."""
    if horizon < 1:
        raise ValueError("horizon must be a positive integer.")
    history = monthly_revenue(frame)
    if len(history) < 12:
        return ForecastResult(history, pd.DataFrame(), None, "Insufficient history")

    periods = pd.PeriodIndex(history["Month"], freq="M")
    origin = periods.min()
    features = _forecast_features(periods, origin)
    target = history["Revenue"].to_numpy(dtype=float)

    backtest_mae: float | None = None
    if len(history) >= 15:
        holdout = min(3, max(1, len(history) // 6))
        train_x, test_x = features[:-holdout], features[-holdout:]
        train_y, test_y = target[:-holdout], target[-holdout:]
        backtest_model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        backtest_model.fit(train_x, train_y)
        backtest_mae = float(mean_absolute_error(test_y, backtest_model.predict(test_x)))

    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    model.fit(features, target)
    fitted = model.predict(features)
    residual_std = float(np.sqrt(np.mean(np.square(target - fitted))))

    future_periods = pd.period_range(periods.max() + 1, periods.max() + horizon, freq="M")
    future_features = _forecast_features(future_periods, origin)
    predicted = np.maximum(0, model.predict(future_features))
    critical_value = float(t.ppf(0.975, df=max(len(history) - features.shape[1], 1)))
    horizon_scale = np.sqrt(1 + np.arange(1, horizon + 1) / len(history))
    margin = critical_value * residual_std * horizon_scale

    forecast = pd.DataFrame(
        {
            "Month": future_periods.to_timestamp(),
            "Forecast_Revenue": predicted,
            "Lower_95": np.maximum(0, predicted - margin),
            "Upper_95": predicted + margin,
        }
    )
    return ForecastResult(history, forecast, backtest_mae, "Seasonal Ridge baseline")


def discount_association(frame: pd.DataFrame) -> dict[str, float | int | None]:
    """Measure rank association between discount depth and realized order margin."""
    eligible = realized_sales(frame)
    eligible = eligible.loc[eligible["Revenue"] > 0].copy()
    if len(eligible) < 3 or eligible["Discount"].nunique() < 2:
        return {"observations": len(eligible), "rho": None, "p_value": None}

    eligible["Order_Margin"] = eligible["Profit"] / eligible["Revenue"]
    result = spearmanr(eligible["Discount"], eligible["Order_Margin"], nan_policy="omit")
    rho = float(result.statistic)
    p_value = float(result.pvalue)
    if not np.isfinite(rho) or not np.isfinite(p_value):
        return {"observations": len(eligible), "rho": None, "p_value": None}
    return {"observations": len(eligible), "rho": rho, "p_value": p_value}
