from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import sqlite3, qrcode, io, base64, hashlib
from datetime import datetime

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="your-secret-key-here")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------- DB (in-memory, global, persists during app run only) ----------
GLOBAL_CONN = sqlite3.connect(":memory:", check_same_thread=False)
GLOBAL_CONN.row_factory = sqlite3.Row

def get_db_connection():
    return GLOBAL_CONN

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            shop_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (shop_id) REFERENCES shops(id),
            UNIQUE(shop_id, phone)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            points_change INTEGER NOT NULL,
            transaction_type TEXT NOT NULL CHECK(transaction_type IN ('add', 'redeem')),
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)
    # Insert default shop if not exists
    cursor.execute("SELECT COUNT(*) FROM shops WHERE username = 'admin'")
    if cursor.fetchone()[0] == 0:
        hashed_password = hash_password("admin123")
        cursor.execute("INSERT INTO shops (username, password, shop_name) VALUES (?, ?, ?)",
                       ("admin", hashed_password, 'Demo Shop'))
    conn.commit()

init_db()

def get_current_shop(request: Request):
    shop_id = request.session.get("shop_id")
    if not shop_id:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shops WHERE id = ?", (shop_id,))
    shop = cursor.fetchone()
    return dict(shop) if shop else None

def generate_qr_code(shop_id: int) -> str:
    customer_url = f"http://localhost:8000/customer/{shop_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(customer_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='PNG')
    img_str = base64.b64encode(img_buffer.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"

# ------ Shop Side ------
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shops WHERE username = ?", (username,))
    shop = cursor.fetchone()
    if shop and verify_password(password, shop['password']):
        request.session["shop_id"] = shop['id']
        return RedirectResponse(url="/dashboard", status_code=303)
    else:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid username or password"})

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    shop = get_current_shop(request)
    if not shop:
        return RedirectResponse(url="/", status_code=303)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, phone, points, created_at
        FROM customers WHERE shop_id = ? ORDER BY created_at DESC
    """, (shop['id'],))
    customers = [dict(row) for row in cursor.fetchall()]
    for customer in customers:
        if customer['created_at']:
            customer['created_at'] = datetime.fromisoformat(customer['created_at'])
    qr_code = generate_qr_code(shop['id'])
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "shop": shop,
        "customers": customers,
        "qr_code": qr_code
    })

@app.get("/add-customer", response_class=HTMLResponse)
async def add_customer_page(request: Request):
    shop = get_current_shop(request)
    if not shop:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("add_customer.html", {"request": request, "shop": shop})

@app.post("/add-customer")
async def add_customer(request: Request, name: str = Form(...), phone: str = Form(...)):
    shop = get_current_shop(request)
    if not shop:
        return RedirectResponse(url="/", status_code=303)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO customers (shop_id, name, phone, points) VALUES (?, ?, ?, 0)", (shop['id'], name, phone))
        conn.commit()
    except sqlite3.IntegrityError:
        return templates.TemplateResponse("add_customer.html", {
            "request": request,
            "shop": shop,
            "error": "Customer with this phone number already exists"
        })
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/customer-profile/{customer_id}", response_class=HTMLResponse)
async def customer_profile(request: Request, customer_id: int):
    shop = get_current_shop(request)
    if not shop:
        return RedirectResponse(url="/", status_code=303)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE id = ? AND shop_id = ?", (customer_id, shop['id']))
    customer = cursor.fetchone()
    if not customer:
        return RedirectResponse(url="/dashboard", status_code=303)
    customer = dict(customer)
    cursor.execute("SELECT * FROM transactions WHERE customer_id = ? ORDER BY created_at DESC LIMIT 10", (customer_id,))
    transactions = [dict(row) for row in cursor.fetchall()]
    return templates.TemplateResponse("customer_profile.html", {
        "request": request,
        "shop": shop,
        "customer": customer,
        "transactions": transactions
    })

@app.post("/add-points/{customer_id}")
async def add_points(request: Request, customer_id: int, points: int = Form(...), description: str = Form("")):
    shop = get_current_shop(request)
    if not shop:
        return RedirectResponse(url="/", status_code=303)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE customers SET points = points + ? WHERE id = ? AND shop_id = ?", (points, customer_id, shop['id']))
    cursor.execute(
        "INSERT INTO transactions (customer_id, points_change, transaction_type, description) VALUES (?, ?, 'add', ?)",
        (customer_id, points, description or f"Added {points} points"))
    conn.commit()
    return RedirectResponse(url=f"/customer-profile/{customer_id}", status_code=303)

@app.post("/redeem-points/{customer_id}")
async def redeem_points(request: Request, customer_id: int, points: int = Form(...), description: str = Form("")):
    shop = get_current_shop(request)
    if not shop:
        return RedirectResponse(url="/", status_code=303)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT points FROM customers WHERE id = ? AND shop_id = ?", (customer_id, shop['id']))
    result = cursor.fetchone()
    if not result or result['points'] < points:
        return RedirectResponse(url=f"/customer-profile/{customer_id}?error=insufficient", status_code=303)
    cursor.execute("UPDATE customers SET points = points - ? WHERE id = ? AND shop_id = ?", (points, customer_id, shop['id']))
    cursor.execute(
        "INSERT INTO transactions (customer_id, points_change, transaction_type, description) VALUES (?, ?, 'redeem', ?)",
        (customer_id, -points, description or f"Redeemed {points} points"))
    conn.commit()
    return RedirectResponse(url=f"/customer-profile/{customer_id}", status_code=303)

# ------ Customer Side ------
@app.get("/customer/{shop_id}", response_class=HTMLResponse)
async def customer_page(request: Request, shop_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shops WHERE id = ?", (shop_id,))
    shop = cursor.fetchone()
    if not shop:
        return HTMLResponse("Shop not found", status_code=404)
    return templates.TemplateResponse("customer_login.html", {"request": request, "shop": dict(shop)})

@app.post("/customer/{shop_id}/check-points")
async def check_customer_points(request: Request, shop_id: int, phone: str = Form(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shops WHERE id = ?", (shop_id,))
    shop = cursor.fetchone()
    if not shop:
        return HTMLResponse("Shop not found", status_code=404)
    shop = dict(shop)
    cursor.execute("SELECT * FROM customers WHERE shop_id = ? AND phone = ?", (shop_id, phone))
    customer = cursor.fetchone()
    if not customer:
        return templates.TemplateResponse("customer_login.html", {
            "request": request,
            "shop": shop,
            "error": "Customer not found. Please contact the shop to register."
        })
    customer = dict(customer)
    cursor.execute("SELECT * FROM transactions WHERE customer_id = ? ORDER BY created_at DESC LIMIT 5", (customer['id'],))
    transactions = [dict(row) for row in cursor.fetchall()]
    return templates.TemplateResponse("customer_points.html", {
        "request": request,
        "shop": shop,
        "customer": customer,
        "transactions": transactions
    })

# Run the app:
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
