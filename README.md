# HisabFlow

HisabFlow is a Flask + SQLite ledger app for small shops to track customer balances and transaction history.

## Features

- User auth: signup, login, logout
- Session-protected app routes (`@login_required`)
- Customer management with opening balance
- Credit/debit entries with automatic balance update
- Customer ledger view with latest transactions first
- Safe delete flows:
	- delete transaction and reverse balance atomically
	- delete customer with cascade delete of related transactions
- Custom 404 and 500 pages

## Stack

- Python 3
- Flask 2.3.3
- SQLite
- Werkzeug 2.3.7
- Jinja2 templates + CSS

## Project Structure

```
app.py                 Flask routes, validation, session handling
config.py              Config and validation constants
database.py            Schema and DB helper functions
middleware.py          Login protection decorator
requirements.txt       Python dependencies
static/css/style.css   Styles
templates/             HTML templates
```

## Quick Start

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: `http://127.0.0.1:5000`

## Environment

Optional environment variables:

- `SECRET_KEY` (recommended in production)
- `FLASK_ENV=development` to enable debug mode

Defaults:

- SQLite database path: `hisabflow.db`
- Session lifetime: 24 hours

## Data Model

Tables created on startup (`init_db`):

- `users`
- `customers`
- `transactions`
- `deleted_transactions` (Recovery Vault & Audit log)

Notes:

- Foreign keys are enabled (`PRAGMA foreign_keys = ON`)
- `customers -> transactions` uses `ON DELETE CASCADE`
- `customers -> deleted_transactions` uses `ON DELETE CASCADE`
- Schema creation is idempotent

## Routes

| Route | Methods | Description |
| --- | --- | --- |
| `/` | GET | Redirect to login or dashboard |
| `/signup` | GET, POST | Register account |
| `/login` | GET, POST | Authenticate user |
| `/logout` | GET, POST | End session |
| `/dashboard` | GET | List customers + summary |
| `/customer/add` | GET, POST | Add customer |
| `/customer/<int:customer_id>/ledger` | GET | Customer ledger with filters & KPI summary |
| `/customer/<int:customer_id>/export/csv` | GET | Export single customer ledger to CSV spreadsheet |
| `/customer/<int:customer_id>/statement` | GET | Printable Statement of Account / PDF view |
| `/transaction/add/<int:customer_id>` | GET, POST | Add credit/debit entry |
| `/transaction/delete/<int:transaction_id>` | POST | Delete transaction, reverse balance & archive to Recovery Vault |
| `/transaction/<int:transaction_id>/receipt` | GET | Printable Official Payment Receipt / Voucher |
| `/journal` | GET | General Journal Book across all accounts with filters |
| `/journal/export/csv` | GET | Export entire Journal Book in 1 go to CSV |
| `/recovery` | GET | Recovery Vault (view archived/deleted transactions) |
| `/transaction/restore/<int:archive_id>` | POST | Restore / reroll archived transaction & recalculate balance |
| `/transaction/restore-last` | POST | Quick 1-click undo for most recently deleted transaction |
| `/transaction/purge/<int:archive_id>` | POST | Permanently delete record from Recovery Vault |
| `/customer/delete/<int:customer_id>` | POST | Delete customer and related transactions |

## Security and Reliability

- Passwords hashed with Werkzeug
- Input validation for usernames, passwords, balances, and amounts
- Parameterized SQL queries
- Atomic DB transactions for multi-step writes
