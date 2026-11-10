"""Generate a reproducible, realistic retail sales dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "raw" / "sales_raw.csv"

GEO = {
    "Northeast": {
        "New York": ["New York City", "Buffalo", "Rochester"],
        "Massachusetts": ["Boston", "Worcester", "Springfield"],
        "Pennsylvania": ["Philadelphia", "Pittsburgh", "Allentown"],
        "New Jersey": ["Newark", "Jersey City", "Trenton"],
    },
    "South": {
        "Texas": ["Houston", "Dallas", "Austin", "San Antonio"],
        "Florida": ["Miami", "Orlando", "Tampa", "Jacksonville"],
        "Georgia": ["Atlanta", "Savannah", "Augusta"],
        "North Carolina": ["Charlotte", "Raleigh", "Durham"],
    },
    "Midwest": {
        "Illinois": ["Chicago", "Springfield", "Naperville"],
        "Ohio": ["Columbus", "Cleveland", "Cincinnati"],
        "Michigan": ["Detroit", "Grand Rapids", "Ann Arbor"],
        "Minnesota": ["Minneapolis", "Saint Paul", "Rochester"],
    },
    "West": {
        "California": ["Los Angeles", "San Francisco", "San Diego", "Sacramento"],
        "Washington": ["Seattle", "Spokane", "Tacoma"],
        "Arizona": ["Phoenix", "Tucson", "Mesa"],
        "Colorado": ["Denver", "Colorado Springs", "Boulder"],
    },
}

PRODUCTS = [
    ("Electronics", "Computers", ["Laptop Pro 14", "Ultrabook Air", "Desktop Workstation", "Gaming Laptop"]),
    ("Electronics", "Audio", ["Wireless Headphones", "Bluetooth Speaker", "Studio Headset", "Soundbar"]),
    ("Electronics", "Accessories", ["USB-C Hub", "Wireless Mouse", "Mechanical Keyboard", "4K Webcam"]),
    ("Home & Living", "Furniture", ["Ergonomic Chair", "Standing Desk", "Bookshelf", "Lounge Chair"]),
    ("Home & Living", "Kitchen", ["Air Fryer", "Espresso Machine", "Blender Pro", "Smart Kettle"]),
    ("Home & Living", "Decor", ["Table Lamp", "Area Rug", "Wall Art Set", "Ceramic Vase"]),
    ("Apparel", "Clothing", ["Performance Jacket", "Classic Denim", "Everyday Hoodie", "Linen Shirt"]),
    ("Apparel", "Footwear", ["Trail Runner", "Leather Sneaker", "City Boot", "Training Shoe"]),
    ("Apparel", "Accessories", ["Leather Tote", "Travel Backpack", "Wool Scarf", "Classic Belt"]),
    ("Sports & Outdoors", "Fitness", ["Adjustable Dumbbells", "Yoga Mat", "Fitness Tracker", "Resistance Kit"]),
    ("Sports & Outdoors", "Outdoor", ["Camping Tent", "Daypack 28L", "Trekking Poles", "Insulated Bottle"]),
    ("Sports & Outdoors", "Cycling", ["Road Helmet", "Commuter Light Set", "Cycling Gloves", "Floor Pump"]),
    ("Beauty & Wellness", "Skincare", ["Daily Moisturizer", "Vitamin C Serum", "Gentle Cleanser", "SPF 50 Lotion"]),
    ("Beauty & Wellness", "Personal Care", ["Hair Dryer", "Electric Toothbrush", "Beard Trimmer", "Travel Grooming Kit"]),
    ("Beauty & Wellness", "Wellness", ["Aromatherapy Set", "Sleep Mask", "Massage Gun", "Humidifier"]),
]
PRODUCT_PRICE_RANGES = {
    "Electronics": (24, 1550),
    "Home & Living": (18, 1100),
    "Apparel": (16, 320),
    "Sports & Outdoors": (12, 620),
    "Beauty & Wellness": (10, 260),
}
FIRST_NAMES = [
    "Avery", "Jordan", "Taylor", "Morgan", "Riley", "Casey", "Quinn", "Cameron",
    "Skyler", "Alex", "Drew", "Jamie", "Reese", "Parker", "Rowan", "Elliot",
]
LAST_NAMES = [
    "Morgan", "Brooks", "Patel", "Kim", "Reed", "Bennett", "Rivera", "Carter",
    "Foster", "Nguyen", "Price", "Hayes", "Cooper", "Sullivan", "Wright", "Diaz",
]


def build_products(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    product_number = 1
    for category, sub_category, names in PRODUCTS:
        low, high = PRODUCT_PRICE_RANGES[category]
        for name in names:
            price = round(float(rng.uniform(low, high)), 2)
            unit_cost = round(price * float(rng.uniform(0.48, 0.72)), 2)
            rows.append((f"P{product_number:04d}", name, category, sub_category, price, unit_cost))
            product_number += 1
    return pd.DataFrame(
        rows,
        columns=["Product_ID", "Product_Name", "Category", "Sub_Category", "Unit_Price", "Unit_Cost"],
    )


def generate_sales(record_count: int = 105_000, seed: int = 42) -> pd.DataFrame:
    """Create sales rows with seasonality, repeat customers, discounts and operational noise."""
    if record_count < 100_000:
        raise ValueError("record_count must be at least 100,000.")

    rng = np.random.default_rng(seed)
    products = build_products(rng)
    customer_count = max(12_000, int(record_count * 0.14))
    customer_ids = np.array([f"C{i:06d}" for i in range(1, customer_count + 1)])
    customer_names = np.array(
        [f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}" for _ in customer_ids]
    )
    genders = rng.choice(["Female", "Male", "Non-binary"], size=customer_count, p=[0.49, 0.48, 0.03])
    ages = np.clip(np.rint(rng.normal(40, 13, customer_count)), 18, 78).astype(int)
    customer_index = rng.integers(0, customer_count, size=record_count)

    start = np.datetime64("2023-01-01")
    end = np.datetime64("2026-01-01")
    days = int((end - start).astype("timedelta64[D]").astype(int))
    order_dates = start + rng.integers(0, days, size=record_count).astype("timedelta64[D]")
    month = pd.DatetimeIndex(order_dates).month.to_numpy()
    seasonality = np.select(
        [np.isin(month, [11, 12]), np.isin(month, [1, 2]), np.isin(month, [6, 7, 8])],
        [1.50, 0.82, 1.12],
        default=1.0,
    )

    product_index = rng.choice(
        len(products),
        size=record_count,
        p=np.array([1.2 if c in ("Electronics", "Home & Living") else 1.0 for c in products["Category"]])
        / sum([1.2 if c in ("Electronics", "Home & Living") else 1.0 for c in products["Category"]]),
    )
    selected_products = products.iloc[product_index].reset_index(drop=True)
    category = selected_products["Category"].to_numpy()
    unit_price = selected_products["Unit_Price"].to_numpy(dtype=float)
    unit_cost = selected_products["Unit_Cost"].to_numpy(dtype=float)

    region_names = np.array(list(GEO))
    region = rng.choice(region_names, size=record_count, p=[0.24, 0.29, 0.22, 0.25])
    state = np.empty(record_count, dtype=object)
    city = np.empty(record_count, dtype=object)
    for region_name, states in GEO.items():
        mask = region == region_name
        state_names = np.array(list(states))
        chosen_states = rng.choice(state_names, size=int(mask.sum()))
        state[mask] = chosen_states
        for state_name, cities in states.items():
            state_mask = mask & (state == state_name)
            city[state_mask] = rng.choice(cities, size=int(state_mask.sum()))

    quantity = np.clip(rng.poisson(1.7, record_count) + 1, 1, 12).astype(int)
    quantity = np.where(rng.random(record_count) < 0.08, quantity + rng.integers(2, 8, record_count), quantity)
    discount = rng.choice(
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
        size=record_count,
        p=[0.36, 0.13, 0.20, 0.15, 0.09, 0.05, 0.02],
    )
    discount = np.minimum(discount * seasonality, 0.40)
    revenue = np.round(quantity * unit_price * (1 - discount), 2)
    cost = np.round(quantity * unit_cost, 2)
    profit = np.round(revenue - cost, 2)

    status = rng.choice(
        ["Delivered", "Shipped", "Processing", "Cancelled", "Returned"],
        size=record_count,
        p=[0.82, 0.09, 0.045, 0.025, 0.02],
    )
    # Cancelled/returned orders carry zero realized revenue and profit.
    reversed_mask = np.isin(status, ["Cancelled", "Returned"])
    revenue[reversed_mask] = 0.0
    profit[reversed_mask] = -cost[reversed_mask]
    shipping_days = np.where(
        status == "Cancelled",
        0,
        np.clip(rng.gamma(shape=2.2, scale=1.6, size=record_count).round(), 1, 15),
    ).astype(int)

    payment_method = rng.choice(
        ["Credit Card", "Debit Card", "PayPal", "Digital Wallet", "Bank Transfer"],
        size=record_count,
        p=[0.42, 0.22, 0.17, 0.14, 0.05],
    )
    result = pd.DataFrame(
        {
            "Order_ID": [f"ORD{i:08d}" for i in range(1, record_count + 1)],
            "Order_Date": pd.to_datetime(order_dates),
            "Customer_ID": customer_ids[customer_index],
            "Customer_Name": customer_names[customer_index],
            "Gender": genders[customer_index],
            "Age": ages[customer_index],
            "Product_ID": selected_products["Product_ID"].to_numpy(),
            "Product_Name": selected_products["Product_Name"].to_numpy(),
            "Category": category,
            "Sub_Category": selected_products["Sub_Category"].to_numpy(),
            "Region": region,
            "State": state,
            "City": city,
            "Quantity": quantity,
            "Unit_Price": unit_price,
            "Discount": discount,
            "Revenue": revenue,
            "Cost": cost,
            "Profit": profit,
            "Payment_Method": payment_method,
            "Order_Status": status,
            "Shipping_Days": shipping_days,
        }
    )

    # Small, controlled quality defects make the cleaning workflow demonstrable.
    missing_rows = rng.choice(record_count, size=max(1, record_count // 2_000), replace=False)
    result.loc[missing_rows, "City"] = None
    category_row = int(rng.integers(record_count))
    result.loc[category_row, "Payment_Method"] = "credit card "
    duplicate_count = max(1, record_count // 1_000)
    duplicates = result.sample(n=duplicate_count, random_state=seed)
    return pd.concat([result, duplicates], ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=105_000, help="Number of distinct base records (minimum 100000).")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Destination CSV path.")
    args = parser.parse_args()
    data = generate_sales(args.rows, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(args.output, index=False, date_format="%Y-%m-%d")
    print(f"Wrote {len(data):,} rows to {args.output}")


if __name__ == "__main__":
    main()
