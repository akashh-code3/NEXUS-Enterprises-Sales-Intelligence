CREATE DATABASE IF NOT EXISTS enterprise_sales
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
USE enterprise_sales;

CREATE TABLE IF NOT EXISTS dim_date (
  date_key INT PRIMARY KEY,
  full_date DATE NOT NULL UNIQUE,
  year SMALLINT NOT NULL,
  quarter TINYINT NOT NULL,
  month TINYINT NOT NULL,
  month_name VARCHAR(12) NOT NULL,
  week_of_year TINYINT NOT NULL,
  day_of_week TINYINT NOT NULL,
  is_weekend BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_customer (
  customer_key INT AUTO_INCREMENT PRIMARY KEY,
  customer_id VARCHAR(24) NOT NULL UNIQUE,
  customer_name VARCHAR(120) NOT NULL,
  gender VARCHAR(24) NOT NULL,
  age SMALLINT NOT NULL,
  INDEX idx_customer_gender (gender)
);

CREATE TABLE IF NOT EXISTS dim_product (
  product_key INT AUTO_INCREMENT PRIMARY KEY,
  product_id VARCHAR(24) NOT NULL UNIQUE,
  product_name VARCHAR(120) NOT NULL,
  category VARCHAR(60) NOT NULL,
  sub_category VARCHAR(60) NOT NULL,
  INDEX idx_product_category (category, sub_category)
);

CREATE TABLE IF NOT EXISTS dim_geography (
  geography_key INT AUTO_INCREMENT PRIMARY KEY,
  region VARCHAR(40) NOT NULL,
  state VARCHAR(60) NOT NULL,
  city VARCHAR(80) NOT NULL,
  UNIQUE KEY uq_geography (region, state, city),
  INDEX idx_geography_region (region)
);

CREATE TABLE IF NOT EXISTS fact_sales (
  sales_key BIGINT AUTO_INCREMENT PRIMARY KEY,
  order_id VARCHAR(32) NOT NULL,
  date_key INT NOT NULL,
  customer_key INT NOT NULL,
  product_key INT NOT NULL,
  geography_key INT NOT NULL,
  quantity SMALLINT NOT NULL,
  unit_price DECIMAL(12,2) NOT NULL,
  discount DECIMAL(5,4) NOT NULL,
  revenue DECIMAL(14,2) NOT NULL,
  cost DECIMAL(14,2) NOT NULL,
  profit DECIMAL(14,2) NOT NULL,
  payment_method VARCHAR(40) NOT NULL,
  order_status VARCHAR(24) NOT NULL,
  shipping_days SMALLINT NOT NULL,
  UNIQUE KEY uq_fact_order (order_id),
  INDEX idx_fact_date_status (date_key, order_status),
  INDEX idx_fact_product (product_key),
  INDEX idx_fact_customer (customer_key),
  INDEX idx_fact_geography (geography_key),
  CONSTRAINT fk_fact_date FOREIGN KEY (date_key) REFERENCES dim_date(date_key),
  CONSTRAINT fk_fact_customer FOREIGN KEY (customer_key) REFERENCES dim_customer(customer_key),
  CONSTRAINT fk_fact_product FOREIGN KEY (product_key) REFERENCES dim_product(product_key),
  CONSTRAINT fk_fact_geography FOREIGN KEY (geography_key) REFERENCES dim_geography(geography_key),
  CONSTRAINT chk_fact_quantity CHECK (quantity > 0),
  CONSTRAINT chk_fact_discount CHECK (discount BETWEEN 0 AND 0.8)
);
