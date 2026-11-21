from __future__ import annotations

import hashlib
import hmac
import logging
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

import mysql.connector
from mysql.connector import Error as MySQLError
from fastapi import Body, FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_NAME = Path(os.environ.get("EXPENSE_DB_PATH", PROJECT_ROOT / "expenses.db"))
MYSQL_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "database": os.environ.get("MYSQL_DATABASE", "grocerylist_db"),
}
SESSION_LIFETIME_SECONDS = 60 * 60 * 24 * 7
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 256
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EXPENSE_CATEGORIES = {
    "Food & Dining",
    "Transportation",
    "Shopping",
    "Utilities",
    "Entertainment",
    "Health",
    "Food",
    "Transport",
    "Bills",
    "Bills & Utilities",
    "Games & Recharges",
    "Groceries",
    "Other",
}


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_NAME)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def connect_grocery_db() -> mysql.connector.MySQLConnection:
    try:
        return mysql.connector.connect(**MYSQL_CONFIG)
    except MySQLError as error:
        if getattr(error, "errno", None) != 1049:
            raise

    database_name = MYSQL_CONFIG["database"]
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise ValueError("MYSQL_DATABASE may contain only letters, numbers, and underscores.")
    server_config = {key: value for key, value in MYSQL_CONFIG.items() if key != "database"}
    with closing(mysql.connector.connect(**server_config)) as server_connection:
        cursor = server_connection.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        cursor.close()
    return mysql.connector.connect(**MYSQL_CONFIG)


def init_db() -> None:
    with closing(connect_db()) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                monthly_budget REAL NOT NULL DEFAULT 0.00,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS account_map (
                mysql_user_id INTEGER PRIMARY KEY,
                sqlite_user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        expense_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(expenses)").fetchall()
        }
        if "user_id" not in expense_columns:
            connection.execute(
                "ALTER TABLE expenses ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE"
            )
        user_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "monthly_budget" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN monthly_budget REAL NOT NULL DEFAULT 0.00"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses(user_id, date DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_expiration ON sessions(expires_at)"
        )


def init_mysql_auth_db() -> None:
    with closing(connect_grocery_db()) as connection:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SHOW COLUMNS FROM users")
            columns = {row["Field"] for row in cursor.fetchall()}
        except MySQLError as error:
            if getattr(error, "errno", None) != 1146:
                raise
            cursor.execute(
                """
                CREATE TABLE users (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    email VARCHAR(254) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    display_name VARCHAR(80) NOT NULL DEFAULT '',
                    monthly_budget DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uq_users_email (email)
                ) ENGINE=InnoDB
                """
            )
            columns = {"id", "email", "password_hash", "display_name", "monthly_budget", "created_at"}

        if "display_name" not in columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN display_name VARCHAR(80) NOT NULL DEFAULT ''"
            )
        if "monthly_budget" not in columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN monthly_budget DECIMAL(12, 2) NOT NULL DEFAULT 0.00"
            )
        cursor.execute("ALTER TABLE users ALTER COLUMN monthly_budget SET DEFAULT 0.00")
        cursor.execute("SHOW TABLES LIKE 'grocerylist_db'")
        if cursor.fetchone() is None:
            cursor.execute(
                """
                CREATE TABLE grocerylist_db (
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
                ) ENGINE=InnoDB
                """
            )
        else:
            cursor.execute("SHOW COLUMNS FROM grocerylist_db")
            grocery_columns = {row["Field"] for row in cursor.fetchall()}
            if "item" not in grocery_columns:
                legacy_name = next(
                    (column for column in ("Product_name", "product_name", "name") if column in grocery_columns),
                    None,
                )
                if legacy_name is not None:
                    cursor.execute(
                        f"ALTER TABLE grocerylist_db CHANGE COLUMN `{legacy_name}` item VARCHAR(100) NOT NULL"
                    )
                    grocery_columns.remove(legacy_name)
                    grocery_columns.add("item")
            if "quantity" not in grocery_columns:
                legacy_quantity = next(
                    (column for column in ("Quantity",) if column in grocery_columns),
                    None,
                )
                if legacy_quantity is not None:
                    cursor.execute(
                        f"ALTER TABLE grocerylist_db CHANGE COLUMN `{legacy_quantity}` quantity INT UNSIGNED NOT NULL DEFAULT 1"
                    )
                    grocery_columns.remove(legacy_quantity)
                    grocery_columns.add("quantity")
                else:
                    cursor.execute(
                        "ALTER TABLE grocerylist_db ADD COLUMN quantity INT UNSIGNED NOT NULL DEFAULT 1"
                    )
            if "unit_price" not in grocery_columns:
                legacy_price = next(
                    (column for column in ("Unit_Price", "price") if column in grocery_columns),
                    None,
                )
                if legacy_price is not None:
                    cursor.execute(
                        f"ALTER TABLE grocerylist_db CHANGE COLUMN `{legacy_price}` unit_price DECIMAL(10, 2) NOT NULL DEFAULT 0.00"
                    )
                    grocery_columns.remove(legacy_price)
                    grocery_columns.add("unit_price")
                else:
                    cursor.execute(
                        "ALTER TABLE grocerylist_db ADD COLUMN unit_price DECIMAL(10, 2) NOT NULL DEFAULT 0.00"
                    )
            for column_name, definition in {
                "user_id": "BIGINT UNSIGNED NULL",
                "purchased": "TINYINT(1) NOT NULL DEFAULT 0",
            }.items():
                if column_name not in grocery_columns:
                    cursor.execute(
                        f"ALTER TABLE grocerylist_db ADD COLUMN {column_name} {definition}"
                    )
            if "purchased_at" not in grocery_columns:
                cursor.execute("ALTER TABLE grocerylist_db ADD COLUMN purchased_at DATETIME NULL")
            if "created_at" not in grocery_columns:
                cursor.execute(
                    "ALTER TABLE grocerylist_db ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                )
        cursor.execute("SHOW TABLES LIKE 'purchase_history'")
        if cursor.fetchone() is None:
            cursor.execute(
                """
                CREATE TABLE purchase_history (
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
                ) ENGINE=InnoDB
                """
            )
        cursor.execute("SHOW COLUMNS FROM purchase_history")
        purchase_columns = {row["Field"] for row in cursor.fetchall()}
        purchase_column_migrations = {
            "user_id": "BIGINT UNSIGNED NULL",
            "grocery_item_id": "BIGINT UNSIGNED NULL",
            "category": "VARCHAR(60) NOT NULL DEFAULT 'Groceries'",
            "quantity": "INT UNSIGNED NOT NULL DEFAULT 1",
            "unit_price": "DECIMAL(10, 2) NOT NULL DEFAULT 0.00",
            "expense": "DECIMAL(12, 2) NOT NULL DEFAULT 0.00",
        }
        for column_name, definition in purchase_column_migrations.items():
            if column_name not in purchase_columns:
                cursor.execute(
                    f"ALTER TABLE purchase_history ADD COLUMN {column_name} {definition}"
                )
        if "date" not in purchase_columns:
            cursor.execute(
                "ALTER TABLE purchase_history ADD COLUMN date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )
        else:
            cursor.execute("SHOW COLUMNS FROM purchase_history")
            purchase_column_rows = cursor.fetchall()
            date_column = next(row for row in purchase_column_rows if row["Field"] == "date")
            if date_column.get("Type", "").lower() != "datetime" or date_column.get("Default") is None:
                cursor.execute(
                    "ALTER TABLE purchase_history MODIFY COLUMN date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                )

        cursor.execute(
            """
            SELECT id, user_id, item, quantity, unit_price, purchased_at
            FROM grocerylist_db
            WHERE purchased = 1 AND purchased_at IS NOT NULL AND user_id IS NOT NULL
            """
        )
        purchased_groceries = cursor.fetchall()
        for grocery in purchased_groceries:
            cursor.execute(
                """
                SELECT id FROM purchase_history
                WHERE grocery_item_id = %s AND date = %s
                """,
                (grocery["id"], grocery["purchased_at"]),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    """
                    INSERT INTO purchase_history (
                        user_id, grocery_item_id, product_name, category,
                        quantity, unit_price, expense, date
                    )
                    VALUES (%s, %s, %s, 'Groceries', %s, %s, %s, %s)
                    """,
                    (
                        grocery["user_id"],
                        grocery["id"],
                        grocery["item"],
                        grocery["quantity"],
                        grocery["unit_price"],
                        round(int(grocery["quantity"]) * float(grocery["unit_price"]), 2),
                        grocery["purchased_at"],
                    ),
                )
        cursor.execute("SHOW TABLES LIKE 'expense_records'")
        if cursor.fetchone() is None:
            cursor.execute(
                """
                CREATE TABLE expense_records (
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
                ) ENGINE=InnoDB
                """
            )
        else:
            cursor.execute("SHOW COLUMNS FROM expense_records")
            expense_column_rows = cursor.fetchall()
            expense_columns = {row["Field"] for row in expense_column_rows}
            if "purchased_at" not in expense_columns:
                cursor.execute(
                    "ALTER TABLE expense_records ADD COLUMN purchased_at DATETIME NULL"
                )
            elif any(
                row["Field"] == "purchased_at" and row.get("Null") == "NO"
                for row in expense_column_rows
            ):
                cursor.execute(
                    "ALTER TABLE expense_records MODIFY COLUMN purchased_at DATETIME NULL"
                )
            if "source_sqlite_user_id" not in expense_columns:
                cursor.execute(
                    "ALTER TABLE expense_records ADD COLUMN source_sqlite_user_id INTEGER NULL"
                )
            if "source_sqlite_id" not in expense_columns:
                cursor.execute(
                    "ALTER TABLE expense_records ADD COLUMN source_sqlite_id INTEGER NULL"
                )
        cursor.execute("SHOW TABLES LIKE 'auth_sessions'")
        if cursor.fetchone() is None:
            cursor.execute(
                """
                CREATE TABLE auth_sessions (
                    token_hash CHAR(64) NOT NULL,
                    user_id BIGINT UNSIGNED NOT NULL,
                    expires_at BIGINT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (token_hash),
                    INDEX idx_auth_sessions_expiration (expires_at)
                ) ENGINE=InnoDB
                """
            )

        cursor.execute("SELECT id, email, password_hash, display_name, monthly_budget FROM users")
        for user in cursor.fetchall():
            stored_hash = user["password_hash"]
            email = str(user["email"]).strip().lower()
            name = str(user["display_name"] or "").strip() or email.partition("@")[0][:80] or "User"
            if not isinstance(stored_hash, str) or not stored_hash.startswith("scrypt$"):
                cursor.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (hash_password(str(stored_hash)), user["id"]),
                )
            if not user["display_name"]:
                cursor.execute(
                    "UPDATE users SET display_name = %s WHERE id = %s",
                    (name, user["id"]),
                )
            ensure_sqlite_account_mapping(
                int(user["id"]),
                email,
                name,
                float(user["monthly_budget"]),
            )

        connection.commit()
        cursor.close()

    migrate_sqlite_accounts_to_mysql()
    migrate_sqlite_expenses_to_mysql()


def migrate_sqlite_expenses_to_mysql() -> None:
    with closing(connect_db()) as sqlite_connection:
        rows = sqlite_connection.execute(
            """
            SELECT e.id, e.user_id, e.title, e.amount, e.category, e.date, e.notes, m.mysql_user_id
            FROM expenses AS e
            JOIN account_map AS m ON m.sqlite_user_id = e.user_id
            ORDER BY e.id
            """
        ).fetchall()

    if not rows:
        return

    with closing(connect_grocery_db()) as mysql_connection:
        cursor = mysql_connection.cursor(dictionary=True)
        for row in rows:
            cursor.execute(
                """
                SELECT id FROM expense_records
                WHERE source_sqlite_user_id = %s AND source_sqlite_id = %s
                """,
                (row["user_id"], row["id"]),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    """
                    INSERT INTO expense_records (
                        user_id, title, amount, category, date, notes,
                        purchased_at, source_sqlite_user_id, source_sqlite_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s)
                    """,
                    (
                        row["mysql_user_id"],
                        row["title"],
                        row["amount"],
                        row["category"],
                        row["date"],
                        row["notes"] or "",
                        row["user_id"],
                        row["id"],
                    ),
                )
        mysql_connection.commit()
        cursor.close()


def ensure_sqlite_account_mapping(
    mysql_user_id: int,
    email: str,
    display_name: str,
    monthly_budget: float = 0.0,
) -> int:
    with closing(connect_db()) as connection, connection:
        mapped = connection.execute(
            "SELECT sqlite_user_id FROM account_map WHERE mysql_user_id = ?",
            (mysql_user_id,),
        ).fetchone()
        if mapped is not None:
            return int(mapped["sqlite_user_id"])

        shadow = connection.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,),
        ).fetchone() if email else None
        if shadow is None:
            shadow_email = f"mysql-user-{mysql_user_id}@expense-tracker.invalid"
            shadow = connection.execute(
                "SELECT id FROM users WHERE email = ?",
                (shadow_email,),
            ).fetchone()
        if shadow is None:
            shadow_email = f"mysql-user-{mysql_user_id}@expense-tracker.invalid"
            cursor = connection.execute(
                """
                INSERT INTO users (email, display_name, password_hash, monthly_budget)
                VALUES (?, ?, ?, ?)
                """,
                (shadow_email, display_name or email.partition("@")[0], hash_password(secrets.token_urlsafe(32)), monthly_budget),
            )
            sqlite_user_id = int(cursor.lastrowid)
        else:
            sqlite_user_id = int(shadow["id"])
        connection.execute(
            "INSERT INTO account_map (mysql_user_id, sqlite_user_id) VALUES (?, ?)",
            (mysql_user_id, sqlite_user_id),
        )
        return sqlite_user_id


def migrate_sqlite_accounts_to_mysql() -> None:
    with closing(connect_db()) as sqlite_connection, sqlite_connection:
        legacy_users = [
            dict(row)
            for row in sqlite_connection.execute(
                "SELECT id, email, display_name, password_hash, monthly_budget FROM users WHERE email NOT LIKE 'mysql-user-%@expense-tracker.invalid'"
            ).fetchall()
        ]
        for legacy_user in legacy_users:
            if not str(legacy_user["password_hash"]).startswith("scrypt$"):
                legacy_hash = hash_password(str(legacy_user["password_hash"]))
                sqlite_connection.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (legacy_hash, legacy_user["id"]),
                )
                legacy_user["password_hash"] = legacy_hash

    with closing(connect_grocery_db()) as mysql_connection:
        cursor = mysql_connection.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users")
        mysql_user_ids = [int(user["id"]) for user in cursor.fetchall()]
        with closing(connect_db()) as sqlite_connection, sqlite_connection:
            if mysql_user_ids:
                placeholders = ", ".join("?" for _ in mysql_user_ids)
                sqlite_connection.execute(
                    f"DELETE FROM account_map WHERE mysql_user_id NOT IN ({placeholders})",
                    mysql_user_ids,
                )
            else:
                sqlite_connection.execute("DELETE FROM account_map")

        for legacy_user in legacy_users:
            email = str(legacy_user["email"]).strip().lower()
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            existing = cursor.fetchone()
            if existing is None:
                cursor.execute(
                    """
                    INSERT INTO users (email, password_hash, display_name, monthly_budget)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        email,
                        legacy_user["password_hash"],
                        legacy_user["display_name"],
                        legacy_user["monthly_budget"],
                    ),
                )
                mysql_user_id = int(cursor.lastrowid)
            else:
                mysql_user_id = int(existing["id"])
            ensure_sqlite_account_mapping(
                mysql_user_id,
                email,
                str(legacy_user["display_name"]),
                float(legacy_user["monthly_budget"]),
            )
        mysql_connection.commit()
        cursor.close()


def json_error(message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$16384$8$1${}${}".format(
        salt.hex(),
        derived_key.hex(),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, n_value, r_value, p_value, salt_hex, expected_hex = stored_hash.split("$")
        if algorithm != "scrypt":
            return False
        derived_key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_value),
            r=int(r_value),
            p=int(p_value),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived_key.hex(), expected_hex)


def issue_session(connection: Any, user_id: int) -> str:
    cursor = connection.cursor()
    cursor.execute("DELETE FROM auth_sessions WHERE expires_at <= %s", (int(time.time()),))
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    cursor.execute(
        "INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
        (token_hash, user_id, int(time.time()) + SESSION_LIFETIME_SECONDS),
    )
    cursor.close()
    return token


def authenticated_user_id(authorization: str | None) -> int | None:
    authorization = authorization or ""
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        return None

    token_hash = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
    with closing(connect_grocery_db()) as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id FROM auth_sessions WHERE token_hash = %s AND expires_at > %s",
            (token_hash, int(time.time())),
        )
        row = cursor.fetchone()
        cursor.close()
    if row is None:
        return None
    user_id = int(row["user_id"])
    sqlite_user_id = ensure_sqlite_account_mapping(
        user_id,
        "",
        "",
    )
    del sqlite_user_id
    return user_id


def expense_payload(data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    title = data.get("title")
    amount = data.get("amount")
    category = data.get("category")
    expense_date = data.get("date")
    notes = data.get("notes", "")

    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 100:
        return None, "Title is required and must be 100 characters or fewer."
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return None, "Amount must be a positive number."
    if not math.isfinite(amount) or amount <= 0:
        return None, "Amount must be a positive number."
    if not isinstance(category, str) or category not in EXPENSE_CATEGORIES:
        return None, "Choose a valid expense category."
    if not isinstance(expense_date, str):
        return None, "Date must use the YYYY-MM-DD format."
    try:
        normalized_date = date.fromisoformat(expense_date).isoformat()
    except ValueError:
        return None, "Date must use the YYYY-MM-DD format."
    if not isinstance(notes, str) or len(notes) > 500:
        return None, "Notes must be 500 characters or fewer."

    return {
        "title": title.strip(),
        "amount": float(amount),
        "category": category,
        "date": normalized_date,
        "notes": notes.strip(),
    }, None


def grocery_payload(data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    name = data.get("name")
    quantity = data.get("quantity", 1)
    budget = data.get("budget", 0)
    purchased = data.get("purchased", False)

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        return None, "Item name is required and must be 100 characters or fewer."
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1 or quantity > 999:
        return None, "Quantity must be a whole number from 1 to 999."
    if isinstance(budget, bool) or not isinstance(budget, (int, float)):
        return None, "Budget must be a non-negative number."
    if not math.isfinite(budget) or budget < 0:
        return None, "Budget must be a non-negative number."
    if not isinstance(purchased, bool):
        return None, "Purchased must be true or false."

    return {
        "name": name.strip(),
        "quantity": quantity,
        "budget": float(budget),
        "purchased": purchased,
    }, None


def create_app() -> FastAPI:
    init_db()
    application = FastAPI(title="Expense Tracker API")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    auth_store_ready = False

    def ensure_auth_store() -> None:
        nonlocal auth_store_ready
        if not auth_store_ready:
            init_mysql_auth_db()
            auth_store_ready = True

    @application.middleware("http")
    async def initialize_api_storage(request: Request, call_next: Any) -> Any:
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            try:
                ensure_auth_store()
            except MySQLError:
                logging.getLogger(__name__).exception("Could not initialize MySQL storage.")
                return json_error("MySQL database is unavailable. Check your database settings.", 503)
        return await call_next(request)

    @application.exception_handler(MySQLError)
    async def handle_mysql_error(_request: Any, error: MySQLError) -> JSONResponse:
        del error
        logging.getLogger(__name__).exception("MySQL request failed.")
        return json_error("MySQL database is unavailable. Check your database settings.", 503)

    @application.get("/")
    def root() -> dict[str, object]:
        return {
            "message": "Expense Tracker API is running.",
            "frontend": "http://localhost:4200",
            "api_base": "/api",
            "endpoints": ["/api/auth", "/api/expenses", "/api/groceries"],
        }

    @application.get("/api")
    @application.get("/api/")
    def api_root() -> dict[str, object]:
        return {
            "message": "Expense Tracker API",
            "endpoints": [
                "/api/auth/register",
                "/api/auth/login",
                "/api/auth/logout",
                "/api/expenses",
                "/api/groceries",
            ],
        }

    @application.post("/api/auth/register", status_code=201)
    def register(data: dict[str, Any] | None = Body(default=None)) -> Any:
        if data is None:
            return json_error("A JSON request body is required.", 400)
        email = data.get("email")
        display_name = data.get("name")
        password = data.get("password")
        if not isinstance(email, str) or len(email.strip()) > 254 or not EMAIL_PATTERN.fullmatch(email.strip()):
            return json_error("Enter a valid email address.", 400)
        if not isinstance(display_name, str) or not display_name.strip() or len(display_name.strip()) > 80:
            return json_error("Name is required and must be 80 characters or fewer.", 400)
        if not isinstance(password, str) or not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
            return json_error(
                f"Password must be between {PASSWORD_MIN_LENGTH} and {PASSWORD_MAX_LENGTH} characters.",
                400,
            )
        try:
            ensure_auth_store()
            normalized_email = email.strip().lower()
            with closing(connect_grocery_db()) as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT id FROM users WHERE email = %s", (normalized_email,))
                if cursor.fetchone() is not None:
                    cursor.close()
                    return json_error("An account with this email already exists.", 409)
                cursor.execute(
                    "INSERT INTO users (email, display_name, password_hash, monthly_budget) "
                    "VALUES (%s, %s, %s, %s)",
                    (normalized_email, display_name.strip(), hash_password(password), 0.0),
                )
                user_id = int(cursor.lastrowid)
                ensure_sqlite_account_mapping(user_id, normalized_email, display_name.strip())
                token = issue_session(connection, user_id)
                connection.commit()
                cursor.close()
        except MySQLError as error:
            if getattr(error, "errno", None) == 1062:
                return json_error("An account with this email already exists.", 409)
            logging.getLogger(__name__).exception("Could not register account in MySQL.")
            return json_error("Account database is unavailable. Check your MySQL settings.", 503)
        except sqlite3.IntegrityError:
            return json_error("An account with this email already exists.", 409)
        return {
            "token": token,
            "user": {
                "id": user_id,
                "email": normalized_email,
                "name": display_name.strip(),
                "monthlyBudget": 0.0,
            },
        }

    @application.post("/api/auth/login")
    def login(data: dict[str, Any] | None = Body(default=None)) -> Any:
        if data is None:
            return json_error("A JSON request body is required.", 400)
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            return json_error("Email and password are required.", 400)
        try:
            ensure_auth_store()
            with closing(connect_grocery_db()) as connection:
                cursor = connection.cursor(dictionary=True)
                cursor.execute(
                    "SELECT id, email, display_name, password_hash, monthly_budget "
                    "FROM users WHERE email = %s",
                    (email.strip().lower(),),
                )
                user = cursor.fetchone()
                if user is None or not verify_password(password, user["password_hash"]):
                    cursor.close()
                    return json_error("Email or password is incorrect.", 401)
                user_id = int(user["id"])
                token = issue_session(connection, user_id)
                connection.commit()
                cursor.close()
        except MySQLError:
            logging.getLogger(__name__).exception("Could not authenticate account with MySQL.")
            return json_error("Account database is unavailable. Check your MySQL settings.", 503)
        return {
            "token": token,
            "user": {
                "id": user_id,
                "email": user["email"],
                "name": user["display_name"],
                "monthlyBudget": float(user["monthly_budget"]),
            },
        }

    @application.post("/api/auth/logout")
    def logout(authorization: str | None = Header(default=None, alias="Authorization")) -> Any:
        try:
            ensure_auth_store()
        except MySQLError:
            return json_error("Account database is unavailable. Check your MySQL settings.", 503)
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        token = (authorization or "").partition(" ")[2].strip()
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with closing(connect_grocery_db()) as connection:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (token_hash,))
            connection.commit()
            cursor.close()
        return {"message": "Signed out successfully."}

    @application.get("/api/auth/me")
    def current_user(authorization: str | None = Header(default=None, alias="Authorization")) -> Any:
        try:
            ensure_auth_store()
        except MySQLError:
            return json_error("Account database is unavailable. Check your MySQL settings.", 503)
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        with closing(connect_grocery_db()) as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, email, display_name, monthly_budget FROM users WHERE id = %s",
                (user_id,),
            )
            user = cursor.fetchone()
            cursor.close()
        if user is None:
            return json_error("Account not found.", 401)
        return {
            "id": user["id"],
            "email": user["email"],
            "name": user["display_name"],
            "monthlyBudget": float(user["monthly_budget"]),
        }

    @application.put("/api/auth/me")
    def update_current_user(
        data: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> Any:
        try:
            ensure_auth_store()
        except MySQLError:
            return json_error("Account database is unavailable. Check your MySQL settings.", 503)
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        if data is None:
            return json_error("A JSON request body is required.", 400)
        budget = data.get("monthlyBudget")
        if isinstance(budget, bool) or not isinstance(budget, (int, float)):
            return json_error("Monthly budget must be a positive number.", 400)
        if not math.isfinite(budget) or budget <= 0 or budget > 100_000_000:
            return json_error("Monthly budget must be between 0.01 and 100,000,000.", 400)
        with closing(connect_grocery_db()) as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "UPDATE users SET monthly_budget = %s WHERE id = %s",
                (float(budget), user_id),
            )
            cursor.execute(
                "SELECT id, email, display_name, monthly_budget FROM users WHERE id = %s",
                (user_id,),
            )
            user = cursor.fetchone()
            connection.commit()
            cursor.close()
        return {
            "id": user["id"],
            "email": user["email"],
            "name": user["display_name"],
            "monthlyBudget": float(user["monthly_budget"]),
        }

    @application.get("/api/expenses")
    def get_expenses(authorization: str | None = Header(default=None, alias="Authorization")) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        with closing(connect_grocery_db()) as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, title, CAST(amount AS DOUBLE) AS amount, category, date, notes, "
                "purchased_at AS purchasedAt FROM expense_records WHERE user_id = %s "
                "ORDER BY date DESC, id DESC",
                (user_id,),
            )
            rows = cursor.fetchall()
            cursor.close()
        return rows

    @application.get("/api/expenses/{expense_id}")
    def get_expense(expense_id: int, authorization: str | None = Header(default=None, alias="Authorization")) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        with closing(connect_grocery_db()) as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, title, CAST(amount AS DOUBLE) AS amount, category, date, notes, "
                "purchased_at AS purchasedAt FROM expense_records WHERE id = %s AND user_id = %s",
                (expense_id, user_id),
            )
            row = cursor.fetchone()
            cursor.close()
        if row is None:
            return json_error("Expense not found.", 404)
        return row

    @application.post("/api/expenses", status_code=201)
    def add_expense(
        data: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        if data is None:
            return json_error("A JSON request body is required.", 400)
        payload, error = expense_payload(data)
        if error is not None or payload is None:
            return json_error(error or "Invalid expense data.", 400)
        with closing(connect_grocery_db()) as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "INSERT INTO expense_records (user_id, title, amount, category, date, notes, purchased_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)",
                (user_id, payload["title"], payload["amount"], payload["category"], payload["date"], payload["notes"]),
            )
            expense_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT purchased_at AS purchasedAt FROM expense_records WHERE id = %s AND user_id = %s",
                (expense_id, user_id),
            )
            record = cursor.fetchone()
            connection.commit()
            cursor.close()
        return {"id": expense_id, **payload, **record}

    @application.put("/api/expenses/{expense_id}")
    def update_expense(
        expense_id: int,
        data: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        if data is None:
            return json_error("A JSON request body is required.", 400)
        payload, error = expense_payload(data)
        if error is not None or payload is None:
            return json_error(error or "Invalid expense data.", 400)
        with closing(connect_grocery_db()) as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "UPDATE expense_records SET title = %s, amount = %s, category = %s, date = %s, notes = %s "
                "WHERE id = %s AND user_id = %s",
                (payload["title"], payload["amount"], payload["category"], payload["date"], payload["notes"], expense_id, user_id),
            )
            cursor.execute(
                "SELECT purchased_at AS purchasedAt FROM expense_records WHERE id = %s AND user_id = %s",
                (expense_id, user_id),
            )
            record = cursor.fetchone()
            connection.commit()
            cursor.close()
        if record is None:
            return json_error("Expense not found.", 404)
        return {"id": expense_id, **payload, **record}

    @application.patch("/api/expenses/{expense_id}")
    def patch_expense(
        expense_id: int,
        data: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        if data is None:
            return json_error("A JSON request body is required.", 400)
        with closing(connect_grocery_db()) as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT title, CAST(amount AS DOUBLE) AS amount, category, date, notes "
                "FROM expense_records WHERE id = %s AND user_id = %s",
                (expense_id, user_id),
            )
            existing = cursor.fetchone()
            if existing is None:
                cursor.close()
                return json_error("Expense not found.", 404)
            payload, error = expense_payload({**existing, **data})
            if error is not None or payload is None:
                cursor.close()
                return json_error(error or "Invalid expense data.", 400)
            cursor.execute(
                "UPDATE expense_records SET title = %s, amount = %s, category = %s, date = %s, notes = %s "
                "WHERE id = %s AND user_id = %s",
                (payload["title"], payload["amount"], payload["category"], payload["date"], payload["notes"], expense_id, user_id),
            )
            cursor.execute(
                "SELECT purchased_at AS purchasedAt FROM expense_records WHERE id = %s AND user_id = %s",
                (expense_id, user_id),
            )
            record = cursor.fetchone()
            connection.commit()
            cursor.close()
        return {"id": expense_id, **payload, **record}

    @application.delete("/api/expenses/{expense_id}")
    def delete_expense(expense_id: int, authorization: str | None = Header(default=None, alias="Authorization")) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        with closing(connect_grocery_db()) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM expense_records WHERE id = %s AND user_id = %s",
                (expense_id, user_id),
            )
            deleted_count = cursor.rowcount
            connection.commit()
            cursor.close()
        if deleted_count == 0:
            return json_error("Expense not found.", 404)
        return {"message": "Expense deleted successfully.", "id": expense_id}

    @application.get("/api/groceries")
    def get_groceries(authorization: str | None = Header(default=None, alias="Authorization")) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        try:
            with closing(connect_grocery_db()) as connection:
                cursor = connection.cursor(dictionary=True)
                cursor.execute(
                    "SELECT id, item AS name, quantity, CAST(unit_price AS DOUBLE) AS budget, purchased, "
                    "created_at AS createdAt, purchased_at AS purchasedAt FROM grocerylist_db "
                    "WHERE user_id = %s ORDER BY purchased ASC, id DESC",
                    (user_id,),
                )
                rows = cursor.fetchall()
                cursor.close()
        except MySQLError:
            return json_error("Grocery database is unavailable. Check your MySQL settings.", 503)
        return [{**dict(row), "purchased": bool(row["purchased"])} for row in rows]

    @application.get("/api/purchase-history")
    def get_purchase_history(authorization: str | None = Header(default=None, alias="Authorization")) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        with closing(connect_grocery_db()) as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, product_name AS productName, category, quantity, "
                "CAST(unit_price AS DOUBLE) AS unitPrice, CAST(expense AS DOUBLE) AS expense, "
                "date AS purchasedAt FROM purchase_history WHERE user_id = %s "
                "ORDER BY date DESC, id DESC",
                (user_id,),
            )
            rows = cursor.fetchall()
            cursor.close()
        return rows

    @application.delete("/api/purchase-history/{history_id}")
    def delete_purchase_history(
        history_id: int,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        try:
            with closing(connect_grocery_db()) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    "DELETE FROM purchase_history WHERE id = %s AND user_id = %s",
                    (history_id, user_id),
                )
                deleted_count = cursor.rowcount
                connection.commit()
                cursor.close()
        except MySQLError:
            return json_error("Grocery database is unavailable. Check your MySQL settings.", 503)
        if deleted_count == 0:
            return json_error("Purchased history item not found.", 404)
        return {"message": "Purchased history item deleted successfully.", "id": history_id}

    @application.post("/api/groceries", status_code=201)
    def add_grocery(
        data: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        if data is None:
            return json_error("A JSON request body is required.", 400)
        payload, error = grocery_payload(data)
        if error is not None or payload is None:
            return json_error(error or "Invalid grocery item.", 400)
        try:
            with closing(connect_grocery_db()) as connection:
                cursor = connection.cursor(dictionary=True)
                cursor.execute(
                    "INSERT INTO grocerylist_db (user_id, item, quantity, unit_price, purchased) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (user_id, payload["name"], payload["quantity"], payload["budget"], int(payload["purchased"])),
                )
                item_id = int(cursor.lastrowid)
                cursor.execute(
                    "SELECT created_at AS createdAt, purchased_at AS purchasedAt "
                    "FROM grocerylist_db WHERE id = %s AND user_id = %s",
                    (item_id, user_id),
                )
                timestamps = cursor.fetchone()
                connection.commit()
                cursor.close()
        except MySQLError:
            return json_error("Grocery database is unavailable. Check your MySQL settings.", 503)
        return {"id": item_id, **payload, **timestamps}

    def save_grocery_update(
        item_id: int,
        user_id: int,
        data: dict[str, Any],
        partial: bool,
    ) -> Any:
        try:
            with closing(connect_grocery_db()) as connection:
                cursor = connection.cursor(dictionary=True)
                cursor.execute(
                    "SELECT item, quantity, unit_price, purchased, purchased_at "
                    "FROM grocerylist_db WHERE id = %s AND user_id = %s FOR UPDATE",
                    (item_id, user_id),
                )
                existing = cursor.fetchone()
                if existing is None:
                    cursor.close()
                    return json_error("Grocery item not found.", 404)
                payload_data = {
                    "name": existing["item"],
                    "quantity": existing["quantity"],
                    "budget": float(existing["unit_price"]),
                    "purchased": bool(existing["purchased"]),
                }
                if partial:
                    payload_data.update(data)
                else:
                    payload_data = data
                payload, error = grocery_payload(payload_data)
                if error is not None or payload is None:
                    cursor.close()
                    return json_error(error or "Invalid grocery item.", 400)
                cursor.execute(
                    "UPDATE grocerylist_db SET item = %s, quantity = %s, unit_price = %s, purchased = %s, "
                    "purchased_at = CASE WHEN %s = 1 THEN COALESCE(purchased_at, CURRENT_TIMESTAMP) ELSE NULL END "
                    "WHERE id = %s AND user_id = %s",
                    (
                        payload["name"],
                        payload["quantity"],
                        payload["budget"],
                        int(payload["purchased"]),
                        int(payload["purchased"]),
                        item_id,
                        user_id,
                    ),
                )
                if not payload["purchased"] and bool(existing["purchased"]):
                    cursor.execute(
                        "DELETE FROM purchase_history WHERE user_id = %s AND grocery_item_id = %s",
                        (user_id, item_id),
                    )
                if payload["purchased"] and not bool(existing["purchased"]):
                    cursor.execute(
                        "INSERT INTO purchase_history "
                        "(user_id, grocery_item_id, product_name, category, quantity, unit_price, expense) "
                        "VALUES (%s, %s, %s, 'Groceries', %s, %s, %s)",
                        (
                            user_id,
                            item_id,
                            payload["name"],
                            payload["quantity"],
                            payload["budget"],
                            round(payload["quantity"] * payload["budget"], 2),
                        ),
                    )
                cursor.execute(
                    "SELECT created_at AS createdAt, purchased_at AS purchasedAt "
                    "FROM grocerylist_db WHERE id = %s AND user_id = %s",
                    (item_id, user_id),
                )
                timestamps = cursor.fetchone()
                connection.commit()
                cursor.close()
        except MySQLError:
            return json_error("Grocery database is unavailable. Check your MySQL settings.", 503)
        return {"id": item_id, **payload, **timestamps}

    @application.put("/api/groceries/{item_id}")
    def update_grocery(
        item_id: int,
        data: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        if data is None:
            return json_error("A JSON request body is required.", 400)
        return save_grocery_update(item_id, user_id, data, partial=False)

    @application.patch("/api/groceries/{item_id}")
    def patch_grocery(
        item_id: int,
        data: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        if data is None:
            return json_error("A JSON request body is required.", 400)
        return save_grocery_update(item_id, user_id, data, partial=True)

    @application.delete("/api/groceries/{item_id}")
    def delete_grocery(item_id: int, authorization: str | None = Header(default=None, alias="Authorization")) -> Any:
        user_id = authenticated_user_id(authorization)
        if user_id is None:
            return json_error("Sign in to continue.", 401)
        try:
            with closing(connect_grocery_db()) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    "DELETE FROM grocerylist_db WHERE id = %s AND user_id = %s",
                    (item_id, user_id),
                )
                deleted_count = cursor.rowcount
                connection.commit()
                cursor.close()
        except MySQLError:
            return json_error("Grocery database is unavailable. Check your MySQL settings.", 503)
        if deleted_count == 0:
            return json_error("Grocery item not found.", 404)
        return {"message": "Grocery item deleted successfully.", "id": item_id}

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.app.home.main:app", host="127.0.0.1", port=8000, reload=False)
