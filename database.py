import sqlite3
import os
from decimal import Decimal
from config import DATABASE_PATH

def get_db_connection():
    """
    Get a database connection to SQLite.
    Returns a connection object with row factory set to sqlite3.Row for dict-like access.
    """
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """
    Initialize the database schema.
    Creates three tables: users, customers, and transactions.
    This function is idempotent and can be called multiple times.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Create users table with constraints
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL CHECK(length(username) <= 50 AND length(username) >= 3),
                email TEXT UNIQUE NOT NULL CHECK(length(email) <= 100),
                password_hash TEXT NOT NULL CHECK(length(password_hash) > 0),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create customers table with constraints
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL CHECK(length(name) <= 100 AND length(name) >= 2),
                phone TEXT NOT NULL CHECK(length(phone) <= 20),
                current_balance REAL DEFAULT 0.0 CHECK(current_balance >= -9999999.99 AND current_balance <= 9999999.99),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')
        
        # Create transactions table with constraints
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                transaction_type TEXT NOT NULL CHECK(transaction_type IN ('debit', 'credit')),
                amount REAL NOT NULL CHECK(amount > 0),
                description TEXT CHECK(length(description) <= 255),
                balance_after REAL NOT NULL CHECK(balance_after >= -9999999.99 AND balance_after <= 9999999.99),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')
        
        # Create deleted_transactions table for the recovery and reroll vault
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deleted_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                transaction_type TEXT NOT NULL CHECK(transaction_type IN ('debit', 'credit')),
                amount REAL NOT NULL CHECK(amount > 0),
                description TEXT CHECK(length(description) <= 255),
                balance_after REAL NOT NULL,
                created_at TIMESTAMP NOT NULL,
                deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
    finally:
        conn.close()

def execute_query(query, params=(), fetch_one=False, fetch_all=False):
    """
    Execute a generic query with parameter binding to prevent SQL injection.
    Connection is ALWAYS closed via finally block.
    
    Args:
        query: SQL query string with ? placeholders
        params: Tuple of parameters to bind to the query
        fetch_one: If True, returns a single row (dict-like object)
        fetch_all: If True, returns all rows as a list
    
    Returns:
        Query result based on fetch_one/fetch_all flags, or last inserted row ID for INSERT
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(query, params)
        
        if fetch_one:
            result = cursor.fetchone()
            return dict(result) if result else None
        elif fetch_all:
            results = cursor.fetchall()
            return [dict(row) for row in results]
        else:
            conn.commit()
            return cursor.lastrowid
    except sqlite3.Error as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def execute_transaction(queries):
    """
    Execute multiple queries within a database transaction.
    All queries must succeed for the transaction to commit.
    Connection cleanup is guaranteed via finally block.
    
    Args:
        queries: List of tuples (query, params)
    
    Returns:
        List of last inserted row IDs or affected row counts
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    results = []
    
    try:
        for query, params in queries:
            cursor.execute(query, params)
            results.append(cursor.lastrowid)
        conn.commit()
        return results
    except sqlite3.Error as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# User operations
def create_user(username, email, password_hash):
    """Create a new user with hashed password."""
    query = '''
        INSERT INTO users (username, email, password_hash)
        VALUES (?, ?, ?)
    '''
    return execute_query(query, (username, email, password_hash))

def get_user_by_username(username):
    """Fetch user by username."""
    query = 'SELECT * FROM users WHERE username = ?'
    return execute_query(query, (username,), fetch_one=True)

def get_user_by_id(user_id):
    """Fetch user by user ID."""
    query = 'SELECT id, username, email, created_at FROM users WHERE id = ?'
    return execute_query(query, (user_id,), fetch_one=True)

# Customer operations
def create_customer(user_id, name, phone, starting_balance=0.0):
    """Create a new customer for a user."""
    query = '''
        INSERT INTO customers (user_id, name, phone, current_balance)
        VALUES (?, ?, ?, ?)
    '''
    return execute_query(query, (user_id, name, phone, starting_balance))

def get_customer_by_id(customer_id, user_id):
    """Fetch a customer by ID and verify ownership by user_id."""
    query = 'SELECT * FROM customers WHERE id = ? AND user_id = ?'
    return execute_query(query, (customer_id, user_id), fetch_one=True)

def get_all_customers(user_id):
    """Fetch all customers for a specific user."""
    query = 'SELECT * FROM customers WHERE user_id = ? ORDER BY name ASC'
    return execute_query(query, (user_id,), fetch_all=True)

def update_customer_balance(customer_id, new_balance):
    """Update the current balance of a customer."""
    query = '''
        UPDATE customers 
        SET current_balance = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    '''
    execute_query(query, (new_balance, customer_id))

def delete_customer(customer_id, user_id):
    """Delete a customer (cascade deletes transactions)."""
    query = 'DELETE FROM customers WHERE id = ? AND user_id = ?'
    execute_query(query, (customer_id, user_id))

# Transaction operations
def create_transaction(customer_id, user_id, transaction_type, amount, description, balance_after):
    """Create a new transaction for a customer."""
    query = '''
        INSERT INTO transactions (customer_id, user_id, transaction_type, amount, description, balance_after)
        VALUES (?, ?, ?, ?, ?, ?)
    '''
    return execute_query(query, (customer_id, user_id, transaction_type, amount, description, balance_after))

def get_transactions_for_customer(customer_id, user_id):
    """Fetch all transactions for a customer."""
    query = '''
        SELECT * FROM transactions 
        WHERE customer_id = ? 
        ORDER BY created_at DESC
    '''
    return execute_query(query, (customer_id,), fetch_all=True)

def delete_transaction(transaction_id, user_id):
    """
    Fetch transaction WITHOUT deleting.
    Deletion will be handled atomically in app layer.
    """
    query = '''
        SELECT t.* FROM transactions t
        INNER JOIN customers c ON t.customer_id = c.id
        WHERE t.id = ? AND t.user_id = ?
    '''
    return execute_query(query, (transaction_id, user_id), fetch_one=True)

def delete_and_reverse_transaction(transaction_id, customer_id, user_id, new_balance):
    """
    Atomically delete transaction and update balance.
    Both succeed or both fail - no orphaned state.
    """
    queries = [
        ('DELETE FROM transactions WHERE id = ?', (transaction_id,)),
        ('UPDATE customers SET current_balance = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', 
         (new_balance, customer_id))
    ]
    return execute_transaction(queries)

def get_transaction_by_id(transaction_id, user_id):
    """Fetch single transaction joined with customer info."""
    query = '''
        SELECT t.*, c.name AS customer_name, c.phone AS customer_phone, c.current_balance AS customer_current_balance
        FROM transactions t
        INNER JOIN customers c ON t.customer_id = c.id
        WHERE t.id = ? AND t.user_id = ?
    '''
    return execute_query(query, (transaction_id, user_id), fetch_one=True)

def get_all_journal_transactions(user_id, customer_id=None, start_date=None, end_date=None, transaction_type=None):
    """
    Fetch all transactions for user across all customers, with optional filters.
    """
    query = '''
        SELECT t.*, c.name AS customer_name, c.phone AS customer_phone
        FROM transactions t
        INNER JOIN customers c ON t.customer_id = c.id
        WHERE t.user_id = ?
    '''
    params = [user_id]
    if customer_id:
        query += ' AND t.customer_id = ?'
        params.append(customer_id)
    if start_date:
        query += ' AND date(t.created_at) >= date(?)'
        params.append(start_date)
    if end_date:
        query += ' AND date(t.created_at) <= date(?)'
        params.append(end_date)
    if transaction_type and transaction_type in ('credit', 'debit'):
        query += ' AND t.transaction_type = ?'
        params.append(transaction_type)
    query += ' ORDER BY t.created_at DESC, t.id DESC'
    return execute_query(query, tuple(params), fetch_all=True)

def archive_and_delete_transaction(transaction, new_balance):
    """
    Atomically archive transaction into deleted_transactions,
    remove it from transactions, and update the customer's balance.
    All operations succeed or all roll back.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO deleted_transactions 
            (original_id, customer_id, user_id, transaction_type, amount, description, balance_after, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            transaction['id'],
            transaction['customer_id'],
            transaction['user_id'],
            transaction['transaction_type'],
            transaction['amount'],
            transaction['description'],
            transaction['balance_after'],
            transaction['created_at']
        ))
        archive_id = cursor.lastrowid
        
        cursor.execute('DELETE FROM transactions WHERE id = ?', (transaction['id'],))
        
        cursor.execute('''
            UPDATE customers 
            SET current_balance = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (new_balance, transaction['customer_id']))
        
        conn.commit()
        return archive_id
    except sqlite3.Error as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_deleted_transactions(user_id):
    """Fetch all archived/deleted transactions for a user."""
    query = '''
        SELECT d.*, c.name AS customer_name, c.phone AS customer_phone
        FROM deleted_transactions d
        LEFT JOIN customers c ON d.customer_id = c.id
        WHERE d.user_id = ?
        ORDER BY d.deleted_at DESC
    '''
    return execute_query(query, (user_id,), fetch_all=True)

def get_deleted_transaction_by_id(archive_id, user_id):
    """Fetch single archived/deleted transaction by its archive ID."""
    query = '''
        SELECT d.*, c.name AS customer_name, c.phone AS customer_phone
        FROM deleted_transactions d
        LEFT JOIN customers c ON d.customer_id = c.id
        WHERE d.id = ? AND d.user_id = ?
    '''
    return execute_query(query, (archive_id, user_id), fetch_one=True)

def count_deleted_transactions(user_id):
    """Get the total count of recoverable deleted transactions for user."""
    query = 'SELECT COUNT(*) as count FROM deleted_transactions WHERE user_id = ?'
    res = execute_query(query, (user_id,), fetch_one=True)
    return res['count'] if res else 0

def restore_deleted_transaction(archive_id, user_id):
    """
    Reroll / restore an archived transaction:
    Atomically re-creates the transaction in `transactions`, adjusts customer balance back,
    and removes the entry from `deleted_transactions`.
    """
    from config import MIN_BALANCE, MAX_BALANCE
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM deleted_transactions WHERE id = ? AND user_id = ?', (archive_id, user_id))
        archived = cursor.fetchone()
        if not archived:
            return None, 'Archived transaction not found or access denied.'
        
        archived = dict(archived)
        customer_id = archived['customer_id']
        
        cursor.execute('SELECT * FROM customers WHERE id = ? AND user_id = ?', (customer_id, user_id))
        customer = cursor.fetchone()
        if not customer:
            return None, 'Associated customer no longer exists. Cannot restore transaction.'
            
        customer = dict(customer)
        current_bal = Decimal(str(customer['current_balance'])).quantize(Decimal('0.01'))
        amt = Decimal(str(archived['amount'])).quantize(Decimal('0.01'))
        
        # When restored, re-apply the original transaction effect:
        # credit was +amount, debit was -amount
        if archived['transaction_type'] == 'credit':
            new_bal = current_bal + amt
        else:
            new_bal = current_bal - amt
            
        if new_bal < MIN_BALANCE or new_bal > MAX_BALANCE:
            return None, 'Restoring this transaction would exceed allowable balance range.'
            
        new_bal_float = float(new_bal)
        
        # Re-insert into transactions table
        cursor.execute('''
            INSERT INTO transactions (customer_id, user_id, transaction_type, amount, description, balance_after, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            customer_id,
            user_id,
            archived['transaction_type'],
            float(amt),
            archived['description'],
            new_bal_float,
            archived['created_at']
        ))
        new_trans_id = cursor.lastrowid
        
        # Update customer balance
        cursor.execute('''
            UPDATE customers 
            SET current_balance = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (new_bal_float, customer_id))
        
        # Delete from deleted_transactions
        cursor.execute('DELETE FROM deleted_transactions WHERE id = ?', (archive_id,))
        
        conn.commit()
        return {
            'restored_transaction_id': new_trans_id,
            'customer_id': customer_id,
            'customer_name': customer['name'],
            'amount': float(amt),
            'transaction_type': archived['transaction_type'],
            'new_balance': new_bal_float
        }, None
    except sqlite3.Error as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def purge_deleted_transaction(archive_id, user_id):
    """Permanently delete an entry from deleted_transactions."""
    query = 'DELETE FROM deleted_transactions WHERE id = ? AND user_id = ?'
    execute_query(query, (archive_id, user_id))

