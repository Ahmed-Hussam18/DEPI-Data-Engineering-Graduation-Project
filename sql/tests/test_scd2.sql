BEGIN;

-- Add test products to staging
TRUNCATE TABLE staging.products;

INSERT INTO staging.products (product_id, name, category, unit)
VALUES
    ('TEST001', 'Gold Ring', 'Jewelry', 'gram'),
    ('TEST002', 'Gold Necklace', 'Jewelry', 'gram');

COMMIT;