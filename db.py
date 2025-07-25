import sqlite3

DB_NAME = "loyalty.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    conn = get_db()
    c = conn.cursor()

    # Add shop name field
    c.execute('''
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            username TEXT UNIQUE,
            password TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER,
            name TEXT,
            phone TEXT,
            points INTEGER DEFAULT 0,
            FOREIGN KEY(shop_id) REFERENCES shops(id)
        )
    ''')
    conn.commit()

    # Insert two sample shops if none exist
    c.execute("SELECT COUNT(*) FROM shops")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO shops (name, username, password) VALUES (?, ?, ?)", 
                  ("Coffee Corner", "coffee", "coffee123"))
        c.execute("INSERT INTO shops (name, username, password) VALUES (?, ?, ?)", 
                  ("Bakery Bliss", "bakery", "bread456"))
    conn.commit()
    conn.close()

def get_shop_by_username(username):
    conn = get_db()
    shop = conn.execute("SELECT * FROM shops WHERE username = ?", (username,)).fetchone()
    conn.close()
    return shop

def get_shop_by_id(shop_id):
    conn = get_db()
    shop = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    conn.close()
    return shop

def add_customer(shop_id, name, phone):
    conn = get_db()
    conn.execute("INSERT INTO customers (shop_id, name, phone, points) VALUES (?, ?, ?, 0)",
                 (shop_id, name, phone))
    conn.commit()
    conn.close()

def get_customers(shop_id):
    conn = get_db()
    customers = conn.execute("SELECT * FROM customers WHERE shop_id = ?", (shop_id,)).fetchall()
    conn.close()
    return customers

def search_customer(shop_id, phone):
    conn = get_db()
    customers = conn.execute("SELECT * FROM customers WHERE shop_id = ? AND phone LIKE ?", 
                             (shop_id, f"%{phone}%")).fetchall()
    conn.close()
    return customers

def get_customer_by_id(customer_id):
    conn = get_db()
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    conn.close()
    return customer
