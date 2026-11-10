from __future__ import annotations

import unittest
from io import BytesIO
from zipfile import ZipFile

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from analytics import build_rfm, cohort_retention, discount_association, forecast_revenue, monthly_revenue
from reporting import build_excel_report, build_pdf_report


def sample_sales() -> pd.DataFrame:
    rows = []
    for customer, months in {"C1": [1, 2, 4], "C2": [1], "C3": [2, 4]}.items():
        for order, month in enumerate(months, start=1):
            date = pd.Timestamp(2024, month, 5)
            revenue = 100.0 + month * 15 + order
            discount = 0.05 * order
            profit = revenue * (0.5 - discount)
            rows.append(
                {
                    "Order_ID": f"{customer}-{order}",
                    "Order_Date": date,
                    "Customer_ID": customer,
                    "Customer_Name": f"Customer {customer}",
                    "Gender": "Female",
                    "Age": 35,
                    "Category": "Electronics",
                    "Region": "West",
                    "Quantity": 1,
                    "Unit_Price": revenue,
                    "Discount": discount,
                    "Revenue": revenue,
                    "Cost": revenue - profit,
                    "Profit": profit,
                    "Order_Status": "Delivered",
                }
            )
    rows.append(
        {
            **rows[0],
            "Order_ID": "C4-cancelled",
            "Customer_ID": "C4",
            "Order_Status": "Cancelled",
            "Revenue": 0.0,
            "Profit": -60.0,
        }
    )
    return pd.DataFrame(rows)


class AnalyticsTests(unittest.TestCase):
    def test_monthly_revenue_fills_missing_calendar_months(self) -> None:
        result = monthly_revenue(sample_sales())
        self.assertEqual(len(result), 4)
        self.assertEqual(result.loc[2, "Revenue"], 0)
        self.assertEqual(result["Month"].iloc[0], pd.Timestamp("2024-01-01"))

    def test_rfm_excludes_reversed_orders_and_assigns_segments(self) -> None:
        result = build_rfm(sample_sales())
        self.assertNotIn("C4", result["Customer_ID"].tolist())
        self.assertEqual(result.set_index("Customer_ID").loc["C1", "Frequency"], 3)
        self.assertTrue(result["Segment"].notna().all())
        self.assertTrue(result["RFM_Score"].str.len().eq(3).all())

    def test_cohort_retention_is_bounded_and_uses_first_order_month(self) -> None:
        counts, retention = cohort_retention(sample_sales())
        self.assertEqual(counts.loc["2024-01", 1], 2)
        self.assertEqual(counts.loc["2024-01", 2], 1)
        self.assertEqual(retention.loc["2024-01", 1], 1.0)
        self.assertAlmostEqual(retention.loc["2024-01", 2], 0.5)
        self.assertTrue(((retention >= 0) & (retention <= 1)).all().all())

    def test_forecast_returns_nonnegative_horizon_and_holdout_error(self) -> None:
        rows = []
        for offset, date in enumerate(pd.date_range("2022-01-01", periods=30, freq="MS")):
            seasonal = 1 + 0.2 * np.sin(2 * np.pi * date.month / 12)
            revenue = (10_000 + offset * 200) * seasonal
            rows.append(
                {
                    "Order_ID": f"O{offset}",
                    "Order_Date": date,
                    "Customer_ID": f"C{offset % 8}",
                    "Customer_Name": "Test Customer",
                    "Gender": "Female",
                    "Age": 40,
                    "Category": "Apparel",
                    "Region": "West",
                    "Quantity": 1,
                    "Unit_Price": revenue,
                    "Discount": 0.1,
                    "Revenue": revenue,
                    "Cost": revenue * 0.65,
                    "Profit": revenue * 0.35,
                    "Order_Status": "Delivered",
                }
            )
        result = forecast_revenue(pd.DataFrame(rows), horizon=6)
        self.assertEqual(len(result.forecast), 6)
        self.assertTrue((result.forecast["Lower_95"] >= 0).all())
        self.assertTrue((result.forecast["Upper_95"] >= result.forecast["Forecast_Revenue"]).all())
        self.assertIsNotNone(result.backtest_mae)

    def test_discount_association_is_reported_as_a_statistic(self) -> None:
        result = discount_association(sample_sales())
        self.assertGreaterEqual(result["observations"], 3)
        self.assertIsNotNone(result["rho"])
        self.assertIsNotNone(result["p_value"])

    def test_management_exports_are_valid(self) -> None:
        data = sample_sales()
        rfm = build_rfm(data)
        counts, retention = cohort_retention(data)
        forecast = forecast_revenue(data)
        quality = {"clean_rows": len(data), "business_rule_violations_after": {"profit_reconciliation": 0}}
        workbook_bytes = build_excel_report(data, rfm, counts, retention, forecast, quality)
        workbook = load_workbook(BytesIO(workbook_bytes), read_only=True)
        self.assertIn("Executive Summary", workbook.sheetnames)
        self.assertIn("Customer RFM", workbook.sheetnames)
        pdf_bytes = build_pdf_report(data, rfm, retention, forecast, quality, "Jan — Apr 2024")
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        with ZipFile(BytesIO(workbook_bytes)) as archive:
            self.assertIn("xl/workbook.xml", archive.namelist())


if __name__ == "__main__":
    unittest.main()
