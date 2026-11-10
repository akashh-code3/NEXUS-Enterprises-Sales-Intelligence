"""Load the cleaned sales dataset into the enterprise_sales MySQL star schema."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "processed" / "sales_cleaned.csv"
SCHEMA_FILE = ROOT / "sql" / "schema.sql"
CHUNK_SIZE = 5_000


def require_database_url() -> str:
    value = os.getenv("SALES_DATABASE_URL")
    if not value:
        raise RuntimeError(
            "Set SALES_DATABASE_URL, for example "
            "mysql+mysqlconnector://user:password@localhost:3306/enterprise_sales"
        )
    return value


def main() -> None:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"{DATA_FILE} not found. Run scripts/clean_data.py first.")
    url = require_database_url()
    engine = create_engine(url, pool_pre_ping=True)

    frame = pd.read_csv(DATA_FILE, parse_dates=["Order_Date"])
    schema_statements = [
        statement.strip()
        for statement in SCHEMA_FILE.read_text(encoding="utf-8").split(";")
        if statement.strip()
    ]
    with engine.begin() as connection:
        for statement in schema_statements:
            connection.exec_driver_sql(statement)
        customers = frame[["Customer_ID", "Customer_Name", "Gender", "Age"]].drop_duplicates("Customer_ID")
        products = frame[["Product_ID", "Product_Name", "Category", "Sub_Category"]].drop_duplicates("Product_ID")
        geographies = frame[["Region", "State", "City"]].drop_duplicates()
        dates = pd.date_range(frame["Order_Date"].min().normalize(), frame["Order_Date"].max().normalize(), freq="D")

        connection.execute(
            text(
                "INSERT INTO dim_customer (customer_id, customer_name, gender, age) "
                "VALUES (:Customer_ID, :Customer_Name, :Gender, :Age) "
                "ON DUPLICATE KEY UPDATE customer_name=VALUES(customer_name), gender=VALUES(gender), age=VALUES(age)"
            ),
            customers.to_dict("records"),
        )
        connection.execute(
            text(
                "INSERT INTO dim_product (product_id, product_name, category, sub_category) "
                "VALUES (:Product_ID, :Product_Name, :Category, :Sub_Category) "
                "ON DUPLICATE KEY UPDATE product_name=VALUES(product_name), category=VALUES(category), sub_category=VALUES(sub_category)"
            ),
            products.to_dict("records"),
        )
        connection.execute(
            text(
                "INSERT INTO dim_geography (region, state, city) VALUES (:Region, :State, :City) "
                "ON DUPLICATE KEY UPDATE city=VALUES(city)"
            ),
            geographies.to_dict("records"),
        )
        date_records = []
        for date in dates:
            date_records.append(
                {
                    "date_key": int(date.strftime("%Y%m%d")),
                    "full_date": date.date(),
                    "year": date.year,
                    "quarter": (date.month - 1) // 3 + 1,
                    "month": date.month,
                    "month_name": date.strftime("%B"),
                    "week_of_year": int(date.isocalendar().week),
                    "day_of_week": date.isoweekday(),
                    "is_weekend": date.weekday() >= 5,
                }
            )
        connection.execute(
            text(
                "INSERT INTO dim_date (date_key, full_date, year, quarter, month, month_name, week_of_year, day_of_week, is_weekend) "
                "VALUES (:date_key, :full_date, :year, :quarter, :month, :month_name, :week_of_year, :day_of_week, :is_weekend) "
                "ON DUPLICATE KEY UPDATE full_date=VALUES(full_date)"
            ),
            date_records,
        )

        customer_keys = dict(connection.execute(text("SELECT customer_id, customer_key FROM dim_customer")).all())
        product_keys = dict(connection.execute(text("SELECT product_id, product_key FROM dim_product")).all())
        geography_keys = {
            (region, state, city): key
            for region, state, city, key in connection.execute(
                text("SELECT region, state, city, geography_key FROM dim_geography")
            ).all()
        }

        fact = frame[
            [
                "Order_ID", "Order_Date", "Customer_ID", "Product_ID", "Region", "State", "City",
                "Quantity", "Unit_Price", "Discount", "Revenue", "Cost", "Profit",
                "Payment_Method", "Order_Status", "Shipping_Days",
            ]
        ].copy()
        fact["date_key"] = fact["Order_Date"].dt.strftime("%Y%m%d").astype(int)
        fact["customer_key"] = fact["Customer_ID"].map(customer_keys)
        fact["product_key"] = fact["Product_ID"].map(product_keys)
        fact["geography_key"] = [
            geography_keys[(region, state, city)]
            for region, state, city in zip(fact["Region"], fact["State"], fact["City"])
        ]
        fact = fact.rename(
            columns={
                "Order_ID": "order_id",
                "Quantity": "quantity",
                "Unit_Price": "unit_price",
                "Discount": "discount",
                "Revenue": "revenue",
                "Cost": "cost",
                "Profit": "profit",
                "Payment_Method": "payment_method",
                "Order_Status": "order_status",
                "Shipping_Days": "shipping_days",
            }
        )
        fact = fact[
            [
                "order_id", "date_key", "customer_key", "product_key", "geography_key",
                "quantity", "unit_price", "discount", "revenue", "cost", "profit",
                "payment_method", "order_status", "shipping_days",
            ]
        ]
        insert_sql = text(
            "INSERT INTO fact_sales "
            "(order_id, date_key, customer_key, product_key, geography_key, quantity, unit_price, discount, "
            "revenue, cost, profit, payment_method, order_status, shipping_days) "
            "VALUES (:order_id, :date_key, :customer_key, :product_key, :geography_key, :quantity, :unit_price, "
            ":discount, :revenue, :cost, :profit, :payment_method, :order_status, :shipping_days) "
            "ON DUPLICATE KEY UPDATE date_key=VALUES(date_key), customer_key=VALUES(customer_key), "
            "product_key=VALUES(product_key), geography_key=VALUES(geography_key), quantity=VALUES(quantity), "
            "unit_price=VALUES(unit_price), discount=VALUES(discount), revenue=VALUES(revenue), cost=VALUES(cost), "
            "profit=VALUES(profit), payment_method=VALUES(payment_method), order_status=VALUES(order_status), "
            "shipping_days=VALUES(shipping_days)"
        )
        records = fact.to_dict("records")
        for start in range(0, len(records), CHUNK_SIZE):
            connection.execute(insert_sql, records[start : start + CHUNK_SIZE])

    engine.dispose()
    print(f"Loaded {len(frame):,} sales records into enterprise_sales.")


if __name__ == "__main__":
    main()
