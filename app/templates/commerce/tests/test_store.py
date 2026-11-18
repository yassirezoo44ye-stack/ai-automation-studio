"""Test isolated temporary data; never use the live merchant database."""
import importlib
import uuid
from fastapi.testclient import TestClient


def test_checkout_and_admin_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv('STORE_DATABASE', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setenv('STORE_SETUP_FILE', str(tmp_path / 'setup.txt'))
    import main
    store = importlib.reload(main)
    customer = TestClient(store.app)
    assert customer.post('/api/register', json={'email':'buyer@example.com','password':'test customer password','admin':True}).status_code == 201
    assert customer.post('/api/login', json={'email':'buyer@example.com','password':'test customer password'}).status_code == 200
    assert customer.get('/api/me').json()['admin'] == 0
    assert customer.get('/api/admin/orders').status_code == 403
    with store.database() as con:
        con.execute('INSERT INTO products VALUES(?,?,?,?,?,1)', ('p1','Product','Description',1500,1))
    payload = {'request_id':uuid.uuid4().hex,'items':[{'product_id':'p1','quantity':1}],'address':'Valid delivery address','phone':'+971500000000','total':1}
    order = customer.post('/api/orders', json=payload)
    assert order.status_code == 201 and order.json()['total'] == 1500
    assert customer.post('/api/orders', json=payload).json()['id'] == order.json()['id']
    assert customer.get('/api/products').json()[0]['stock'] == 0
    assert TestClient(store.app).get('/api/orders').status_code == 401
