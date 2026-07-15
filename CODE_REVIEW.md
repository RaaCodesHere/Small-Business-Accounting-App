# HisabFlow: Comprehensive Code Review & Quality Audit
## Final Code Inspection Report
### Examiner: Senior Software Architect (Academic Review)
**Date**: 2026-07-15  
**Project**: HisabFlow v1.0.0 (4th Semester BCA)  
**Verdict**: **CONDITIONALLY APPROVED** - 6 Critical Issues Found, 4 Medium Issues, 3 Code Quality Concerns

---

## EXECUTIVE SUMMARY

The HisabFlow application demonstrates solid architectural understanding with proper separation of concerns (config, database, middleware, routes). However, **6 critical defects** have been identified that compromise **data integrity** and **system reliability** if left unresolved. These are not design flaws but implementation oversights.

**Pass Status**: ✅ Will pass with mandatory patches (see Section II)

---

# SECTION I: CRITICAL DEFECTS (Must Fix)

## 🔴 DEFECT #1: Race Condition in Transaction Deletion
**Severity**: CRITICAL (Data Integrity)  
**File**: `database.py`, Function `delete_transaction()` + `app.py`, Function `delete_trans()`  
**Impact**: Transaction deleted before balance reversal verified → **orphaned state if update fails**

### The Problem:
```python
# In database.py (Line 236-245)
def delete_transaction(transaction_id, user_id):
    query = '''SELECT t.* FROM transactions t ...'''
    transaction = execute_query(query, (transaction_id, user_id), fetch_one=True)
    if transaction:
        delete_query = 'DELETE FROM transactions WHERE id = ?'
        execute_query(delete_query, (transaction_id,))  # ❌ DELETES IMMEDIATELY
        return transaction
    return None

# In app.py (Line 269-290)
def delete_trans(transaction_id):
    user_id = session['user_id']
    transaction = delete_transaction(transaction_id, user_id)  # ← Already deleted in DB
    if not transaction:
        flash('Transaction not found...', 'error')
        return redirect(url_for('dashboard'))
    try:
        customer_id = transaction['customer_id']
        customer = get_customer_by_id(customer_id, user_id)
        if customer:
            # ❌ If this update fails, transaction is already gone from DB
            new_balance = customer['current_balance'] - transaction['amount']
            update_customer_balance(customer_id, new_balance)  # ← Separate DB call
            flash('Transaction deleted and balance reversed successfully.', 'success')
    except Exception as e:
        flash('An error occurred while deleting the transaction.', 'error')
```

### Why This Fails:
1. **Scenario**: Network hiccup, disk full, or exception during `update_customer_balance()`
2. **Result**: Transaction deleted ✓ | Balance update failed ✗ → **Inconsistent state**
3. **Audit Trail**: No transaction in database, but balance doesn't reflect the reversal

### The Fix:
**Refactor to true atomic operation:**

```python
# PATCH 1: Modify database.py - delete_transaction()
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

# PATCH 2: Add new atomic operation in database.py
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

# PATCH 3: Modify app.py - delete_trans()
@app.route('/transaction/delete/<int:transaction_id>', methods=['POST'])
@login_required
def delete_trans(transaction_id):
    """Delete a transaction and reverse its balance impact - ATOMICALLY."""
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
            return redirect(url_for('dashboard'))
        
        # Calculate new balance
        if transaction['transaction_type'] == 'credit':
            new_balance = customer['current_balance'] - transaction['amount']
        else:  # debit
            new_balance = customer['current_balance'] + transaction['amount']
        
        # Atomic operation: delete + reverse balance in single transaction
        delete_and_reverse_transaction(transaction_id, customer_id, user_id, new_balance)
        
        flash('Transaction deleted and balance reversed successfully.', 'success')
        return redirect(url_for('ledger', customer_id=customer_id))
    except sqlite3.Error as e:
        flash('Database error while deleting the transaction. Please try again.', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        flash('An error occurred while deleting the transaction.', 'error')
        return redirect(url_for('dashboard'))
```

---

## 🔴 DEFECT #2: Missing Finally Block in Connection Management
**Severity**: CRITICAL (Resource Leak)  
**File**: `database.py`  
**Functions**: `execute_query()` (Line 62-92), `execute_transaction()` (Line 94-118)  
**Impact**: Database connections may not be closed if exceptions occur in unexpected places

### The Problem:
```python
def execute_query(query, params=(), fetch_one=False, fetch_all=False):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        if fetch_one:
            result = cursor.fetchone()
            conn.close()  # ❌ If dict(result) fails, connection not closed
            return dict(result) if result else None  # Exception here = leak
        # ... similar for fetch_all and else
    except sqlite3.Error as e:
        conn.close()
        raise e

def execute_transaction(queries):
    conn = get_db_connection()
    cursor = conn.cursor()
    results = []
    try:
        for query, params in queries:
            cursor.execute(query, params)
            results.append(cursor.lastrowid)
        conn.commit()
        conn.close()  # ❌ If commit() fails, connection not properly closed
        return results
    except sqlite3.Error as e:
        conn.rollback()
        conn.close()  # ❌ If rollback() fails, exception swallowed
        raise e
```

### Why This Fails:
1. **Scenario 1**: `dict(result)` raises an exception → connection left open
2. **Scenario 2**: `conn.commit()` raises exception → resource leaked before exception handling
3. **Scenario 3**: `conn.rollback()` raises exception → mask original error

### The Fix:
```python
# PATCH 4: Refactor execute_query() with proper resource management
def execute_query(query, params=(), fetch_one=False, fetch_all=False):
    """
    Execute a generic query with parameter binding to prevent SQL injection.
    Connection is ALWAYS closed via finally block.
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

# PATCH 5: Refactor execute_transaction() with finally block
def execute_transaction(queries):
    """
    Execute multiple queries within a database transaction.
    All queries must succeed for the transaction to commit.
    Connection cleanup is guaranteed via finally block.
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
```

---

## 🔴 DEFECT #3: Unused Import Creates Code Smell
**Severity**: CRITICAL (Code Quality / Academic Standards)  
**File**: `app.py`, Line 2  
**Impact**: Suggests incomplete refactoring; confuses reviewers; fails strict code quality gates

### The Problem:
```python
from flask import Flask, render_template, request, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps  # ❌ IMPORTED BUT NEVER USED
import sqlite3
# ... other imports
from middleware import login_required
```

The `@login_required` decorator is imported from `middleware.py` (where `wraps` is properly used). Importing `wraps` again in `app.py` is redundant and indicates the developer didn't clean up after refactoring.

### Why This Fails:
1. **Academic Review**: Unused imports violate PEP 8 and basic code hygiene standards
2. **Linter Failure**: Any modern Python linter (flake8, pylint) will flag this
3. **Professionalism**: Suggests code wasn't reviewed before submission

### The Fix:
```python
# PATCH 6: Remove unused import from app.py
# REMOVE THIS LINE:
from functools import wraps  # ← DELETE

# Correct import block:
from flask import Flask, render_template, request, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from config import SECRET_KEY, DEBUG, DATABASE_PATH
from database import (
    init_db, get_db_connection, execute_query, execute_transaction,
    create_user, get_user_by_username, get_user_by_id,
    create_customer, get_customer_by_id, get_all_customers, 
    update_customer_balance, delete_customer,
    create_transaction, get_transactions_for_customer, delete_transaction
)
from middleware import login_required
```

---

## 🔴 DEFECT #4: Floating-Point Arithmetic for Currency (Money)
**Severity**: CRITICAL (Data Accuracy)  
**File**: `app.py`, Multiple locations  
**Lines**: 224, 263, 276, 281  
**Impact**: Balance calculations lose precision; customer accounts become inaccurate

### The Problem:
```python
# In add_transaction() - Line 224
starting_balance = float(starting_balance) if starting_balance else 0.0

# In add_transaction() - Line 263
amount = float(amount_str)

# In add_transaction() - Line 278-281
if transaction_type == 'credit':
    new_balance = current_balance + amount  # ❌ Float arithmetic
else:
    new_balance = current_balance - amount  # ❌ Float arithmetic
```

### Why This Fails:
**Example**: Customer balance = Rs. 0.1. You add Rs. 0.2. Expected balance = Rs. 0.3

```python
>>> 0.1 + 0.2
0.30000000000000004  # ❌ Not exactly 0.3!
```

After 100 transactions, accumulated floating-point error makes balances unreliable. In audits, this is **unacceptable** for financial systems.

### The Fix:
```python
# PATCH 7: Use integer arithmetic (paise) instead of float (rupees)
# Add to top of database.py
import sqlite3
import os
from decimal import Decimal  # ← ADD THIS IMPORT
from config import DATABASE_PATH

# PATCH 8: Modify create_customer() to use Decimal
def create_customer(user_id, name, phone, starting_balance=0.0):
    """Create a new customer for a user."""
    # Convert to Decimal immediately for precision
    balance_decimal = Decimal(str(starting_balance)).quantize(Decimal('0.01'))
    query = '''
        INSERT INTO customers (user_id, name, phone, current_balance)
        VALUES (?, ?, ?, ?)
    '''
    return execute_query(query, (user_id, name, phone, float(balance_decimal)))

# PATCH 9: Modify add_transaction() in app.py
@app.route('/transaction/add/<int:customer_id>', methods=['GET', 'POST'])
@login_required
def add_transaction(customer_id):
    from decimal import Decimal  # Add at function level
    user_id = session['user_id']
    customer = get_customer_by_id(customer_id, user_id)
    
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        transaction_type = request.form.get('type', '').strip()
        amount_str = request.form.get('amount', '').strip()
        description = request.form.get('description', '').strip()
        
        if not transaction_type or transaction_type not in ['credit', 'debit']:
            flash('Invalid transaction type.', 'error')
            return redirect(url_for('add_transaction', customer_id=customer_id))
        
        if not amount_str:
            flash('Amount is required.', 'error')
            return redirect(url_for('add_transaction', customer_id=customer_id))
        
        try:
            # Use Decimal for precise arithmetic
            amount = Decimal(amount_str).quantize(Decimal('0.01'))
            if amount <= 0:
                flash('Amount must be greater than zero.', 'error')
                return redirect(url_for('add_transaction', customer_id=customer_id))
        except:
            flash('Amount must be a valid number.', 'error')
            return redirect(url_for('add_transaction', customer_id=customer_id))
        
        # Calculate new balance using Decimal
        current_balance = Decimal(str(customer['current_balance'])).quantize(Decimal('0.01'))
        if transaction_type == 'credit':
            new_balance = current_balance + amount
        else:  # debit
            new_balance = current_balance - amount
        
        new_balance_float = float(new_balance)  # Convert back to float for DB storage
        
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
            
            flash(f'Transaction logged successfully! New balance: Rs. {new_balance:.2f}', 'success')
            return redirect(url_for('ledger', customer_id=customer_id))
        except Exception as e:
            flash('An error occurred while logging the transaction.', 'error')
            return redirect(url_for('add_transaction', customer_id=customer_id))
    
    return render_template('add_transaction.html', customer=customer)
```

---

## 🔴 DEFECT #5: Silent Exception Swallowing (No Logging)
**Severity**: CRITICAL (Debugging & Maintenance)  
**File**: `app.py`  
**Lines**: 96, 160, 245, 265, 310, 318  
**Impact**: Errors disappear; impossible to debug in production; fails audit trail requirements

### The Problem:
```python
# Line 96 in signup()
except Exception as e:
    flash(f'An error occurred during signup. Please try again.', 'error')
    return redirect(url_for('signup'))
    # ❌ Exception caught but thrown away - NO LOG, NO TRACE

# Line 245 in add_transaction()
except Exception as e:
    flash('An error occurred while logging the transaction.', 'error')
    # ❌ Exception e is never examined or logged

# Line 310 in delete_cust()
except Exception as e:
    flash('An error occurred while deleting the customer.', 'error')
    # ❌ Same issue
```

### Why This Fails:
1. **No Audit Trail**: 12 months from now, why did transactions fail? No record.
2. **Debugging Nightmare**: Developer gets "An error occurred" - could be 100 different things
3. **Production Blind Spot**: Can't monitor real issues
4. **Academic Failing**: Serious applications require error logging

### The Fix:
```python
# PATCH 10: Add logging to app.py
import logging  # ADD AT TOP
from flask import Flask, render_template, request, session, redirect, url_for, flash

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

# PATCH 11: Replace all generic exception handlers
# Example 1: In signup()
except Exception as e:
    logger.error(f'Signup error for user {username}: {str(e)}', exc_info=True)
    flash('An error occurred during signup. Please try again.', 'error')
    return redirect(url_for('signup'))

# Example 2: In add_transaction()
except Exception as e:
    logger.error(f'Transaction error for customer {customer_id}, user {user_id}: {str(e)}', exc_info=True)
    flash('An error occurred while logging the transaction.', 'error')
    return redirect(url_for('add_transaction', customer_id=customer_id))

# Example 3: In delete_cust()
except Exception as e:
    logger.error(f'Customer deletion error: {str(e)}', exc_info=True)
    flash('An error occurred while deleting the customer.', 'error')
```

---

## 🔴 DEFECT #6: Missing Validation for Account Balance Boundaries
**Severity**: CRITICAL (Business Logic)  
**File**: `app.py`, Function `delete_trans()` & `add_transaction()`  
**Impact**: Can create negative balances that break business logic

### The Problem:
```python
# In delete_trans() - Line 281
if transaction['transaction_type'] == 'credit':
    new_balance = customer['current_balance'] - transaction['amount']
else:
    new_balance = customer['current_balance'] + transaction['amount']

# ❌ new_balance can be any value - no validation!
# ❌ Customer balance goes negative, breaking business logic
```

### Scenario:
1. Ahmed's balance: Rs. 100
2. Debit transaction: Rs. 50 (payment received)
3. Ahmed's new balance: Rs. 50 ✓
4. **Delete that debit transaction**:
   - new_balance = 50 + 50 = 100 ✓ (correct)

But what if there's a **race condition**? Another transaction added after deletion but before balance calc?

More importantly: **What if negative balances should be prohibited?**

### The Fix:
```python
# PATCH 12: Add balance validation
def delete_trans(transaction_id):
    """Delete a transaction and reverse its balance impact - WITH VALIDATION."""
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
            return redirect(url_for('dashboard'))
        
        # Calculate new balance
        from decimal import Decimal
        current = Decimal(str(customer['current_balance'])).quantize(Decimal('0.01'))
        amount = Decimal(str(transaction['amount'])).quantize(Decimal('0.01'))
        
        if transaction['transaction_type'] == 'credit':
            new_balance = current - amount
        else:
            new_balance = current + amount
        
        # Validate: Balance should not go below configured minimum
        # (You can configure this in config.py)
        MIN_BALANCE = Decimal('-9999999.99')  # Allow reasonable negatives
        if new_balance < MIN_BALANCE:
            flash('Cannot delete transaction: would exceed minimum allowed balance.', 'error')
            logger.warning(f'Balance underflow prevented: customer {customer_id}, new balance {new_balance}')
            return redirect(url_for('ledger', customer_id=customer_id))
        
        delete_and_reverse_transaction(transaction_id, customer_id, user_id, float(new_balance))
        
        flash('Transaction deleted and balance reversed successfully.', 'success')
        return redirect(url_for('ledger', customer_id=customer_id))
    except sqlite3.Error as e:
        logger.error(f'DB error deleting transaction {transaction_id}: {str(e)}', exc_info=True)
        flash('Database error while deleting the transaction.', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f'Unexpected error in delete_trans: {str(e)}', exc_info=True)
        flash('An error occurred while deleting the transaction.', 'error')
        return redirect(url_for('dashboard'))
```

---

# SECTION II: MEDIUM SEVERITY ISSUES

## 🟠 ISSUE #7: Context Processor Inefficiency
**Severity**: MEDIUM (Performance)  
**File**: `app.py`, Line 312-316  
**Impact**: `get_user_by_id()` called on every request (wasteful)

### Current Code:
```python
@app.context_processor
def inject_user():
    """Make user info available in all templates."""
    user = None
    if 'user_id' in session:
        user = get_user_by_id(session['user_id'])  # ← DB call every request
    return dict(current_user=user)
```

### Fix:
```python
# PATCH 13: Cache user info in session
@app.context_processor
def inject_user():
    """Make user info available in all templates."""
    user = None
    if 'user_id' in session:
        # Only fetch if not cached in session
        if 'user_data' not in session:
            session['user_data'] = get_user_by_id(session['user_id'])
        user = session['user_data']
    return dict(current_user=user)
```

---

## 🟠 ISSUE #8: Redundant Database Lookups
**Severity**: MEDIUM (Performance)  
**File**: `database.py`, Function `get_transactions_for_customer()`  
**Impact**: INNER JOIN on customers table unnecessary (already verified user ownership)

### Current Code (Line 221-228):
```python
def get_transactions_for_customer(customer_id, user_id):
    """Fetch all transactions for a customer, verified by user ownership."""
    query = '''
        SELECT t.* FROM transactions t
        INNER JOIN customers c ON t.customer_id = c.id
        WHERE t.customer_id = ? AND c.user_id = ?
        ORDER BY t.created_at DESC
    '''
    return execute_query(query, (customer_id, user_id), fetch_all=True)
```

### Why It's Wasteful:
- We already verified the customer is owned by the user via `get_customer_by_id()` in the route
- INNER JOIN adds unnecessary computation
- We don't need customer columns - just transactions

### Fix:
```python
# PATCH 14: Simplify query
def get_transactions_for_customer(customer_id, user_id):
    """Fetch all transactions for a customer."""
    query = '''
        SELECT * FROM transactions 
        WHERE customer_id = ? 
        ORDER BY created_at DESC
    '''
    return execute_query(query, (customer_id,), fetch_all=True)
    
# Note: Route already verified user ownership via get_customer_by_id(customer_id, user_id)
# So redundant user_id check not needed here
```

---

## 🟠 ISSUE #9: Missing Database Constraints
**Severity**: MEDIUM (Data Integrity)  
**File**: `database.py`, Function `init_db()`  
**Impact**: No length limits on critical fields; can cause storage/performance issues

### Current Schema:
```python
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,  # ❌ No length limit
        email TEXT UNIQUE NOT NULL,     # ❌ No length limit
        password_hash TEXT NOT NULL,    # ❌ No length limit
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
```

### Fix:
```python
# PATCH 15: Add CHECK constraints for realistic sizes
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL CHECK(length(username) <= 50 AND length(username) >= 3),
        email TEXT UNIQUE NOT NULL CHECK(length(email) <= 100),
        password_hash TEXT NOT NULL CHECK(length(password_hash) > 0),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

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
```

---

## 🟠 ISSUE #10: No Session Timeout Enforcement
**Severity**: MEDIUM (Security)  
**File**: `config.py` & `app.py`  
**Impact**: Session may persist indefinitely despite timeout config

### Current Code:
```python
# config.py
PERMANENT_SESSION_LIFETIME = 86400  # 24 hours

# app.py - Line 108
session.permanent = True
```

### Problem:
Session timeout is set but never enforced. Flask doesn't automatically expire sessions unless configured.

### Fix:
```python
# PATCH 16: Enforce session timeout
# In app.py, after creating the Flask app (after Line 17)

@app.before_request
def before_request():
    """Enforce session timeout."""
    session.permanent = True
    app.permanent_session_lifetime = timedelta(hours=24)

# Also add import at top
from datetime import timedelta
```

---

# SECTION III: CODE QUALITY CONCERNS

## 🟡 CONCERN #11: Insufficient Input Sanitization
**Severity**: LOW-MEDIUM (Security)  
**File**: `app.py`, Multiple routes  
**Impact**: While Flask auto-escapes template output, XSS still possible in edge cases

### Example:
```python
# Line 131 in add_customer()
name = request.form.get('name', '').strip()  # ← Only strips whitespace
```

HTML characters could be injected (though Jinja2 auto-escapes in templates).

### Fix:
```python
# PATCH 17: Add HTML escaping
from markupsafe import escape

# In add_customer()
name = escape(request.form.get('name', '').strip())
```

---

## 🟡 CONCERN #12: No CSRF Protection
**Severity**: LOW (For offline app)  
**File**: `app.py`, All POST routes  
**Impact**: For production, CSRF tokens should be added

### Fix:
```python
# PATCH 18: Add Flask-WTF for CSRF (future enhancement)
# This is NOT required for 4th-semester project but good practice:
# pip install Flask-WTF
# from flask_wtf.csrf import CSRFProtect
# csrf = CSRFProtect(app)
```

---

## 🟡 CONCERN #13: Magic Strings Scattered Throughout Code
**Severity**: LOW (Maintainability)  
**File**: `app.py`  
**Impact**: "credit", "debit", "error", "success" repeated as strings

### Example:
```python
# Line 78, 108, 173, 208, 225, 238, 263, 279
if transaction_type not in ['credit', 'debit']:  # ← Magic string
    flash('Invalid transaction type.', 'error')  # ← Magic string
```

### Fix:
```python
# PATCH 19: Define constants
# Add to top of app.py after imports

TRANSACTION_TYPES = ('credit', 'debit')
FLASH_CATEGORIES = {
    'ERROR': 'error',
    'SUCCESS': 'success',
    'WARNING': 'warning'
}

# Use as:
if transaction_type not in TRANSACTION_TYPES:
    flash('Invalid transaction type.', FLASH_CATEGORIES['ERROR'])
```

---

# SECTION IV: VERIFICATION CHECKLIST

| Check | Status | Notes |
|-------|--------|-------|
| **Syntax Correctness** | ✅ PASS | No Python syntax errors found |
| **SQL Injection Prevention** | ✅ PASS | All queries use parameterized statements |
| **Dead Code** | ⚠️ **FAIL** | Unused `wraps` import in app.py (PATCH 6) |
| **Resource Management** | ❌ **FAIL** | Missing finally blocks (PATCH 4, 5) |
| **Floating Point Arithmetic** | ❌ **FAIL** | Uses float for currency (PATCH 7, 8, 9) |
| **Atomic Transactions** | ❌ **FAIL** | Race condition in delete (PATCH 1, 2, 3) |
| **Error Logging** | ❌ **FAIL** | Silent exception swallowing (PATCH 10, 11) |
| **Balance Validation** | ⚠️ **FAIL** | No boundary checks (PATCH 12) |
| **Database Constraints** | ❌ **FAIL** | Missing CHECK constraints (PATCH 15) |
| **Session Security** | ⚠️ **FAIL** | Timeout not enforced (PATCH 16) |
| **Documentation** | ✅ PASS | Docstrings present and clear |
| **Naming Conventions** | ✅ PASS | PEP 8 compliant |
| **Architecture** | ✅ PASS | Good separation of concerns |

---

# SECTION V: RECOMMENDED FIXES PRIORITY

**Priority 1 (MUST FIX before submission):**
- ✅ DEFECT #1: Race condition in delete_trans (PATCH 1, 2, 3)
- ✅ DEFECT #2: Missing finally blocks (PATCH 4, 5)
- ✅ DEFECT #3: Unused import (PATCH 6)
- ✅ DEFECT #4: Float arithmetic for money (PATCH 7, 8, 9)
- ✅ DEFECT #5: Exception logging (PATCH 10, 11)
- ✅ DEFECT #6: Balance validation (PATCH 12)

**Priority 2 (SHOULD FIX for code quality):**
- Issue #7: Context processor caching (PATCH 13)
- Issue #8: Redundant queries (PATCH 14)
- Issue #9: Database constraints (PATCH 15)
- Issue #10: Session timeout (PATCH 16)

**Priority 3 (NICE-TO-HAVE):**
- Concern #11: HTML sanitization (PATCH 17)
- Concern #12: CSRF protection (PATCH 18)
- Concern #13: Constants instead of magic strings (PATCH 19)

---

# SECTION VI: FINAL VERDICT

### Overall Grade: **B+ (Good Architecture, Implementation Flaws)**

**Status**: ✅ **APPROVED WITH MANDATORY CORRECTIONS**

The application demonstrates:
- ✅ Solid Flask fundamentals
- ✅ Proper database schema design
- ✅ Middleware pattern understanding
- ✅ Session management awareness
- ✅ Security best practices (password hashing, parameterized queries)

However, **6 critical defects must be fixed** before final submission:
1. ❌ Race condition in transaction deletion
2. ❌ Resource leaks in database layer
3. ❌ Unused imports (code smell)
4. ❌ Float arithmetic for currency
5. ❌ Silent exception handling
6. ❌ Missing balance validation

**Estimated Fix Time**: 2-3 hours (all patches provided above)

**Recommendation**: Apply all PATCH items (1-19), run `python -m pytest` if tests are added, and re-submit. With these fixes, this project will achieve **A grade** (Excellent Production-Ready Code).

---

### Examiner Signature
**Senior Software Architect**  
**Academic Review Panel**  
**Date**: 2026-07-15  

---

## Appendix: Quick Reference for Patches

| Patch # | File | Line | Issue | Type |
|---------|------|------|-------|------|
| 1-3 | database.py, app.py | 236-290 | Race condition | CRITICAL |
| 4-5 | database.py | 62-118 | Resource leak | CRITICAL |
| 6 | app.py | 2 | Unused import | CRITICAL |
| 7-9 | app.py, database.py | Multiple | Float arithmetic | CRITICAL |
| 10-11 | app.py | Multiple | Error logging | CRITICAL |
| 12 | app.py | 278-290 | Balance validation | CRITICAL |
| 13 | app.py | 312-316 | Performance | MEDIUM |
| 14 | database.py | 221-228 | Redundant join | MEDIUM |
| 15 | database.py | 23-67 | Schema constraints | MEDIUM |
| 16 | app.py | 17-20 | Session timeout | MEDIUM |
| 17 | app.py | Multiple | HTML sanitization | LOW |
| 18 | app.py | - | CSRF protection | LOW |
| 19 | app.py | 1-20 | Magic strings | LOW |

**All patches are provided with exact code snippets above.**
