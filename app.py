import os
import sqlite3
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "hisabflow.db")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.secret_key = os.environ.get("HISABFLOW_SECRET_KEY", "hisabflow-local-secret-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()


def login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_function(*args, **kwargs)

    return wrapped_view


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            message = "Both username and password are required."
        else:
            connection = get_db_connection()
            user = connection.execute(
                "SELECT id, username, password FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            connection.close()

            if user and check_password_hash(user["password"], password):
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                return redirect(url_for("dashboard"))

            message = "Invalid username or password."

    return render_template("login.html", message=message)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            message = "Username and password cannot be empty."
        else:
            connection = get_db_connection()
            existing_user = connection.execute(
                "SELECT id FROM users WHERE username = ?",
                (username,),
            ).fetchone()

            if existing_user:
                message = "Username already exists. Please choose a different one."
            else:
                hashed_password = generate_password_hash(password)
                connection.execute(
                    "INSERT INTO users (username, password) VALUES (?, ?)",
                    (username, hashed_password),
                )
                connection.commit()
                connection.close()
                return redirect(url_for("login"))

            connection.close()

    return render_template("signup.html", message=message)


@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    message = None
    customers = []

    connection = get_db_connection()

    if request.method == "POST":
        customer_name = request.form.get("name", "").strip()
        customer_phone = request.form.get("phone", "").strip()

        if not customer_name or not customer_phone:
            message = "Name and phone are required."
        else:
            connection.execute(
                "INSERT INTO customers (name, phone) VALUES (?, ?)",
                (customer_name, customer_phone),
            )
            connection.commit()
            message = "Customer added successfully."

    customers = connection.execute(
        "SELECT id, name, phone FROM customers ORDER BY id DESC"
    ).fetchall()
    connection.close()

    return render_template(
        "dashboard.html",
        username=session.get("username", "User"),
        customers=customers,
        message=message,
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)