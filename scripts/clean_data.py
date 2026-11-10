"""Profile, clean, validate and export the retail sales dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "raw" / "sales_raw.csv"
DEFAULT_OUTPUT = ROOT / "data" / "processed"
REQUIRED_COLUMNS = [
    "Order_ID", "Order_Date", "Customer_ID", "Customer_Name", "Gender", "Age",
    "Product_ID", "Product_Name", "Category", "Sub_Category", "Region", "State",
    "City", "Quantity", "Unit_Price", "Discount", "Revenue", "Cost", "Profit",
    "Payment_Method", "Order_Status", "Shipping_Days",
]


def clean_sales(data: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(data.columns))
    if missing_columns:
        raise ValueError(f"Input is missing required columns: {', '.join(missing_columns)}")

    work = data[REQUIRED_COLUMNS].copy()
    report: dict = {
        "source_rows": int(len(work)),
        "missing_values_before": {str(k): int(v) for k, v in work.isna().sum().items() if v},
        "duplicates_removed": int(work.duplicated().sum()),
    }
    work = work.drop_duplicates().reset_index(drop=True)

    work["Order_Date"] = pd.to_datetime(work["Order_Date"], errors="coerce")
    for column in ["Age", "Quantity", "Shipping_Days"]:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    for column in ["Unit_Price", "Discount", "Revenue", "Cost", "Profit"]:
        work[column] = pd.to_numeric(work[column], errors="coerce")

    text_columns = [
        "Order_ID", "Customer_ID", "Customer_Name", "Gender", "Product_ID",
        "Product_Name", "Category", "Sub_Category", "Region", "State", "City",
        "Payment_Method", "Order_Status",
    ]
    for column in text_columns:
        work[column] = work[column].astype("string").str.strip()

    normalizations = {
        "Gender": {"female": "Female", "male": "Male", "non-binary": "Non-binary"},
        "Payment_Method": {
            "credit card": "Credit Card", "debit card": "Debit Card",
            "paypal": "PayPal", "digital wallet": "Digital Wallet",
            "bank transfer": "Bank Transfer",
        },
        "Order_Status": {
            "delivered": "Delivered", "shipped": "Shipped", "processing": "Processing",
            "cancelled": "Cancelled", "returned": "Returned",
        },
        "Region": {
            "northeast": "Northeast", "south": "South", "midwest": "Midwest", "west": "West",
        },
    }
    for column, mapping in normalizations.items():
        work[column] = work[column].str.lower().map(mapping).fillna(work[column])

    work["Age"] = work["Age"].fillna(work["Age"].median()).round().clip(18, 100).astype("int16")
    work["Quantity"] = work["Quantity"].fillna(1).round().clip(1, 100).astype("int16")
    work["Shipping_Days"] = work["Shipping_Days"].fillna(0).round().clip(0, 60).astype("int16")
    for column in ["Unit_Price", "Discount", "Revenue", "Cost", "Profit"]:
        work[column] = work[column].fillna(work[column].median()).astype("float64")
    work["Unit_Price"] = work["Unit_Price"].clip(lower=0.01)
    work["Discount"] = work["Discount"].clip(0, 0.8)
    work["Cost"] = work["Cost"].clip(lower=0)

    categorical = ["Gender", "Category", "Sub_Category", "Region", "State", "City", "Payment_Method", "Order_Status"]
    for column in categorical:
        mode = work[column].mode(dropna=True)
        work[column] = work[column].fillna(mode.iloc[0] if not mode.empty else "Unknown")
    for column in ["Customer_ID", "Customer_Name", "Product_ID", "Product_Name", "Order_ID"]:
        work[column] = work[column].fillna("Unknown")

    invalid_dates = int(work["Order_Date"].isna().sum())
    if invalid_dates:
        work = work.loc[work["Order_Date"].notna()].copy()

    # Flag extreme monetary observations for audit without deleting legitimate high-value orders.
    outlier_counts = {}
    for column in ["Revenue", "Cost", "Profit", "Unit_Price"]:
        q1, q3 = work[column].quantile([0.25, 0.75])
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outlier_counts[column] = int(((work[column] < lower) | (work[column] > upper)).sum())

    # Recalculate measures from business inputs to enforce coherent revenue/profit values.
    reversed_mask = work["Order_Status"].isin(["Cancelled", "Returned"])
    calculated_revenue = (work["Quantity"] * work["Unit_Price"] * (1 - work["Discount"])).round(2)
    work["Revenue"] = np.where(reversed_mask, 0.0, calculated_revenue)
    calculated_cost = (work["Quantity"] * (work["Cost"] / work["Quantity"].replace(0, 1))).round(2)
    work["Cost"] = calculated_cost
    work["Profit"] = np.where(reversed_mask, -work["Cost"], work["Revenue"] - work["Cost"]).round(2)
    work["Discount"] = work["Discount"].round(4)
    work["Shipping_Days"] = np.where(work["Order_Status"] == "Cancelled", 0, work["Shipping_Days"])

    work["Gross_Margin_Pct"] = np.where(work["Revenue"] > 0, work["Profit"] / work["Revenue"], 0).round(4)
    work["Order_Year"] = work["Order_Date"].dt.year.astype("int16")
    work["Order_Month"] = work["Order_Date"].dt.month.astype("int8")
    work["Order_Quarter"] = work["Order_Date"].dt.quarter.astype("int8")
    work["Is_Weekend"] = work["Order_Date"].dt.dayofweek.ge(5)

    profit_mismatch = np.where(
        reversed_mask,
        ~np.isclose(work["Profit"], -work["Cost"], atol=0.01),
        ~np.isclose(work["Profit"], work["Revenue"] - work["Cost"], atol=0.01),
    )
    rule_violations = {
        "negative_quantity": int((work["Quantity"] <= 0).sum()),
        "negative_unit_price": int((work["Unit_Price"] < 0).sum()),
        "discount_out_of_range": int((~work["Discount"].between(0, 0.8)).sum()),
        "profit_reconciliation": int(profit_mismatch.sum()),
    }
    report.update(
        {
            "clean_rows": int(len(work)),
            "invalid_dates_removed": invalid_dates,
            "missing_values_after": {str(k): int(v) for k, v in work.isna().sum().items() if v},
            "iqr_outlier_counts": outlier_counts,
            "business_rule_violations_after": rule_violations,
            "revenue_total": round(float(work["Revenue"].sum()), 2),
            "profit_total": round(float(work["Profit"].sum()), 2),
        }
    )
    return work.reset_index(drop=True), report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Raw input CSV.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="CSV, Excel and JSON output directory.")
    args = parser.parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Input file not found: {args.input}. Run scripts/generate_data.py first.")
    raw = pd.read_csv(args.input)
    cleaned, report = clean_sales(raw)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(args.output_dir / "sales_cleaned.csv", index=False, date_format="%Y-%m-%d")
    with pd.ExcelWriter(args.output_dir / "sales_cleaned.xlsx", engine="openpyxl") as writer:
        cleaned.to_excel(writer, sheet_name="Sales", index=False)
        pd.DataFrame(
            [{"Metric": key, "Value": json.dumps(value) if isinstance(value, (dict, list)) else value}
             for key, value in report.items()]
        ).to_excel(writer, sheet_name="Quality Report", index=False)
    (args.output_dir / "quality_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Cleaned {len(raw):,} rows to {len(cleaned):,}; exports saved in {args.output_dir}")


if __name__ == "__main__":
    main()
