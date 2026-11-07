from functools import wraps
from flask import session, redirect, url_for, flash
from database import get_user_by_id

def login_required(f):
    """
    Custom decorator to protect routes that require user authentication.
    Checks if 'user_id' exists in Flask session.
    If not authenticated, redirects to login page with a flash message.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id or not get_user_by_id(user_id):
            session.clear()
            flash('Please log in first to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
