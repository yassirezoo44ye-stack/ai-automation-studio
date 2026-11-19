"""Run on the store host: python store_admin.py create-admin"""
import getpass
import secrets
import sys
from main import SETUP, database, encode_password

if __name__ == '__main__':
    if sys.argv[1:] != ['create-admin']:
        raise SystemExit('Usage: python store_admin.py create-admin')
    email = input('Admin email: ').strip().lower()
    password = getpass.getpass('Password (at least 10 characters): ')
    if '@' not in email or len(password) < 10:
        raise SystemExit('Valid email and at least 10 password characters required')
    with database() as con:
        existing = con.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        if existing:
            con.execute('DELETE FROM sessions WHERE user_id=?', (existing['id'],))
            con.execute('UPDATE users SET admin=1,password=? WHERE id=?', (encode_password(password), existing['id']))
        else:
            con.execute('INSERT INTO users VALUES(?,?,?,1)', (secrets.token_hex(16), email, encode_password(password)))
    SETUP.unlink(missing_ok=True)
    print('Administrator ready. Sign in through the storefront.')
