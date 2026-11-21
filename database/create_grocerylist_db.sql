CREATE DATABASE IF NOT EXISTS grocerylist_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE grocerylist_db;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  email VARCHAR(254) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(80) NOT NULL DEFAULT '',
  monthly_budget DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_sessions (
  token_hash CHAR(64) NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  expires_at BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (token_hash),
  INDEX idx_auth_sessions_expiration (expires_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS grocerylist_db (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  item VARCHAR(100) NOT NULL,
  quantity INT UNSIGNED NOT NULL DEFAULT 1,
  unit_price DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
  user_id BIGINT UNSIGNED NULL,
  purchased TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  purchased_at DATETIME NULL,
  PRIMARY KEY (id),
  INDEX idx_grocerylist_user_purchased (user_id, purchased, id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS purchase_history (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id BIGINT UNSIGNED NOT NULL,
  grocery_item_id BIGINT UNSIGNED NULL,
  product_name VARCHAR(100) NOT NULL,
  category VARCHAR(60) NOT NULL DEFAULT 'Groceries',
  quantity INT UNSIGNED NOT NULL,
  unit_price DECIMAL(10, 2) NOT NULL,
  expense DECIMAL(12, 2) NOT NULL,
  date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_purchase_history_user_date (user_id, date, id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS expense_records (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(100) NOT NULL,
  amount DECIMAL(12, 2) NOT NULL,
  category VARCHAR(60) NOT NULL,
  date DATE NOT NULL,
  notes VARCHAR(500) NOT NULL DEFAULT '',
  purchased_at DATETIME NULL,
  source_sqlite_user_id INTEGER NULL,
  source_sqlite_id INTEGER NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_expense_legacy_source (source_sqlite_user_id, source_sqlite_id),
  INDEX idx_expense_records_user_date (user_id, date, id)
) ENGINE=InnoDB;
