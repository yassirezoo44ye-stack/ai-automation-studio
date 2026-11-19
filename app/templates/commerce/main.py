"""Runnable single-store commerce application. Prices are integer minor units."""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DB = Path(os.getenv('STORE_DATABASE', str(ROOT / 'data' / 'store.sqlite3')))
SETUP = Path(os.getenv('STORE_SETUP_FILE', str(ROOT / 'data' / 'owner-setup.txt')))
app = FastAPI(title='Flow Store')
app.mount('/assets', StaticFiles(directory=ROOT / 'assets'), name='assets')


@contextmanager
def database():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def initialize():
    with database() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,admin INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS setup(token TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS login_attempts(identity TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,price INTEGER NOT NULL CHECK(price>=0),stock INTEGER NOT NULL CHECK(stock>=0),active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),total INTEGER NOT NULL,currency TEXT NOT NULL,address TEXT NOT NULL,phone TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',request_id TEXT NOT NULL,created INTEGER NOT NULL,UNIQUE(user_id,request_id));
        CREATE TABLE IF NOT EXISTS order_items(order_id TEXT REFERENCES orders(id),product_id TEXT REFERENCES products(id),title TEXT NOT NULL,price INTEGER NOT NULL,quantity INTEGER NOT NULL);
        ''')
        if con.execute('SELECT COUNT(*) FROM users WHERE admin=1').fetchone()[0] == 0:
            token = secrets.token_urlsafe(32)
            con.execute('DELETE FROM setup')
            con.execute('INSERT INTO setup VALUES(?)', (hashlib.sha256(token.encode()).hexdigest(),))
            setup_path = SETUP
            setup_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(setup_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            if hasattr(os, 'fchmod'):
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, 'w') as secret_file:
                secret_file.write(token)
            print('Owner setup is ready. Open data/owner-setup.txt on the private host or use Flow store setup.', flush=True)


def encode_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 310000).hex()
    return f'{salt}${digest}'


def valid_password(password, stored):
    salt, digest = stored.split('$')
    return hmac.compare_digest(digest, hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 310000).hex())


@app.middleware('http')
async def security(request: Request, call_next):
    # Browser writes must originate from the served store; JSON prevents form CSRF.
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        origin = request.headers.get('origin')
        expected = os.getenv('STORE_PUBLIC_ORIGIN', str(request.base_url).rstrip('/'))
        if request.client and request.client.host in ('127.0.0.1', '::1') and request.headers.get('x-flow-preview-origin'):
            expected = request.headers['x-flow-preview-origin']
        if origin and origin.rstrip('/') != expected.rstrip('/'):
            return Response('Origin rejected', status_code=403)
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            return Response('JSON required', status_code=415)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'self'"
    return response


def identity(request: Request):
    token = request.cookies.get('flow_store_session', '')
    with database() as con:
        row = con.execute('SELECT u.id,u.email,u.admin FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?', (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
    if row is None:
        raise HTTPException(401, 'Sign in first')
    return dict(row)


def administrator(user=Depends(identity)):
    if not user['admin']:
        raise HTTPException(403, 'Administrator required')
    return user


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)


class ProductInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default='', max_length=4000)
    price: int = Field(ge=0, le=100000000, strict=True)
    stock: int = Field(ge=0, le=1000000, strict=True)
    active: bool = True


class Item(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=100, strict=True)


class Checkout(BaseModel):
    items: list[Item] = Field(min_length=1, max_length=50)
    address: str = Field(min_length=10, max_length=1000)
    phone: str = Field(min_length=7, max_length=40)
    request_id: str = Field(min_length=16, max_length=100)


@app.get('/')
def storefront():
    return FileResponse(ROOT / 'index.html')


@app.get('/api/health')
def health():
    with database() as con:
        con.execute('SELECT 1')
        return {'status': 'ready', 'checkout': 'cash_on_delivery', 'currency': os.getenv('STORE_CURRENCY', 'AED'), 'setup_required': con.execute('SELECT COUNT(*) FROM users WHERE admin=1').fetchone()[0] == 0}


class SetupInput(Credentials):
    token: str = Field(min_length=32, max_length=200)


@app.post('/api/setup', status_code=201)
def setup_store(body: SetupInput):
    email = body.email.strip().lower()
    if '@' not in email or '.' not in email.split('@')[-1]:
        raise HTTPException(422, 'Valid email required')
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT COUNT(*) FROM users WHERE admin=1').fetchone()[0]:
            raise HTTPException(409, 'Store owner already configured')
        row = con.execute('SELECT token FROM setup').fetchone()
        if not row or not hmac.compare_digest(row['token'], hashlib.sha256(body.token.encode()).hexdigest()):
            raise HTTPException(403, 'Private host setup token required')
        # Host possession is needed to initialize ownership; ordinary signup never grants it.
        existing = con.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        if existing:
            con.execute('DELETE FROM sessions WHERE user_id=?', (existing['id'],))
            con.execute('UPDATE users SET admin=1,password=? WHERE id=?', (encode_password(body.password), existing['id']))
        else:
            con.execute('INSERT INTO users VALUES(?,?,?,1)', (secrets.token_hex(16), email, encode_password(body.password)))
        con.execute('DELETE FROM setup')
    SETUP.unlink(missing_ok=True)
    return {'configured': True}


@app.get('/api/me')
def me(user=Depends(identity)):
    return user


@app.post('/api/register', status_code=201)
def register(body: Credentials):
    email = body.email.strip().lower()
    if '@' not in email or '.' not in email.split('@')[-1]:
        raise HTTPException(422, 'Valid email required')
    try:
        with database() as con:
            con.execute('INSERT INTO users(id,email,password) VALUES(?,?,?)', (secrets.token_hex(16), email, encode_password(body.password)))
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'Email already registered') from None
    return {'registered': True}


@app.post('/api/login')
def login(body: Credentials, response: Response, request: Request):
    bucket = hashlib.sha256((body.email.strip().lower() + ':' + (request.client.host if request.client else '')).encode()).hexdigest()
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('DELETE FROM login_attempts WHERE created<?', (int(time.time()) - 900,))
        if con.execute('SELECT COUNT(*) FROM login_attempts WHERE identity=?', (bucket,)).fetchone()[0] >= 5:
            raise HTTPException(429, 'Too many login attempts; retry in 15 minutes')
        row = con.execute('SELECT * FROM users WHERE email=?', (body.email.strip().lower(),)).fetchone()
        # Also perform the hash for unknown users to avoid trivial timing enumeration.
        stored = row['password'] if row else '0' * 32 + '$' + '0' * 64
        if not valid_password(body.password, stored) or row is None:
            con.execute('INSERT INTO login_attempts VALUES(?,?)', (bucket, int(time.time())))
            con.commit()
            raise HTTPException(401, 'Invalid credentials')
        con.execute('DELETE FROM login_attempts WHERE identity=?', (bucket,))
        token = secrets.token_urlsafe(32)
        con.execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
        con.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), row['id'], int(time.time()) + 86400))
    response.set_cookie('flow_store_session', token, httponly=True, samesite='lax', secure=os.getenv('STORE_SECURE_COOKIES', '0') == '1', max_age=86400)
    return {'email': row['email'], 'admin': bool(row['admin'])}


@app.post('/api/logout')
def logout(request: Request, response: Response):
    token = request.cookies.get('flow_store_session', '')
    with database() as con:
        con.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie('flow_store_session')
    return {'signed_out': True}


@app.get('/api/products')
def products():
    with database() as con:
        return [dict(row) for row in con.execute('SELECT * FROM products WHERE active=1 ORDER BY title')]


@app.get('/api/admin/products')
def admin_products(user=Depends(administrator)):
    with database() as con:
        return [dict(row) for row in con.execute('SELECT * FROM products ORDER BY title')]


@app.post('/api/admin/products', status_code=201)
def create_product(body: ProductInput, user=Depends(administrator)):
    pid = secrets.token_hex(16)
    with database() as con:
        con.execute('INSERT INTO products VALUES(?,?,?,?,?,?)', (pid, body.title, body.description, body.price, body.stock, int(body.active)))
    return {'id': pid}


@app.put('/api/admin/products/{pid}')
def update_product(pid: str, body: ProductInput, user=Depends(administrator)):
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        cursor = con.execute('UPDATE products SET title=?,description=?,price=?,stock=?,active=? WHERE id=?', (body.title, body.description, body.price, body.stock, int(body.active), pid))
        if not cursor.rowcount:
            raise HTTPException(404, 'Product not found')
    return {'updated': True}


@app.get('/api/orders')
def orders(user=Depends(identity)):
    with database() as con:
        rows = con.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created DESC', (user['id'],)).fetchall()
        return [dict(row) | {'items': [dict(i) for i in con.execute('SELECT * FROM order_items WHERE order_id=?', (row['id'],))]} for row in rows]


@app.post('/api/orders', status_code=201)
def checkout(body: Checkout, user=Depends(identity)):
    quantities = {}
    for item in body.items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
    if any(q > 100 for q in quantities.values()):
        raise HTTPException(422, 'At most 100 of each product')
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        previous = con.execute('SELECT * FROM orders WHERE user_id=? AND request_id=?', (user['id'], body.request_id)).fetchone()
        if previous:
            original = {r['product_id']: r['quantity'] for r in con.execute('SELECT product_id,quantity FROM order_items WHERE order_id=?', (previous['id'],))}
            if original != quantities or previous['address'] != body.address or previous['phone'] != body.phone:
                raise HTTPException(409, 'Request ID already used for a different order')
            return dict(previous)
        selected = []
        for pid, quantity in quantities.items():
            row = con.execute('SELECT * FROM products WHERE id=? AND active=1', (pid,)).fetchone()
            if row is None or row['stock'] < quantity:
                raise HTTPException(409, 'Product unavailable or insufficient stock')
            selected.append((row, quantity))
        total = sum(row['price'] * quantity for row, quantity in selected)
        oid = secrets.token_hex(16)
        currency = os.getenv('STORE_CURRENCY', 'AED')
        con.execute('INSERT INTO orders(id,user_id,total,currency,address,phone,request_id,created) VALUES(?,?,?,?,?,?,?,?)', (oid, user['id'], total, currency, body.address, body.phone, body.request_id, int(time.time())))
        for row, quantity in selected:
            con.execute('UPDATE products SET stock=stock-? WHERE id=?', (quantity, row['id']))
            con.execute('INSERT INTO order_items VALUES(?,?,?,?,?)', (oid, row['id'], row['title'], row['price'], quantity))
    return {'id': oid, 'total': total, 'currency': currency, 'status': 'pending'}


@app.get('/api/admin/orders')
def admin_orders(user=Depends(administrator)):
    with database() as con:
        return [dict(row) | {'items': [dict(i) for i in con.execute('SELECT * FROM order_items WHERE order_id=?', (row['id'],))]} for row in con.execute('SELECT * FROM orders ORDER BY created DESC LIMIT 200')]


class StatusInput(BaseModel):
    status: str = Field(pattern='^(confirmed|shipped|delivered|cancelled)$')


@app.patch('/api/admin/orders/{oid}')
def order_status(oid: str, body: StatusInput, user=Depends(administrator)):
    allowed = {'pending': {'confirmed', 'cancelled'}, 'confirmed': {'shipped', 'cancelled'}, 'shipped': {'delivered'}, 'delivered': set(), 'cancelled': set()}
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Order not found')
        if row['status'] == body.status:
            return {'status': body.status}
        if body.status not in allowed[row['status']]:
            raise HTTPException(409, 'Invalid order transition')
        if body.status == 'cancelled':
            for item in con.execute('SELECT product_id,quantity FROM order_items WHERE order_id=?', (oid,)):
                con.execute('UPDATE products SET stock=stock+? WHERE id=?', (item['quantity'], item['product_id']))
        con.execute('UPDATE orders SET status=? WHERE id=?', (body.status, oid))
    return {'status': body.status}


initialize()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
