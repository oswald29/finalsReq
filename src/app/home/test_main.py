import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

import main
from fastapi.testclient import TestClient


class FastAPITestResponse:
    def __init__(self, response: object) -> None:
        self._response = response

    @property
    def status_code(self) -> int:
        return int(getattr(self._response, "status_code"))

    def get_json(self) -> object:
        return getattr(self._response, "json")()

    def __getattr__(self, name: str) -> object:
        return getattr(self._response, name)


class FastAPITestClient:
    def __init__(self, app: object) -> None:
        self._client = TestClient(app)

    def _wrap(self, response: object) -> FastAPITestResponse:
        return FastAPITestResponse(response)

    def get(self, *args: object, **kwargs: object) -> FastAPITestResponse:
        return self._wrap(self._client.get(*args, **kwargs))

    def post(self, *args: object, **kwargs: object) -> FastAPITestResponse:
        return self._wrap(self._client.post(*args, **kwargs))

    def put(self, *args: object, **kwargs: object) -> FastAPITestResponse:
        return self._wrap(self._client.put(*args, **kwargs))

    def patch(self, *args: object, **kwargs: object) -> FastAPITestResponse:
        return self._wrap(self._client.patch(*args, **kwargs))

    def delete(self, *args: object, **kwargs: object) -> FastAPITestResponse:
        return self._wrap(self._client.delete(*args, **kwargs))


class MySQLConnectionTests(unittest.TestCase):
    def test_creates_configured_database_if_it_is_missing(self) -> None:
        missing_database = main.mysql.connector.errors.ProgrammingError(
            msg="Unknown database",
            errno=1049,
            sqlstate="42000",
        )
        server_connection = MagicMock()
        application_connection = MagicMock()

        with patch.object(
            main.mysql.connector,
            "connect",
            side_effect=[missing_database, server_connection, application_connection],
        ) as connect:
            result = main.connect_grocery_db()

        self.assertIs(result, application_connection)
        first_config = connect.call_args_list[0].kwargs
        server_config = connect.call_args_list[1].kwargs
        final_config = connect.call_args_list[2].kwargs
        self.assertIn("database", first_config)
        self.assertNotIn("database", server_config)
        self.assertEqual(final_config, first_config)
        server_connection.cursor.return_value.execute.assert_called_once_with(
            f"CREATE DATABASE IF NOT EXISTS `{main.MYSQL_CONFIG['database']}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )


class SQLiteMySQLCursor:
    def __init__(self, cursor: sqlite3.Cursor, dictionary: bool) -> None:
        self.cursor = cursor
        self.dictionary = dictionary
        self.special_rows: list[dict[str, object]] | None = None

    def execute(self, query: str, parameters: tuple[object, ...] = ()) -> None:
        normalized_query = query.strip().upper()
        if normalized_query.startswith("SHOW COLUMNS FROM "):
            table_name = normalized_query.removeprefix("SHOW COLUMNS FROM ").lower()
            self.cursor.execute(f"PRAGMA table_info({table_name})")
            self.special_rows = [
                {
                    "Field": row["name"],
                    "Type": row["type"],
                    "Null": "NO" if row["notnull"] else "YES",
                    "Default": row["dflt_value"],
                }
                for row in self.cursor.fetchall()
            ]
            return
        if normalized_query.startswith("SHOW TABLES LIKE "):
            table_name = query.split("'", 2)[1]
            self.cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            )
            self.special_rows = (
                [{"table": row["name"]} for row in self.cursor.fetchall()]
            )
            return
        if normalized_query.startswith("CREATE TABLE GROCERYLIST_DB "):
            self.cursor.execute(
                """
                CREATE TABLE grocerylist_db (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    unit_price REAL NOT NULL DEFAULT 0,
                    user_id INTEGER,
                    purchased INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    purchased_at TEXT
                )
                """
            )
            self.special_rows = None
            return
        if normalized_query.startswith("CREATE TABLE EXPENSE_RECORDS "):
            self.cursor.execute(
                """
                CREATE TABLE expense_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    date TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    purchased_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    source_sqlite_user_id INTEGER,
                    source_sqlite_id INTEGER,
                    UNIQUE(source_sqlite_user_id, source_sqlite_id)
                )
                """
            )
            self.special_rows = None
            return
        if normalized_query.startswith("CREATE TABLE PURCHASE_HISTORY "):
            self.cursor.execute(
                """
                CREATE TABLE purchase_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    grocery_item_id INTEGER,
                    product_name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'Groceries',
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    expense REAL NOT NULL,
                    date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.special_rows = None
            return
        if normalized_query.startswith("ALTER TABLE PURCHASE_HISTORY MODIFY COLUMN DATE "):
            self.special_rows = None
            return
        if normalized_query.startswith("ALTER TABLE USERS ALTER COLUMN MONTHLY_BUDGET SET DEFAULT "):
            self.special_rows = None
            return
        if normalized_query.startswith("ALTER TABLE GROCERYLIST_DB ADD COLUMN CREATED_AT "):
            self.cursor.execute("ALTER TABLE grocerylist_db ADD COLUMN created_at TEXT")
            self.special_rows = None
            return
        if normalized_query.startswith("ALTER TABLE GROCERYLIST_DB CHANGE COLUMN "):
            columns = query.replace("`", "").split()
            self.cursor.execute(
                f"ALTER TABLE grocerylist_db RENAME COLUMN {columns[5]} TO {columns[6]}"
            )
            self.special_rows = None
            return
        self.special_rows = None
        self.cursor.execute(query.replace("%s", "?").replace(" FOR UPDATE", ""), parameters)

    def fetchall(self) -> list[dict[str, object] | tuple[object, ...]]:
        if self.special_rows is not None:
            rows = self.special_rows
            self.special_rows = None
            return rows
        rows = self.cursor.fetchall()
        return [dict(row) if self.dictionary else tuple(row) for row in rows]

    def fetchone(self) -> dict[str, object] | tuple[object, ...] | None:
        if self.special_rows is not None:
            rows = self.special_rows
            self.special_rows = None
            return rows[0] if rows else None
        row = self.cursor.fetchone()
        return (dict(row) if self.dictionary else tuple(row)) if row is not None else None

    @property
    def rowcount(self) -> int:
        return self.cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self.cursor.lastrowid

    def close(self) -> None:
        self.cursor.close()


class SQLiteMySQLConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def cursor(self, dictionary: bool = False) -> SQLiteMySQLCursor:
        return SQLiteMySQLCursor(self.connection.cursor(), dictionary)

    def commit(self) -> None:
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


class ExpenseApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = main.DB_NAME
        self.original_grocery_connection = main.connect_grocery_db
        main.DB_NAME = Path(self.temporary_directory.name) / "test-expenses.db"
        self.grocery_database = Path(self.temporary_directory.name) / "test-groceries.db"
        with closing(sqlite3.connect(self.grocery_database)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE grocerylist_db (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    item TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    purchased INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    purchased_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE expense_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    date TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    purchased_at TEXT,
                    source_sqlite_user_id INTEGER,
                    source_sqlite_id INTEGER,
                    UNIQUE(source_sqlite_user_id, source_sqlite_id)
                )
                """
            )
            connection.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                ("legacy@example.com", "legacy-password-123"),
            )
        main.connect_grocery_db = self.connect_test_grocery_db
        self.app = main.create_app()
        self.client = FastAPITestClient(self.app)

    def tearDown(self) -> None:
        main.DB_NAME = self.original_database
        main.connect_grocery_db = self.original_grocery_connection
        self.temporary_directory.cleanup()

    def connect_test_grocery_db(self) -> SQLiteMySQLConnection:
        connection = sqlite3.connect(self.grocery_database)
        connection.row_factory = sqlite3.Row
        return SQLiteMySQLConnection(connection)

    def register(self, email: str, name: str = "Test User") -> tuple[dict[str, str], dict[str, object]]:
        response = self.client.post(
            "/api/auth/register",
            json={"name": name, "email": email, "password": "secure-pass-123"},
        )
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        return {"Authorization": f"Bearer {body['token']}"}, body

    def test_registration_hashes_password_and_login_returns_a_token(self) -> None:
        with closing(sqlite3.connect(main.DB_NAME)) as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO users (email, display_name, password_hash)
                VALUES (?, ?, ?)
                """,
                ("sqlite-legacy@example.com", "SQLite Legacy", "sqlite-legacy-password"),
            )
            connection.execute(
                """
                INSERT INTO expenses (user_id, title, amount, category, date, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cursor.lastrowid, "Older meal", 75, "Food", "2026-11-06", ""),
            )

        headers, body = self.register("user@example.com")
        self.assertIn("token", body)
        self.assertEqual(body["user"]["email"], "user@example.com")
        self.assertEqual(body["user"]["monthlyBudget"], 0)
        self.assertNotIn("password_hash", body["user"])

        with closing(sqlite3.connect(self.grocery_database)) as connection, connection:
            connection.row_factory = sqlite3.Row
            stored_hash = connection.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("user@example.com",),
            ).fetchone()[0]
        self.assertNotEqual(stored_hash, "secure-pass-123")
        self.assertTrue(stored_hash.startswith("scrypt$"))
        self.assertTrue(main.verify_password("secure-pass-123", stored_hash))
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).get_json()["monthlyBudget"], 0)
        with closing(sqlite3.connect(self.grocery_database)) as connection, connection:
            connection.row_factory = sqlite3.Row
            migrated_hash = connection.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("legacy@example.com",),
            ).fetchone()["password_hash"]
        self.assertTrue(migrated_hash.startswith("scrypt$"))
        self.assertTrue(main.verify_password("legacy-password-123", migrated_hash))
        migrated_login = self.client.post(
            "/api/auth/login",
            json={"email": "legacy@example.com", "password": "legacy-password-123"},
        )
        self.assertEqual(migrated_login.status_code, 200)

        with closing(sqlite3.connect(self.grocery_database)) as connection, connection:
            connection.row_factory = sqlite3.Row
            sqlite_migrated_hash = connection.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("sqlite-legacy@example.com",),
            ).fetchone()["password_hash"]
        self.assertTrue(sqlite_migrated_hash.startswith("scrypt$"))
        self.assertTrue(main.verify_password("sqlite-legacy-password", sqlite_migrated_hash))
        sqlite_legacy_login = self.client.post(
            "/api/auth/login",
            json={"email": "sqlite-legacy@example.com", "password": "sqlite-legacy-password"},
        )
        self.assertEqual(sqlite_legacy_login.status_code, 200)
        sqlite_legacy_token = sqlite_legacy_login.get_json()["token"]
        migrated_expenses = self.client.get(
            "/api/expenses",
            headers={"Authorization": f"Bearer {sqlite_legacy_token}"},
        )
        self.assertEqual(migrated_expenses.get_json()[0]["title"], "Older meal")
        self.assertIsNone(migrated_expenses.get_json()[0]["purchasedAt"])

        login = self.client.post(
            "/api/auth/login",
            json={"email": "USER@example.com", "password": "secure-pass-123"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("token", login.get_json())

    def test_sqlite_account_migration_removes_mappings_for_deleted_mysql_users(self) -> None:
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        with closing(sqlite3.connect(main.DB_NAME)) as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO users (email, display_name, password_hash, monthly_budget)
                VALUES (?, ?, ?, ?)
                """,
                ("retained@example.com", "Retained User", main.hash_password("secure-pass-123"), 0),
            )
            sqlite_user_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO account_map (mysql_user_id, sqlite_user_id) VALUES (?, ?)",
                (999, sqlite_user_id),
            )

        main.migrate_sqlite_accounts_to_mysql()

        with closing(sqlite3.connect(main.DB_NAME)) as connection:
            mapped_user_id = connection.execute(
                "SELECT sqlite_user_id FROM account_map WHERE mysql_user_id = 2"
            ).fetchone()[0]
            stale_mapping = connection.execute(
                "SELECT 1 FROM account_map WHERE mysql_user_id = 999"
            ).fetchone()
        self.assertEqual(mapped_user_id, sqlite_user_id)
        self.assertIsNone(stale_mapping)

    def test_monthly_budget_is_saved_per_account(self) -> None:
        alice_headers, _ = self.register("budget-alice@example.com")
        bob_headers, _ = self.register("budget-bob@example.com")

        updated = self.client.put(
            "/api/auth/me",
            json={"monthlyBudget": 18500},
            headers=alice_headers,
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["monthlyBudget"], 18500)
        self.assertEqual(
            self.client.get("/api/auth/me", headers=bob_headers).get_json()["monthlyBudget"],
            0,
        )
        invalid = self.client.put(
            "/api/auth/me",
            json={"monthlyBudget": -10},
            headers=alice_headers,
        )
        self.assertEqual(invalid.status_code, 400)

    def test_expenses_are_private_and_crud_is_persisted(self) -> None:
        alice_headers, _ = self.register("alice@example.com", "Alice")
        bob_headers, _ = self.register("bob@example.com", "Bob")
        payload = {
            "title": "Lunch",
            "amount": 125.5,
            "category": "Food",
            "date": "2026-11-07",
            "notes": "Campus meal",
        }

        created = self.client.post("/api/expenses", json=payload, headers=alice_headers)
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.get_json()["purchasedAt"])
        expense_id = created.get_json()["id"]
        self.assertEqual(self.client.get("/api/expenses", headers=bob_headers).get_json(), [])
        self.assertEqual(
            self.client.get(f"/api/expenses/{expense_id}", headers=bob_headers).status_code,
            404,
        )
        self.assertEqual(
            self.client.put(
                f"/api/expenses/{expense_id}",
                json=payload,
                headers=bob_headers,
            ).status_code,
            404,
        )
        partial_update = self.client.patch(
            f"/api/expenses/{expense_id}",
            json={"title": "Updated by PATCH"},
            headers=alice_headers,
        )
        self.assertEqual(partial_update.status_code, 200)
        self.assertEqual(partial_update.get_json()["title"], "Updated by PATCH")
        self.assertEqual(partial_update.get_json()["amount"], payload["amount"])
        self.assertEqual(partial_update.get_json()["notes"], payload["notes"])
        self.assertEqual(
            self.client.patch(
                f"/api/expenses/{expense_id}",
                json={"amount": -1},
                headers=alice_headers,
            ).status_code,
            400,
        )
        unchanged = self.client.put(
            f"/api/expenses/{expense_id}",
            json=payload,
            headers=alice_headers,
        )
        self.assertEqual(unchanged.status_code, 200)
        self.assertEqual(
            self.client.delete(f"/api/expenses/{expense_id}", headers=bob_headers).status_code,
            404,
        )

        updated_payload = {**payload, "title": "Updated lunch", "amount": 140}
        updated = self.client.put(
            f"/api/expenses/{expense_id}",
            json=updated_payload,
            headers=alice_headers,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["title"], "Updated lunch")
        self.assertEqual(self.client.get("/api/expenses", headers=alice_headers).get_json()[0]["amount"], 140)
        self.assertEqual(
            self.client.delete(f"/api/expenses/{expense_id}", headers=alice_headers).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/expenses", headers=alice_headers).get_json(), [])

    def test_routes_require_a_valid_account_session(self) -> None:
        self.assertEqual(self.client.get("/api/expenses").status_code, 401)
        self.assertEqual(self.client.get("/api/purchase-history").status_code, 401)
        headers, _ = self.register("logout@example.com")
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/expenses", headers=headers).status_code, 401)

    def test_api_initialization_creates_missing_mysql_tables(self) -> None:
        with closing(sqlite3.connect(self.grocery_database)) as connection, connection:
            connection.execute("DROP TABLE grocerylist_db")
            connection.execute("DROP TABLE expense_records")
            connection.execute("DROP TABLE IF EXISTS purchase_history")

        restarted_app = main.create_app()
        response = FastAPITestClient(restarted_app).get("/api/groceries")

        self.assertEqual(response.status_code, 401)
        with closing(sqlite3.connect(self.grocery_database)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            grocery_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(grocerylist_db)")
            }
        self.assertIn("grocerylist_db", tables)
        self.assertIn("expense_records", tables)
        self.assertIn("purchase_history", tables)
        self.assertIn("purchased_at", grocery_columns)

    def test_api_upgrades_existing_purchase_history_table(self) -> None:
        with closing(sqlite3.connect(self.grocery_database)) as connection, connection:
            connection.execute("DROP TABLE IF EXISTS purchase_history")
            connection.execute(
                """
                CREATE TABLE purchase_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    expense REAL NOT NULL,
                    date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

        headers, _ = self.register("history-schema@example.com")
        restarted_app = main.create_app()
        restarted_client = FastAPITestClient(restarted_app)
        grocery = restarted_client.post(
            "/api/groceries",
            json={"name": "Burat", "quantity": 2, "budget": 20, "purchased": False},
            headers=headers,
        )

        self.assertEqual(grocery.status_code, 201)
        purchase = restarted_client.put(
            f"/api/groceries/{grocery.get_json()['id']}",
            json={"name": "Burat", "quantity": 2, "budget": 20, "purchased": True},
            headers=headers,
        )
        self.assertEqual(purchase.status_code, 200)

    def test_api_upgrades_legacy_grocery_columns(self) -> None:
        with closing(sqlite3.connect(self.grocery_database)) as connection, connection:
            connection.execute("DROP TABLE grocerylist_db")
            connection.execute(
                """
                CREATE TABLE grocerylist_db (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    Product_name TEXT NOT NULL,
                    Quantity INTEGER NOT NULL,
                    Unit_Price REAL NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO grocerylist_db (Product_name, Quantity, Unit_Price) VALUES (?, ?, ?)",
                ("Rice", 2, 20),
            )

        headers, _ = self.register("legacy-grocery@example.com")
        restarted_app = main.create_app()
        restarted_client = FastAPITestClient(restarted_app)
        created = restarted_client.post(
            "/api/groceries",
            json={"name": "Burat", "quantity": 2, "budget": 20, "purchased": False},
            headers=headers,
        )

        self.assertEqual(created.status_code, 201)
        persisted = restarted_client.get("/api/groceries", headers=headers)
        self.assertEqual(persisted.status_code, 200)
        self.assertEqual(len(persisted.get_json()), 1)
        self.assertEqual(persisted.get_json()[0]["name"], "Burat")

    def test_existing_purchased_groceries_are_backfilled_to_history(self) -> None:
        headers, _ = self.register("history-migration@example.com")
        payload = {"name": "Flour", "quantity": 2, "budget": 45, "purchased": False}
        created = self.client.post("/api/groceries", json=payload, headers=headers)
        item_id = created.get_json()["id"]
        updated = self.client.put(
            f"/api/groceries/{item_id}",
            json={**payload, "purchased": True},
            headers=headers,
        )
        self.assertEqual(updated.status_code, 200)

        with closing(sqlite3.connect(self.grocery_database)) as connection, connection:
            connection.execute("DROP TABLE purchase_history")

        restarted_client = FastAPITestClient(main.create_app())
        history = restarted_client.get("/api/purchase-history", headers=headers)

        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.get_json()), 1)
        self.assertEqual(history.get_json()[0]["productName"], "Flour")
        self.assertEqual(history.get_json()[0]["expense"], 90)

    def test_invalid_expense_data_and_duplicate_account_are_rejected(self) -> None:
        headers, _ = self.register("duplicate@example.com")
        duplicate = self.client.post(
            "/api/auth/register",
            json={"name": "Duplicate", "email": "DUPLICATE@example.com", "password": "secure-pass-123"},
        )
        self.assertEqual(duplicate.status_code, 409)

        invalid_expense = self.client.post(
            "/api/expenses",
            json={
                "title": "Bad amount",
                "amount": -1,
                "category": "Food",
                "date": "2026-11-07",
            },
            headers=headers,
        )
        self.assertEqual(invalid_expense.status_code, 400)

    def test_bill_and_game_topups_are_saved_as_expenses(self) -> None:
        headers, _ = self.register("topups@example.com")
        for title, category in (
            ("Water bill", "Bills & Utilities"),
            ("Mobile Legends diamonds", "Games & Recharges"),
        ):
            with self.subTest(category=category):
                response = self.client.post(
                    "/api/expenses",
                    json={
                        "title": title,
                        "amount": 99.5,
                        "category": category,
                        "date": "2026-11-07",
                        "notes": "",
                    },
                    headers=headers,
                )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.get_json()["category"], category)

    def test_grocery_list_is_persisted_and_private_per_user(self) -> None:
        alice_headers, _ = self.register("grocery-alice@example.com", "Alice")
        bob_headers, _ = self.register("grocery-bob@example.com", "Bob")
        payload = {"name": "Rice", "quantity": 2, "budget": 180, "purchased": False}

        created = self.client.post("/api/groceries", json=payload, headers=alice_headers)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["name"], "Rice")
        self.assertEqual(created.get_json()["quantity"], 2)
        self.assertEqual(created.get_json()["budget"], 180)
        self.assertIsNone(created.get_json()["purchasedAt"])
        item_id = created.get_json()["id"]
        self.assertEqual(self.client.get("/api/groceries", headers=bob_headers).get_json(), [])

        restarted_client = FastAPITestClient(main.create_app())
        persisted_items = restarted_client.get("/api/groceries", headers=alice_headers).get_json()
        self.assertEqual(len(persisted_items), 1)
        self.assertEqual(persisted_items[0]["id"], item_id)
        self.assertEqual(persisted_items[0]["name"], "Rice")
        self.assertEqual(persisted_items[0]["quantity"], 2)
        self.assertEqual(persisted_items[0]["budget"], 180)

        partial_update = self.client.patch(
            f"/api/groceries/{item_id}",
            json={"quantity": 4},
            headers=alice_headers,
        )
        self.assertEqual(partial_update.status_code, 200)
        self.assertEqual(partial_update.get_json()["quantity"], 4)
        self.assertEqual(partial_update.get_json()["name"], "Rice")
        self.assertEqual(partial_update.get_json()["budget"], 180)

        updated_payload = {**payload, "quantity": 3, "purchased": True}
        updated = self.client.patch(
            f"/api/groceries/{item_id}",
            json={"purchased": True},
            headers=alice_headers,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertTrue(updated.get_json()["purchased"])
        self.assertTrue(updated.get_json()["purchasedAt"])
        purchase_response = self.client.get("/api/purchase-history", headers=alice_headers)
        self.assertEqual(purchase_response.status_code, 200)
        self.assertEqual(len(purchase_response.get_json()), 1)
        purchase = purchase_response.get_json()[0]
        self.assertEqual(purchase["productName"], "Rice")
        self.assertEqual(purchase["category"], "Groceries")
        self.assertEqual(purchase["quantity"], 4)
        self.assertEqual(purchase["unitPrice"], 180)
        self.assertEqual(purchase["expense"], 720)
        self.assertTrue(purchase["purchasedAt"])
        self.assertEqual(self.client.get("/api/purchase-history", headers=bob_headers).get_json(), [])
        repeated_purchase_update = self.client.put(
            f"/api/groceries/{item_id}",
            json=updated_payload,
            headers=alice_headers,
        )
        self.assertEqual(repeated_purchase_update.status_code, 200)
        self.assertEqual(len(self.client.get("/api/purchase-history", headers=alice_headers).get_json()), 1)
        self.assertEqual(len(restarted_client.get("/api/purchase-history", headers=alice_headers).get_json()), 1)
        self.assertEqual(
            self.client.get("/api/groceries", headers=alice_headers).get_json()[0]["quantity"],
            3,
        )
        self.assertTrue(self.client.get("/api/groceries", headers=alice_headers).get_json()[0]["purchasedAt"])
        unchecked = self.client.put(
            f"/api/groceries/{item_id}",
            json={**updated_payload, "purchased": False},
            headers=alice_headers,
        )
        self.assertEqual(unchecked.status_code, 200)
        self.assertIsNone(unchecked.get_json()["purchasedAt"])
        self.assertEqual(len(self.client.get("/api/purchase-history", headers=alice_headers).get_json()), 0)
        repurchased = self.client.put(
            f"/api/groceries/{item_id}",
            json=updated_payload,
            headers=alice_headers,
        )
        self.assertEqual(repurchased.status_code, 200)
        self.assertEqual(len(self.client.get("/api/purchase-history", headers=alice_headers).get_json()), 1)
        self.assertEqual(
            self.client.delete(f"/api/groceries/{item_id}", headers=bob_headers).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(f"/api/groceries/{item_id}", headers=alice_headers).status_code,
            200,
        )
        self.assertEqual(len(self.client.get("/api/purchase-history", headers=alice_headers).get_json()), 1)

    def test_grocery_item_id_is_unique_and_auto_generated(self) -> None:
        headers, _ = self.register("unique-grocery@example.com")
        payload = {"name": "Apples", "quantity": 2, "budget": 15, "purchased": False}

        first = self.client.post("/api/groceries", json=payload, headers=headers)
        second = self.client.post(
            "/api/groceries",
            json={**payload, "name": "Bananas"},
            headers=headers,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.get_json()["id"], second.get_json()["id"])

    def test_grocery_endpoint_rejects_invalid_items_and_missing_auth(self) -> None:
        self.assertEqual(self.client.get("/api/groceries").status_code, 401)
        headers, _ = self.register("grocery-invalid@example.com")

        invalid = self.client.post(
            "/api/groceries",
            json={"name": "Milk", "quantity": 0, "budget": -10, "purchased": False},
            headers=headers,
        )
        self.assertEqual(invalid.status_code, 400)

    def test_existing_expenses_database_is_migrated(self) -> None:
        legacy_database = Path(self.temporary_directory.name) / "legacy-expenses.db"
        main.DB_NAME = legacy_database
        with closing(sqlite3.connect(legacy_database)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    date TEXT NOT NULL,
                    notes TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO expenses (title, amount, category, date, notes) VALUES (?, ?, ?, ?, ?)",
                ("Old record", 10, "Other", "2026-01-01", ""),
            )

        main.init_db()

        with closing(sqlite3.connect(main.DB_NAME)) as connection, connection:
            column_names = {row[1] for row in connection.execute("PRAGMA table_info(expenses)")}
            migrated_row = connection.execute("SELECT title, user_id FROM expenses").fetchone()
        self.assertIn("user_id", column_names)
        self.assertEqual(migrated_row, ("Old record", None))


if __name__ == "__main__":
    unittest.main()
