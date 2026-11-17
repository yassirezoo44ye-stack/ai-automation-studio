"""Deterministic, runnable commerce scaffold; never substitutes for an approved different stack."""
import json
import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / 'templates' / 'commerce'
CONTRACT = 'flow-commerce-cod-v1'


def is_store_request(prompt: str) -> bool:
    text = prompt.lower()
    return bool(re.search(r'متجر|متجراً|متجرا|تجاره الكترونيه|تجارة إلكترونية|e[- ]?commerce|online (?:store|shop)|web ?shop', text))


def store_plan():
    return {
        'name': 'متجر إلكتروني قابل للتشغيل',
        'description': 'واجهة وخلفية وقاعدة بيانات: منتجات وحسابات وسلة وطلبات وإدارة، بالدفع عند الاستلام. لا يشمل بوابة بطاقات أو بريدًا فعليًا.',
        'tech_stack': {'frontend': 'HTML/CSS/JavaScript — Arabic RTL', 'backend': 'Python / FastAPI', 'database': 'SQLite (persistent volume required)'},
        'pages': ['Products', 'Cart and cash-on-delivery checkout', 'Account', 'My orders', 'Admin products and orders'],
        'database_tables': ['users', 'sessions', 'products', 'orders', 'order_items'],
        'api_routes': ['/api/products', '/api/register', '/api/login', '/api/orders', '/api/admin/products', '/api/admin/orders'],
        'agents': [], 'workflows': ['Checkout → validate server prices/stock → durable order', 'Cancel before shipping → restore stock once'],
        'integrations': [], 'estimated_files': len(store_files()), 'complexity': 'moderate',
        'delivery_contract': CONTRACT,
    }


def store_files():
    return {str(path.relative_to(TEMPLATE)): path.read_text(encoding='utf-8') for path in sorted(TEMPLATE.rglob('*')) if path.is_file() and '__pycache__' not in path.parts and 'data' not in path.relative_to(TEMPLATE).parts and not path.name.endswith('.pyc') and path.suffix != '.sqlite3'}


async def store_chunks():
    for path, content in store_files().items():
        yield {'type': 'delta', 'text': f'<<<FILE: {path}>>>\n{content}\n<<<ENDFILE>>>\n'}
    yield {'type': 'delta', 'text': '<<<META>>>\n' + json.dumps({'description': store_plan()['description'], 'run_command': 'python main.py', 'language': 'python'}, ensure_ascii=False) + '\n<<<ENDMETA>>>\n'}


def validate_store_workspace(ws):
    from fastapi import HTTPException
    expected = store_files()
    for name in ('package.json', 'app.py', 'server.py', 'main.py'):
        path = ws / name
        if path.exists() and (name not in expected or path.read_text(encoding='utf-8') != expected[name]):
            raise HTTPException(409, 'Use a new project; existing application files are never replaced silently.')
