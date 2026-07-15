from functools import wraps
from flask import session, redirect, url_for, flash

def login_required(f):
    """
    Custom decorator to protect routes that require user authentication.
    Checks if 'user_id' exists in Flask session.
    If not authenticated, redirects to login page with a flash message.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
