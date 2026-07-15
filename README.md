# HisabFlow

HisabFlow is a Flask app for tracking customer balances, transactions, and ledger history for small businesses and retail shops.

## What it does

- User signup, login, and logout
- Session-based access control with `@login_required`
- Customer records with names, phone numbers, and running balances
- Credit and debit transactions with automatic balance updates
- Customer ledger pages with transaction history
- Delete customer and delete transaction flows with balance reversal
- Custom 404 and 500 pages

## Tech Stack

- Python 3
- Flask 2.3.3
- SQLite
- Werkzeug 2.3.7
- Jinja templates and static CSS

## Project Layout

```
app.py                 Main Flask application and routes
config.py              App settings and validation constants
database.py            SQLite schema and query helpers
middleware.py          Login protection decorator
requirements.txt       Python dependencies
static/css/style.css   App styling
templates/             HTML templates
```

## Database

The app creates three tables on startup:

- `users` for account data
- `customers` for customer profiles and balances
- `transactions` for credit and debit entries

Foreign keys are enabled, and customer deletion cascades to related records.

## Running Locally

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

## Key Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Redirect to login or dashboard |
| `/signup` | GET, POST | Create an account |
| `/login` | GET, POST | Sign in |
| `/logout` | GET | Sign out |
| `/dashboard` | GET | Customer overview |
| `/customer/add` | GET, POST | Add a customer |
| `/customer/<id>/ledger` | GET | View customer ledger |
| `/transaction/add/<id>` | GET, POST | Add a transaction |
| `/transaction/delete/<id>` | POST | Delete a transaction |
| `/customer/delete/<id>` | POST | Delete a customer |

## Configuration

- `SECRET_KEY` and `FLASK_ENV` are read from environment variables when available
- Session lifetime is 24 hours
- Database file defaults to `hisabflow.db`

## Notes

- Passwords are hashed with Werkzeug
- Queries use parameter binding
- The database schema is idempotent and initializes on app start
