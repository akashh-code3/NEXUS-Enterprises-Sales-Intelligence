USE enterprise_sales;

-- 1. Executive sales and profit summary
SELECT SUM(revenue) AS revenue, SUM(profit) AS profit, SUM(quantity) AS units,
       COUNT(*) AS order_count, SUM(profit) / NULLIF(SUM(revenue), 0) AS margin
FROM fact_sales WHERE order_status NOT IN ('Cancelled', 'Returned');

-- 2. Monthly revenue and profit trend
SELECT d.year, d.month, d.month_name, SUM(f.revenue) AS revenue, SUM(f.profit) AS profit
FROM fact_sales f JOIN dim_date d USING (date_key)
GROUP BY d.year, d.month, d.month_name ORDER BY d.year, d.month;

-- 3. Top 10 products by revenue
SELECT p.product_name, p.category, SUM(f.revenue) AS revenue
FROM fact_sales f JOIN dim_product p USING (product_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY p.product_key, p.product_name, p.category ORDER BY revenue DESC LIMIT 10;

-- 4. Top 10 customers by lifetime revenue
SELECT c.customer_id, c.customer_name, SUM(f.revenue) AS lifetime_revenue
FROM fact_sales f JOIN dim_customer c USING (customer_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY c.customer_key, c.customer_id, c.customer_name ORDER BY lifetime_revenue DESC LIMIT 10;

-- 5. Revenue and margin by category
SELECT p.category, SUM(f.revenue) AS revenue, SUM(f.profit) AS profit,
       SUM(f.profit) / NULLIF(SUM(f.revenue), 0) AS margin
FROM fact_sales f JOIN dim_product p USING (product_key)
GROUP BY p.category ORDER BY revenue DESC;

-- 6. Revenue by region
SELECT g.region, SUM(f.revenue) AS revenue, SUM(f.profit) AS profit
FROM fact_sales f JOIN dim_geography g USING (geography_key)
GROUP BY g.region ORDER BY revenue DESC;

-- 7. Revenue by state
SELECT g.state, g.region, SUM(f.revenue) AS revenue
FROM fact_sales f JOIN dim_geography g USING (geography_key)
GROUP BY g.state, g.region ORDER BY revenue DESC LIMIT 20;

-- 8. Average order value by payment method
SELECT payment_method, SUM(revenue) / NULLIF(COUNT(*), 0) AS average_order_value, COUNT(*) AS orders
FROM fact_sales WHERE order_status NOT IN ('Cancelled', 'Returned')
GROUP BY payment_method ORDER BY average_order_value DESC;

-- 9. Discount band impact on margin
SELECT CASE WHEN discount = 0 THEN '0%'
            WHEN discount <= 0.10 THEN '1-10%'
            WHEN discount <= 0.20 THEN '11-20%'
            ELSE '21%+' END AS discount_band,
       SUM(revenue) AS revenue, SUM(profit) AS profit,
       SUM(profit) / NULLIF(SUM(revenue), 0) AS margin
FROM fact_sales WHERE order_status NOT IN ('Cancelled', 'Returned')
GROUP BY discount_band ORDER BY MIN(discount);

-- 10. Return and cancellation rate by category
SELECT p.category, COUNT(*) AS orders,
       SUM(f.order_status = 'Returned') / COUNT(*) AS return_rate,
       SUM(f.order_status = 'Cancelled') / COUNT(*) AS cancellation_rate
FROM fact_sales f JOIN dim_product p USING (product_key)
GROUP BY p.category ORDER BY return_rate DESC;

-- 11. Average shipping time by region
SELECT g.region, AVG(f.shipping_days) AS avg_shipping_days
FROM fact_sales f JOIN dim_geography g USING (geography_key)
WHERE f.order_status IN ('Delivered', 'Returned')
GROUP BY g.region ORDER BY avg_shipping_days DESC;

-- 12. Revenue mix by gender
SELECT c.gender, SUM(f.revenue) AS revenue, COUNT(*) AS orders,
       SUM(f.revenue) / NULLIF(COUNT(*), 0) AS revenue_per_order
FROM fact_sales f JOIN dim_customer c USING (customer_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY c.gender ORDER BY revenue DESC;

-- 13. Customer age cohort performance
SELECT CASE WHEN c.age < 25 THEN '<25' WHEN c.age < 35 THEN '25-34'
            WHEN c.age < 45 THEN '35-44' WHEN c.age < 55 THEN '45-54' ELSE '55+' END AS age_band,
       COUNT(DISTINCT c.customer_key) AS customers, SUM(f.revenue) AS revenue
FROM fact_sales f JOIN dim_customer c USING (customer_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY age_band ORDER BY MIN(c.age);

-- 14. Weekday versus weekend performance
SELECT d.is_weekend, COUNT(*) AS orders, SUM(f.revenue) AS revenue,
       SUM(f.profit) / NULLIF(SUM(f.revenue), 0) AS margin
FROM fact_sales f JOIN dim_date d USING (date_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY d.is_weekend;

-- 15. Quarter-over-quarter revenue change
WITH quarterly AS (
  SELECT d.year, d.quarter, SUM(f.revenue) AS revenue
  FROM fact_sales f JOIN dim_date d USING (date_key)
  WHERE f.order_status NOT IN ('Cancelled', 'Returned')
  GROUP BY d.year, d.quarter
)
SELECT year, quarter, revenue,
       revenue - LAG(revenue) OVER (ORDER BY year, quarter) AS revenue_change,
       revenue / NULLIF(LAG(revenue) OVER (ORDER BY year, quarter), 0) - 1 AS growth_rate
FROM quarterly ORDER BY year, quarter;

-- 16. Year-over-year monthly revenue growth
WITH monthly AS (
  SELECT d.year, d.month, SUM(f.revenue) AS revenue
  FROM fact_sales f JOIN dim_date d USING (date_key)
  WHERE f.order_status NOT IN ('Cancelled', 'Returned')
  GROUP BY d.year, d.month
)
SELECT year, month, revenue,
       revenue / NULLIF(LAG(revenue, 12) OVER (ORDER BY year, month), 0) - 1 AS yoy_growth
FROM monthly ORDER BY year, month;

-- 17. Repeat customer rate
WITH customer_orders AS (
  SELECT customer_key, COUNT(*) AS order_count
  FROM fact_sales WHERE order_status NOT IN ('Cancelled', 'Returned')
  GROUP BY customer_key
)
SELECT COUNT(*) AS customers, SUM(order_count > 1) AS repeat_customers,
       SUM(order_count > 1) / COUNT(*) AS repeat_rate
FROM customer_orders;

-- 18. Customer lifetime value distribution
WITH customer_value AS (
  SELECT customer_key, SUM(revenue) AS lifetime_value
  FROM fact_sales WHERE order_status NOT IN ('Cancelled', 'Returned')
  GROUP BY customer_key
)
SELECT COUNT(*) AS customers, AVG(lifetime_value) AS avg_ltv,
       MAX(lifetime_value) AS max_ltv,
       SUM(lifetime_value >= 1000) AS customers_over_1000
FROM customer_value;

-- 19. Category and subcategory ranking
SELECT p.category, p.sub_category, SUM(f.revenue) AS revenue,
       DENSE_RANK() OVER (PARTITION BY p.category ORDER BY SUM(f.revenue) DESC) AS category_rank
FROM fact_sales f JOIN dim_product p USING (product_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY p.category, p.sub_category;

-- 20. Profitability by subcategory
SELECT p.category, p.sub_category, SUM(f.profit) AS profit,
       SUM(f.profit) / NULLIF(SUM(f.revenue), 0) AS margin
FROM fact_sales f JOIN dim_product p USING (product_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY p.category, p.sub_category ORDER BY profit;

-- 21. Revenue by city
SELECT g.city, g.state, g.region, SUM(f.revenue) AS revenue
FROM fact_sales f JOIN dim_geography g USING (geography_key)
GROUP BY g.city, g.state, g.region ORDER BY revenue DESC LIMIT 25;

-- 22. Payment method order share
SELECT payment_method, COUNT(*) AS order_count,
       COUNT(*) / SUM(COUNT(*)) OVER () AS order_share
FROM fact_sales GROUP BY payment_method ORDER BY order_count DESC;

-- 23. High-discount orders with negative profit
SELECT f.order_id, p.product_name, f.discount, f.revenue, f.profit
FROM fact_sales f JOIN dim_product p USING (product_key)
WHERE f.discount >= 0.20 AND f.profit < 0 ORDER BY f.profit LIMIT 100;

-- 24. Monthly sales seasonality by category
SELECT d.month, d.month_name, p.category, SUM(f.revenue) AS revenue
FROM fact_sales f JOIN dim_date d USING (date_key)
JOIN dim_product p USING (product_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY d.month, d.month_name, p.category ORDER BY d.month, revenue DESC;

-- 25. Shipping SLA performance
SELECT CASE WHEN shipping_days <= 2 THEN '0-2 days'
            WHEN shipping_days <= 5 THEN '3-5 days' ELSE '6+ days' END AS shipping_band,
       COUNT(*) AS orders, SUM(revenue) AS revenue
FROM fact_sales WHERE order_status = 'Delivered'
GROUP BY shipping_band ORDER BY MIN(shipping_days);

-- 26. Product basket-size and unit economics
SELECT p.product_name, SUM(f.quantity) AS units, SUM(f.revenue) AS revenue,
       SUM(f.profit) / NULLIF(SUM(f.quantity), 0) AS profit_per_unit
FROM fact_sales f JOIN dim_product p USING (product_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY p.product_key, p.product_name ORDER BY units DESC LIMIT 20;

-- 27. Regional category mix
SELECT g.region, p.category, SUM(f.revenue) AS revenue,
       SUM(f.revenue) / SUM(SUM(f.revenue)) OVER (PARTITION BY g.region) AS regional_mix
FROM fact_sales f JOIN dim_geography g USING (geography_key)
JOIN dim_product p USING (product_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY g.region, p.category ORDER BY g.region, revenue DESC;

-- 28. New versus returning monthly customers
WITH first_order AS (
  SELECT customer_key, MIN(date_key) AS first_date_key
  FROM fact_sales WHERE order_status NOT IN ('Cancelled', 'Returned')
  GROUP BY customer_key
)
SELECT d.year, d.month,
       COUNT(DISTINCT CASE WHEN f.date_key = fo.first_date_key THEN f.customer_key END) AS new_customers,
       COUNT(DISTINCT CASE WHEN f.date_key <> fo.first_date_key THEN f.customer_key END) AS returning_customers
FROM fact_sales f JOIN dim_date d USING (date_key)
JOIN first_order fo USING (customer_key)
WHERE f.order_status NOT IN ('Cancelled', 'Returned')
GROUP BY d.year, d.month ORDER BY d.year, d.month;

-- 29. Top 5 products within each region
WITH regional_products AS (
  SELECT g.region, p.product_name, SUM(f.revenue) AS revenue,
         DENSE_RANK() OVER (PARTITION BY g.region ORDER BY SUM(f.revenue) DESC) AS product_rank
  FROM fact_sales f JOIN dim_geography g USING (geography_key)
  JOIN dim_product p USING (product_key)
  WHERE f.order_status NOT IN ('Cancelled', 'Returned')
  GROUP BY g.region, p.product_key, p.product_name
)
SELECT region, product_name, revenue, product_rank
FROM regional_products WHERE product_rank <= 5 ORDER BY region, product_rank;

-- 30. Monthly cumulative revenue
WITH monthly AS (
  SELECT d.year, d.month, SUM(f.revenue) AS revenue
  FROM fact_sales f JOIN dim_date d USING (date_key)
  WHERE f.order_status NOT IN ('Cancelled', 'Returned')
  GROUP BY d.year, d.month
)
SELECT year, month, revenue,
       SUM(revenue) OVER (PARTITION BY year ORDER BY month) AS year_to_date_revenue
FROM monthly ORDER BY year, month;
