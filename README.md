# finaReq_expenseTracker

## Run locally

1. Install the Python API dependencies: `python -m pip install -r requirements.txt`
2. In phpMyAdmin, select the SQL tab and run `database\create_grocerylist_db.sql` for the database and tables. The API also creates the configured database automatically if it does not exist and the MySQL account has permission. If the old `grocerylist_db` table has `Product_name`, `Quantity`, and duplicate IDs, back it up and then run `database\migrate_grocerylist_db.sql` once. The migration keeps the old table as `grocerylist_db_backup` and creates new unique IDs.
3. Configure `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, and `MYSQL_DATABASE` for your local MySQL server. Defaults are `127.0.0.1`, `3306`, `root`, an empty password, and `grocerylist_db`.
4. Start the API from the project root: `python -m uvicorn main:app --reload`
5. In another terminal, start Ionic: `npm start`
6. Open `http://localhost:4200` for the Ionic app and create an account. Sign in with that account on later visits.

Uvicorn serves the native FastAPI ASGI entry point in the root `main.py`. The API listens at `http://localhost:8000`; opening `/` or `/api` shows API information, not the Ionic app. Accounts and login sessions are stored in the MySQL `grocerylist_db.users` and `grocerylist_db.auth_sessions` tables. Passwords are stored as salted scrypt hashes; existing plaintext values in `users.password_hash` are converted on the first API authentication request. Grocery checklist items are stored in MySQL's `grocerylist_db` table with purchase timestamps. Marking a grocery item purchased creates a persistent row in `purchase_history` (product name, category, quantity, unit price, total expense, and purchase date); unchecking or deleting the grocery-list item does not remove that history. On API startup, older grocery column names and simplified `purchase_history` tables are upgraded automatically. Expenses are stored in MySQL's `expense_records` table with a server-generated `purchased_at` timestamp, while the app's selected expense date remains unchanged. Existing SQLite expenses are migrated once into MySQL; their original SQLite database is retained as a backup.

Expenses and grocery items use collection/detail REST endpoints with GET, POST, PUT, PATCH, and DELETE methods. PATCH accepts only the fields being changed; the Angular grocery checklist uses it when toggling an item's purchased status.

The development API URL is `http://localhost:8000/api`, configured in `src/environments/environment.ts`. For an Android emulator, replace `localhost` with `10.0.2.2`. For a physical phone on a trusted local network, start Uvicorn with `python -m uvicorn main:app --reload --host 0.0.0.0` and use the computer's LAN IP in the Angular environment. Use an HTTPS API URL for a deployed app and update `src/environments/environment.prod.ts`.

## Stored data

The FastAPI backend creates `expenses.db` in the project root to preserve account mappings and migrate legacy expenses to MySQL. MySQL stores account email, display name, salted scrypt password hash, monthly budget, sessions, expense records, grocery records, and immutable grocery purchase-history entries. Grocery items include `purchased_at`, which is set when marked purchased and cleared if unchecked; their purchase-history entries remain saved. The expense form's bill and game top-up shortcuts only create expense records; they do not process real payments. Expenses, grocery rows, and purchase-history rows are scoped to the authenticated account and fetched from their databases on app load. The SQLite database file is excluded from Git.

Run the backend tests with `python -m unittest discover -s src\app\home -p test_main.py -v`.

This backend configuration is for a local school project. Deploy it behind HTTPS and restrict CORS to your app's origin before using real personal or financial data.
