from flask import Flask, render_template, request, session, redirect, url_for, flash, Response
from werkzeug.security import generate_password_hash, check_password_hash
from markupsafe import escape
from decimal import Decimal
import hmac
import secrets
import sqlite3
import logging
import csv
import io
from datetime import datetime, timedelta
from config import (
    SECRET_KEY, DEBUG, DATABASE_PATH, 
    TRANSACTION_TYPES, MIN_USERNAME_LENGTH, MAX_USERNAME_LENGTH,
    MIN_PASSWORD_LENGTH, MIN_CUSTOMER_NAME_LENGTH, MAX_CUSTOMER_NAME_LENGTH,
    MAX_PHONE_LENGTH, MAX_BALANCE, MIN_BALANCE, PERMANENT_SESSION_LIFETIME,
    SESSION_COOKIE_SECURE, SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE
)
from database import (
    init_db, get_db_connection, execute_query, execute_transaction,
    create_user, get_user_by_username, get_user_by_id,
    create_customer, get_customer_by_id, get_all_customers, update_customer_balance, delete_customer,
    create_transaction, get_transactions_for_customer, delete_transaction, delete_and_reverse_transaction,
    get_transaction_by_id, get_all_journal_transactions, archive_and_delete_transaction,
    get_deleted_transactions, get_deleted_transaction_by_id, count_deleted_transactions,
    restore_deleted_transaction, purge_deleted_transaction
)
from middleware import login_required

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('hisabflow.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    DEBUG=DEBUG,
    SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
    SESSION_COOKIE_HTTPONLY=SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_SAMESITE=SESSION_COOKIE_SAMESITE,
    PERMANENT_SESSION_LIFETIME=PERMANENT_SESSION_LIFETIME,
)

# Initialize database on app startup
init_db()

@app.before_request
def before_request():
    """Enforce session timeout and permanent session."""
    session.permanent = True
    if request.method == 'POST':
        expected_token = session.get('csrf_token')
        submitted_token = request.form.get('csrf_token', '')
        if not expected_token or not submitted_token or not hmac.compare_digest(expected_token, submitted_token):
            session.clear()
            flash('Your form session expired. Please try again.', 'warning')
            return redirect(url_for('login'))

    user_id = session.get('user_id')
    if user_id:
        user = get_user_by_id(user_id)
        if not user:
            session.clear()
            flash('Your session has expired. Please log in again.', 'warning')
        else:
            session['user_data'] = user

@app.route('/')
def index():
    """Home page - redirects to dashboard if logged in, else to login."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """
    User registration route.
    GET: Display signup form.
    POST: Create new user account with hashed password.
    """
    if request.method == 'POST':
        username = escape(request.form.get('username', '').strip())
        email = escape(request.form.get('email', '').strip())
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        # Validation
        if not username or not email or not password or not confirm_password:
            flash('All fields are required.', 'error')
            return redirect(url_for('signup'))
        
        if len(username) < MIN_USERNAME_LENGTH:
            flash(f'Username must be at least {MIN_USERNAME_LENGTH} characters long.', 'error')
            return redirect(url_for('signup'))
        
        if len(username) > MAX_USERNAME_LENGTH:
            flash(f'Username must not exceed {MAX_USERNAME_LENGTH} characters.', 'error')
            return redirect(url_for('signup'))
        
        if len(password) < MIN_PASSWORD_LENGTH:
            flash(f'Password must be at least {MIN_PASSWORD_LENGTH} characters long.', 'error')
            return redirect(url_for('signup'))
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('signup'))
        
        # Check if user already exists
        existing_user = get_user_by_username(username)
        if existing_user:
            flash('Username already exists. Please choose a different one.', 'error')
            return redirect(url_for('signup'))
        
        try:
            # Hash password and create user
            password_hash = generate_password_hash(password)
            user_id = create_user(username, email, password_hash)
            logger.info(f'User registered successfully: {username}')
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError as e:
            logger.error(f'Signup IntegrityError for user {username}: {str(e)}', exc_info=True)
            flash('Email already registered. Please use a different email.', 'error')
            return redirect(url_for('signup'))
        except Exception as e:
            logger.error(f'Signup error for user {username}: {str(e)}', exc_info=True)
            flash('An error occurred during signup. Please try again.', 'error')
            return redirect(url_for('signup'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    User authentication route.
    GET: Display login form.
    POST: Validate credentials and establish session.
    """
    if request.method == 'GET' and session.get('user_id'):
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('Username and password are required.', 'error')
            return redirect(url_for('login'))
        
        user = get_user_by_username(username)
        
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session.permanent = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['user_data'] = {
                'id': user['id'],
                'username': user['username'],
                'email': user['email']
            }
            logger.info(f'User logged in: {user["username"]}')
            flash(f'Welcome back, {user["username"]}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            logger.warning(f'Failed login attempt for username: {username}')
            flash('Invalid username or password.', 'error')
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    """Destroy session and log out user."""
    username = session.get('username', 'Unknown')
    session.clear()
    logger.info(f'User logged out: {username}')
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    """
    Main dashboard displaying all customers for the logged-in user.
    """
    user_id = session['user_id']
    customers = get_all_customers(user_id)
    
    # Calculate summary statistics
    total_balance = sum(c['current_balance'] for c in customers)
    total_customers = len(customers)
    
    return render_template('dashboard.html', 
                          customers=customers, 
                          total_balance=total_balance,
                          total_customers=total_customers)

@app.route('/customer/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    """
    Add a new customer.
    GET: Display customer form.
    POST: Create customer record.
    """
    user_id = session['user_id']
    
    if request.method == 'POST':
        name = escape(request.form.get('name', '').strip())
        phone = escape(request.form.get('phone', '').strip())
        starting_balance = request.form.get('starting_balance', '0')
        
        # Validation
        if not name or not phone:
            flash('Customer name and phone are required.', 'error')
            return redirect(url_for('add_customer'))
        
        if len(name) < MIN_CUSTOMER_NAME_LENGTH:
            flash(f'Customer name must be at least {MIN_CUSTOMER_NAME_LENGTH} characters long.', 'error')
            return redirect(url_for('add_customer'))
        
        if len(name) > MAX_CUSTOMER_NAME_LENGTH:
            flash(f'Customer name must not exceed {MAX_CUSTOMER_NAME_LENGTH} characters.', 'error')
            return redirect(url_for('add_customer'))
        
        if len(phone) > MAX_PHONE_LENGTH:
            flash(f'Phone number must not exceed {MAX_PHONE_LENGTH} characters.', 'error')
            return redirect(url_for('add_customer'))
        
        try:
            starting_balance = Decimal(starting_balance).quantize(Decimal('0.01')) if starting_balance else Decimal('0.00')
            if starting_balance < MIN_BALANCE or starting_balance > MAX_BALANCE:
                flash('Starting balance is out of valid range.', 'error')
                return redirect(url_for('add_customer'))
        except:
            flash('Starting balance must be a valid number.', 'error')
            return redirect(url_for('add_customer'))
        
        try:
            customer_id = create_customer(user_id, name, phone, float(starting_balance))
            logger.info(f'Customer created: {name} (ID: {customer_id}) by user {user_id}')
            flash(f'Customer "{name}" added successfully!', 'success')
            return redirect(url_for('ledger', customer_id=customer_id))
        except sqlite3.IntegrityError as e:
            logger.error(f'Customer creation IntegrityError: {str(e)}', exc_info=True)
            flash('A customer with this information already exists.', 'error')
            return redirect(url_for('add_customer'))
        except Exception as e:
            logger.error(f'Customer creation error: {str(e)}', exc_info=True)
            flash('An error occurred while adding the customer.', 'error')
            return redirect(url_for('add_customer'))
    
    return render_template('add_customer.html')

@app.route('/customer/<int:customer_id>/ledger', methods=['GET'])
@login_required
def ledger(customer_id):
    """
    Display customer detail page with transaction history.
    """
    user_id = session['user_id']
    customer = get_customer_by_id(customer_id, user_id)
    
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('dashboard'))
    
    transactions = get_transactions_for_customer(customer_id, user_id)
    
    total_credit = sum(t['amount'] for t in transactions if t['transaction_type'] == 'credit')
    total_debit = sum(t['amount'] for t in transactions if t['transaction_type'] == 'debit')
    last_archive_id = session.get('last_deleted_archive_id')
    
    return render_template('ledger.html', 
                          customer=customer, 
                          transactions=transactions,
                          total_credit=total_credit,
                          total_debit=total_debit,
                          last_archive_id=last_archive_id)

@app.route('/transaction/add/<int:customer_id>', methods=['GET', 'POST'])
@login_required
def add_transaction(customer_id):
    """
    Add a transaction for a customer.
    GET: Display transaction form.
    POST: Log transaction and update customer balance.
    """
    user_id = session['user_id']
    customer = get_customer_by_id(customer_id, user_id)
    
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        transaction_type = escape(request.form.get('type', '').strip())
        amount_str = request.form.get('amount', '').strip()
        description = escape(request.form.get('description', '').strip())
        
        # Validation
        if not transaction_type or transaction_type not in TRANSACTION_TYPES:
            flash('Invalid transaction type.', 'error')
            return redirect(url_for('add_transaction', customer_id=customer_id))
        
        if not amount_str:
            flash('Amount is required.', 'error')
            return redirect(url_for('add_transaction', customer_id=customer_id))
        
        try:
            amount = Decimal(amount_str).quantize(Decimal('0.01'))
            if amount <= 0:
                flash('Amount must be greater than zero.', 'error')
                return redirect(url_for('add_transaction', customer_id=customer_id))
        except:
            flash('Amount must be a valid number.', 'error')
            return redirect(url_for('add_transaction', customer_id=customer_id))
        
        # Calculate new balance using Decimal for precision
        current_balance = Decimal(str(customer['current_balance'])).quantize(Decimal('0.01'))
        if transaction_type == 'credit':
            new_balance = current_balance + amount
        else:  # debit
            new_balance = current_balance - amount
        
        # Validate balance is within acceptable range
        if new_balance < MIN_BALANCE or new_balance > MAX_BALANCE:
            flash('Transaction would result in balance out of acceptable range.', 'error')
            logger.warning(f'Transaction rejected: balance overflow. Customer {customer_id}, new balance {new_balance}')
            return redirect(url_for('add_transaction', customer_id=customer_id))
        
        new_balance_float = float(new_balance)
        
        try:
            queries = [
                (
                    '''INSERT INTO transactions (customer_id, user_id, transaction_type, amount, description, balance_after)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (customer_id, user_id, transaction_type, float(amount), description or None, new_balance_float)
                ),
                (
                    '''UPDATE customers SET current_balance = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
                    (new_balance_float, customer_id)
                )
            ]
            execute_transaction(queries)
            logger.info(f'Transaction created: {transaction_type} Rs. {amount} for customer {customer_id}')
            flash(f'Transaction logged successfully! New balance: Rs. {new_balance:.2f}', 'success')
            return redirect(url_for('ledger', customer_id=customer_id))
        except sqlite3.Error as e:
            logger.error(f'Transaction DB error for customer {customer_id}: {str(e)}', exc_info=True)
            flash('Database error while logging the transaction.', 'error')
            return redirect(url_for('add_transaction', customer_id=customer_id))
        except Exception as e:
            logger.error(f'Transaction error for customer {customer_id}: {str(e)}', exc_info=True)
            flash('An error occurred while logging the transaction.', 'error')
            return redirect(url_for('add_transaction', customer_id=customer_id))
    
    return render_template('add_transaction.html', customer=customer)

@app.route('/transaction/delete/<int:transaction_id>', methods=['POST'])
@login_required
def delete_trans(transaction_id):
    """Delete a transaction and archive it into the Recovery Vault with reversed balance."""
    user_id = session['user_id']
    
    transaction = delete_transaction(transaction_id, user_id)
    
    if not transaction:
        flash('Transaction not found or you do not have permission to delete it.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        customer_id = transaction['customer_id']
        customer = get_customer_by_id(customer_id, user_id)
        
        if not customer:
            flash('Customer not found.', 'error')
            logger.error(f'Customer not found for transaction deletion: customer_id {customer_id}')
            return redirect(url_for('dashboard'))
        
        # Calculate new balance using Decimal
        current = Decimal(str(customer['current_balance'])).quantize(Decimal('0.01'))
        amount = Decimal(str(transaction['amount'])).quantize(Decimal('0.01'))
        
        if transaction['transaction_type'] == 'credit':
            new_balance = current - amount
        else:  # debit
            new_balance = current + amount
        
        # Validate balance is within acceptable range
        if new_balance < MIN_BALANCE or new_balance > MAX_BALANCE:
            flash('Cannot delete transaction: would exceed acceptable balance range.', 'error')
            logger.warning(f'Balance overflow prevented in delete: customer {customer_id}, new balance {new_balance}')
            return redirect(url_for('ledger', customer_id=customer_id))
        
        # Atomic operation: archive transaction + reverse customer balance
        archive_id = archive_and_delete_transaction(transaction, float(new_balance))
        session['last_deleted_archive_id'] = archive_id
        logger.info(f'Transaction archived & deleted: ID {transaction_id}, archive {archive_id}, customer {customer_id}')
        
        flash(f'Transaction of Rs. {amount:.2f} moved to Recovery Vault. Balance reversed.', 'warning')
        return redirect(url_for('ledger', customer_id=customer_id))
    except sqlite3.Error as e:
        logger.error(f'DB error deleting transaction {transaction_id}: {str(e)}', exc_info=True)
        flash('Database error while deleting the transaction. Please try again.', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f'Unexpected error in delete_trans: {str(e)}', exc_info=True)
        flash('An error occurred while deleting the transaction.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/customer/delete/<int:customer_id>', methods=['POST'])
@login_required
def delete_cust(customer_id):
    """Delete a customer and all associated transactions."""
    user_id = session['user_id']
    
    customer = get_customer_by_id(customer_id, user_id)
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        delete_customer(customer_id, user_id)
        logger.info(f'Customer deleted: {customer["name"]} (ID: {customer_id})')
        flash(f'Customer "{customer["name"]}" and all associated transactions deleted.', 'success')
    except sqlite3.Error as e:
        logger.error(f'DB error deleting customer {customer_id}: {str(e)}', exc_info=True)
        flash('Database error while deleting the customer.', 'error')
    except Exception as e:
        logger.error(f'Error deleting customer {customer_id}: {str(e)}', exc_info=True)
        flash('An error occurred while deleting the customer.', 'error')
    
    return redirect(url_for('dashboard'))

# -------------------------------------------------------------
# Recovery Vault & Transaction Reroll Routes
# -------------------------------------------------------------
@app.route('/recovery')
@login_required
def recovery_vault():
    """Display the Recovery Vault with all archived/deleted transactions."""
    user_id = session['user_id']
    deleted_transactions = get_deleted_transactions(user_id)
    return render_template('recovery.html', deleted_transactions=deleted_transactions)

@app.route('/transaction/restore/<int:archive_id>', methods=['POST'])
@login_required
def restore_trans(archive_id):
    """Restore (reroll) an archived transaction back into active ledger."""
    user_id = session['user_id']
    try:
        result, error = restore_deleted_transaction(archive_id, user_id)
        if error:
            flash(error, 'error')
            return redirect(url_for('recovery_vault'))
        
        if session.get('last_deleted_archive_id') == archive_id:
            session.pop('last_deleted_archive_id', None)
            
        logger.info(f"Transaction rerolled/restored: Archive ID {archive_id} for customer {result['customer_id']}")
        flash(f"Transaction of Rs. {result['amount']:.2f} successfully restored (rerolled) for {result['customer_name']}! New balance: Rs. {result['new_balance']:.2f}", 'success')
        
        next_page = request.args.get('next')
        if next_page == 'ledger':
            return redirect(url_for('ledger', customer_id=result['customer_id']))
        return redirect(url_for('recovery_vault'))
    except Exception as e:
        logger.error(f"Error restoring transaction {archive_id}: {str(e)}", exc_info=True)
        flash('An error occurred while restoring the transaction.', 'error')
        return redirect(url_for('recovery_vault'))

@app.route('/transaction/restore-last', methods=['POST'])
@login_required
def restore_last_trans():
    """Quick undo/reroll for the most recently deleted transaction."""
    user_id = session['user_id']
    archive_id = session.get('last_deleted_archive_id')
    if not archive_id:
        flash('No recent deleted transaction found to undo.', 'warning')
        return redirect(request.referrer or url_for('dashboard'))
    
    try:
        result, error = restore_deleted_transaction(archive_id, user_id)
        session.pop('last_deleted_archive_id', None)
        if error:
            flash(error, 'error')
            return redirect(request.referrer or url_for('dashboard'))
        
        flash(f"Undone! Transaction of Rs. {result['amount']:.2f} rerolled back for {result['customer_name']}.", 'success')
        return redirect(url_for('ledger', customer_id=result['customer_id']))
    except Exception as e:
        logger.error(f"Error undoing last transaction: {str(e)}", exc_info=True)
        flash('Failed to undo the transaction.', 'error')
        return redirect(request.referrer or url_for('dashboard'))

@app.route('/transaction/purge/<int:archive_id>', methods=['POST'])
@login_required
def purge_trans(archive_id):
    """Permanently delete an archived transaction from the recovery vault."""
    user_id = session['user_id']
    try:
        purge_deleted_transaction(archive_id, user_id)
        if session.get('last_deleted_archive_id') == archive_id:
            session.pop('last_deleted_archive_id', None)
        flash('Transaction record permanently purged from the recovery vault.', 'success')
    except Exception as e:
        logger.error(f"Error purging transaction {archive_id}: {str(e)}", exc_info=True)
        flash('An error occurred while purging the record.', 'error')
    return redirect(url_for('recovery_vault'))

# -------------------------------------------------------------
# General Journal & Export Routes
# -------------------------------------------------------------
@app.route('/journal')
@login_required
def journal():
    """General Journal view of all transactions across all customers with filters."""
    user_id = session['user_id']
    customers = get_all_customers(user_id)
    
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    customer_id = request.args.get('customer_id', type=int)
    trans_type = request.args.get('type', '').strip()
    
    transactions = get_all_journal_transactions(
        user_id=user_id,
        customer_id=customer_id,
        start_date=start_date or None,
        end_date=end_date or None,
        transaction_type=trans_type or None
    )
    
    total_credit = sum(t['amount'] for t in transactions if t['transaction_type'] == 'credit')
    total_debit = sum(t['amount'] for t in transactions if t['transaction_type'] == 'debit')
    net_movement = total_credit - total_debit
    
    return render_template(
        'journal.html',
        transactions=transactions,
        customers=customers,
        total_credit=total_credit,
        total_debit=total_debit,
        net_movement=net_movement,
        selected_customer_id=customer_id,
        start_date=start_date,
        end_date=end_date,
        selected_type=trans_type
    )

@app.route('/journal/export/csv')
@login_required
def export_journal_csv():
    """Export the general journal book across all accounts to CSV."""
    user_id = session['user_id']
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    customer_id = request.args.get('customer_id', type=int)
    trans_type = request.args.get('type', '').strip()
    
    transactions = get_all_journal_transactions(
        user_id=user_id,
        customer_id=customer_id,
        start_date=start_date or None,
        end_date=end_date or None,
        transaction_type=trans_type or None
    )
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Journal Entry ID',
        'Date & Time',
        'Customer Name',
        'Customer Phone',
        'Transaction Type',
        'Debit (Outflow / Owed Rs.)',
        'Credit (Inflow / Paid Rs.)',
        'Customer Balance After (Rs.)',
        'Description'
    ])
    
    for t in transactions:
        debit_val = f"{t['amount']:.2f}" if t['transaction_type'] == 'debit' else ""
        credit_val = f"{t['amount']:.2f}" if t['transaction_type'] == 'credit' else ""
        writer.writerow([
            f"TX-{t['id']:05d}",
            t['created_at'],
            t['customer_name'],
            t['customer_phone'],
            t['transaction_type'].upper(),
            debit_val,
            credit_val,
            f"{t['balance_after']:.2f}",
            t['description'] or ''
        ])
        
    output.seek(0)
    current_time_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"general_journal_{current_time_str}.csv"
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )

@app.route('/customer/<int:customer_id>/export/csv')
@login_required
def export_customer_csv(customer_id):
    """Export transactions of 1 customer to CSV."""
    user_id = session['user_id']
    customer = get_customer_by_id(customer_id, user_id)
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('dashboard'))
    
    transactions = get_transactions_for_customer(customer_id, user_id)
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Summary header info
    writer.writerow(['Customer Name:', customer['name']])
    writer.writerow(['Phone:', customer['phone']])
    writer.writerow(['Current Outstanding Balance (Rs.):', f"{customer['current_balance']:.2f}"])
    writer.writerow(['Exported On:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow([])  # Blank line
    
    # Table headers
    writer.writerow([
        'Transaction ID',
        'Date & Time',
        'Type',
        'Debit (Outflow / Owed Rs.)',
        'Credit (Inflow / Paid Rs.)',
        'Balance After (Rs.)',
        'Description'
    ])
    
    for t in transactions:
        debit_val = f"{t['amount']:.2f}" if t['transaction_type'] == 'debit' else ""
        credit_val = f"{t['amount']:.2f}" if t['transaction_type'] == 'credit' else ""
        writer.writerow([
            f"TX-{t['id']:05d}",
            t['created_at'],
            t['transaction_type'].upper(),
            debit_val,
            credit_val,
            f"{t['balance_after']:.2f}",
            t['description'] or ''
        ])
        
    output.seek(0)
    clean_name = "".join(c for c in customer['name'] if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
    filename = f"{clean_name}_ledger_{datetime.now().strftime('%Y%m%d')}.csv"
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )

@app.route('/customer/<int:customer_id>/statement')
@login_required
def customer_statement(customer_id):
    """Printable account statement / PDF view for 1 customer."""
    user_id = session['user_id']
    customer = get_customer_by_id(customer_id, user_id)
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('dashboard'))
    
    transactions = get_transactions_for_customer(customer_id, user_id)
    
    total_credit = sum(t['amount'] for t in transactions if t['transaction_type'] == 'credit')
    total_debit = sum(t['amount'] for t in transactions if t['transaction_type'] == 'debit')
    
    return render_template(
        'statement.html',
        customer=customer,
        transactions=transactions,
        total_credit=total_credit,
        total_debit=total_debit,
        now=datetime.now()
    )

@app.route('/transaction/<int:transaction_id>/receipt')
@login_required
def transaction_receipt(transaction_id):
    """Display printable transaction voucher / payment receipt."""
    user_id = session['user_id']
    transaction = get_transaction_by_id(transaction_id, user_id)
    if not transaction:
        flash('Transaction not found.', 'error')
        return redirect(url_for('dashboard'))
        
    return render_template(
        'receipt.html',
        transaction=transaction,
        now=datetime.now()
    )

@app.context_processor
def inject_recovery_count():
    """Make recovery vault count available in all templates for notification badges."""
    count = 0
    if 'user_id' in session:
        try:
            count = count_deleted_transactions(session['user_id'])
        except Exception:
            count = 0
    return dict(recovery_count=count)

@app.context_processor
def inject_user():
    """Make user info available in all templates with caching."""
    user = None
    if 'user_id' in session:
        # Use cached user data from session if available
        if 'user_data' not in session:
            session['user_data'] = get_user_by_id(session['user_id'])
        user = session['user_data']
    return dict(current_user=user)

@app.context_processor
def inject_csrf_token():
    """Provide one session-bound token to all forms."""
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return dict(csrf_token=token)

@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 errors."""
    logger.warning(f'404 error: {request.url}')
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    """Handle 500 errors."""
    logger.error(f'500 error: {str(e)}', exc_info=True)
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=DEBUG, host='127.0.0.1', port=5000)
