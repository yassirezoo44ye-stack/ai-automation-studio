"""Exercise the exported store against SQLite, including adversarial checkout paths."""
import importlib.util
import shutil
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from app.core.commerce_builder import CONTRACT, TEMPLATE, is_store_request, store_files, store_plan


@pytest.fixture
def store(tmp_path, monkeypatch):
    folder = tmp_path / 'export'
    shutil.copytree(TEMPLATE, folder, ignore=shutil.ignore_patterns('__pycache__', '*.sqlite3'))
    monkeypatch.setenv('STORE_DATABASE', str(tmp_path / 'store.sqlite3'))
    monkeypatch.delenv('STORE_PUBLIC_ORIGIN', raising=False)
    name = 'exported_store_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, folder / 'main.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    with module.database() as con:
        con.execute('INSERT INTO users VALUES(?,?,?,1)', ('admin', 'admin@example.com', module.encode_password('Admin test password')))
    admin = TestClient(module.app)
    assert admin.post('/api/login', json={'email': 'admin@example.com', 'password': 'Admin test password'}).status_code == 200
    pid = admin.post('/api/admin/products', json={'title': 'Real product', 'description': '<script>not HTML</script>', 'price': 1250, 'stock': 2}).json()['id']
    customer = TestClient(module.app)
    assert customer.post('/api/register', json={'email': 'buyer@example.com', 'password': 'Customer test password', 'admin': True}).status_code == 201
    assert customer.post('/api/login', json={'email': 'buyer@example.com', 'password': 'Customer test password'}).status_code == 200
    yield module, admin, customer, pid
    sys.modules.pop(name, None)


def body(pid, qty=1, **extra):
    return {'request_id': uuid.uuid4().hex, 'items': [{'product_id': pid, 'quantity': qty}], 'address': 'Valid delivery address', 'phone': '+971500000000', **extra}


def test_store_intent_and_plan_are_concrete():
    assert is_store_request('صمم متجر إلكتروني')
    assert is_store_request('Build an e-commerce store')
    assert not is_store_request('Build a timer')
    plan = store_plan()
    assert plan['delivery_contract'] == CONTRACT
    assert plan['tech_stack']['backend'] == 'Python / FastAPI'
    assert plan['integrations'] == []
    assert len(store_files()) == plan['estimated_files']
    assert not any('.sqlite3' in p or '__pycache__' in p for p in store_files())


def test_export_has_real_frontend_backend_and_admin_boundaries(store):
    module, admin, customer, pid = store
    assert customer.get('/').status_code == 200
    assert customer.get('/assets/app.js').status_code == 200
    assert customer.get('/api/health').json()['checkout'] == 'cash_on_delivery'
    assert customer.get('/api/products').json()[0]['id'] == pid
    assert customer.get('/api/me').json()['admin'] == 0
    assert customer.post('/api/admin/products', json={'title': 'X', 'price': 1, 'stock': 1}).status_code == 403
    assert TestClient(module.app).get('/api/orders').status_code == 401
    assert admin.get('/api/admin/products').status_code == 200


def test_checkout_server_prices_idempotency_and_owner_isolation(store):
    module, admin, customer, pid = store
    payload = body(pid, price=1, total=1, user_id='admin')
    result = customer.post('/api/orders', json=payload)
    assert result.status_code == 201
    assert result.json()['total'] == 1250
    assert customer.post('/api/orders', json=payload).json()['id'] == result.json()['id']
    assert customer.get('/api/products').json()[0]['stock'] == 1
    assert admin.get('/api/orders').json() == []
    assert len(customer.get('/api/orders').json()) == 1
    assert customer.post('/api/orders', json=payload | {'address': 'A different valid address'}).status_code == 409
    assert len(admin.get('/api/admin/orders').json()) == 1
    # A new process/session sees persisted data, not a browser-only demo.
    other = TestClient(module.app)
    other.post('/api/login', json={'email': 'buyer@example.com', 'password': 'Customer test password'})
    assert other.get('/api/orders').json()[0]['id'] == result.json()['id']


def test_transaction_stock_and_repeated_cancellation(store):
    _, admin, customer, pid = store
    assert customer.post('/api/orders', json=body(pid,3)).status_code == 409
    order = customer.post('/api/orders', json=body(pid,2)).json()
    assert customer.get('/api/products').json()[0]['stock'] == 0
    assert customer.post('/api/orders', json=body(pid)).status_code == 409
    assert admin.patch('/api/admin/orders/' + order['id'], json={'status': 'cancelled'}).status_code == 200
    assert admin.patch('/api/admin/orders/' + order['id'], json={'status': 'cancelled'}).status_code == 200
    assert customer.get('/api/products').json()[0]['stock'] == 2
    assert admin.patch('/api/admin/orders/' + order['id'], json={'status': 'shipped'}).status_code == 409


def test_concurrent_buyers_cannot_oversell(store):
    _, admin, customer, pid = store
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: customer.post('/api/orders', json=body(pid,2)).status_code, range(2)))
    assert sorted(statuses) == [201,409]
    assert customer.get('/api/products').json()[0]['stock'] == 0


def test_csrf_passwords_and_login_limit(store):
    module, _, customer, pid = store
    assert customer.post('/api/orders', json=body(pid), headers={'origin': 'https://attacker.example'}).status_code == 403
    assert customer.post('/api/orders', content='items=x').status_code == 415
    with module.database() as con:
        password = con.execute('SELECT password FROM users WHERE email=?', ('buyer@example.com',)).fetchone()[0]
        assert password != 'Customer test password'
    attacker = TestClient(module.app)
    for _ in range(5):
        assert attacker.post('/api/login', json={'email':'buyer@example.com','password':'incorrect password'}).status_code == 401
    assert attacker.post('/api/login', json={'email':'buyer@example.com','password':'incorrect password'}).status_code == 429
    assert customer.get('/api/me').status_code == 200
    with module.database() as con:
        tokens = [row[0] for row in con.execute('SELECT token FROM sessions')]
    assert customer.cookies.get('flow_store_session') not in tokens


def test_export_routes_through_python_server_detector(tmp_path):
    from app.execution.detector import detect
    for path, content in store_files().items():
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    info = detect(tmp_path)
    assert info.project_type == 'fastapi'
    assert info.run_strategy == 'server'


def test_one_time_bootstrap_requires_private_host_token(tmp_path, monkeypatch):
    folder = tmp_path / 'bootstrap'
    shutil.copytree(TEMPLATE, folder, ignore=shutil.ignore_patterns('__pycache__', '*.sqlite3', 'data'))
    monkeypatch.setenv('STORE_DATABASE', str(tmp_path / 'bootstrap.sqlite3'))
    name = 'bootstrap_store_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, folder / 'main.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = TestClient(module.app)
    secret = folder / 'data' / 'owner-setup.txt'
    token = secret.read_text()
    assert secret.stat().st_mode & 0o777 == 0o600
    assert client.get('/api/health').json()['setup_required'] is True
    assert token not in client.get('/api/health').text
    old_session = TestClient(module.app)
    old_session.post('/api/register', json={'email':'owner@example.com','password':'Old customer password'})
    old_session.post('/api/login', json={'email':'owner@example.com','password':'Old customer password'})
    payload = {'email':'owner@example.com','password':'Owner test password','token':'x'*43}
    assert client.post('/api/setup', json=payload).status_code == 403
    assert client.post('/api/setup', json=payload | {'token':token}).status_code == 201
    assert not secret.exists()
    assert old_session.get('/api/me').status_code == 401
    assert client.post('/api/setup', json=payload | {'token':token}).status_code == 409
    assert client.post('/api/login', json={'email':'owner@example.com','password':'Owner test password'}).status_code == 200
    assert client.get('/api/me').json()['admin'] == 1
