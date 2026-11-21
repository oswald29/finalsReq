CREATE DATABASE IF NOT EXISTS grocerylist_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE grocerylist_db;

-- Run once when the existing table grocerylist_db has:
-- id, Product_name, Quantity, Unit_Price.
-- Do not run if grocerylist_db_backup already exists. The old table is preserved
-- under that backup name, and copied rows receive new unique auto-increment IDs.
CREATE TABLE grocerylist_db_rebuilt (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  item VARCHAR(100) NOT NULL,
  quantity INT UNSIGNED NOT NULL DEFAULT 1,
  unit_price DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
  user_id BIGINT UNSIGNED NULL,
  purchased TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_grocerylist_user_purchased (user_id, purchased, id)
) ENGINE=InnoDB;

INSERT INTO grocerylist_db_rebuilt (item, quantity, unit_price)
SELECT Product_name, Quantity, Unit_Price
FROM grocerylist_db
ORDER BY id, Product_name, Quantity, Unit_Price;

RENAME TABLE
  grocerylist_db TO grocerylist_db_backup,
  grocerylist_db_rebuilt TO grocerylist_db;
