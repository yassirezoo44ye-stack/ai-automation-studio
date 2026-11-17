# Runnable Flow Store

This is a real single-store application: HTML/CSS/JS frontend, FastAPI REST backend,
SQLite persistence, customer accounts, cart, server-priced orders, stock control,
order history and role-protected product/order administration. No AI/provider API
key is needed to run it. No demo orders, simulated payments or hardcoded passwords.

## Run

Python 3.11+: `python -m pip install -r requirements.txt`

Start: `python main.py`

Open http://localhost:8000. Flow's Run action detects FastAPI and serves this same
application through its project proxy. The initial product list is deliberately
empty. On first Run, the host writes a private data/owner-setup.txt token (0600).
The authenticated Flow project owner can retrieve it with Store setup, or read it
on the private host. In Account, open
owner setup, enter that one-time token and choose your email/password. The token
is never sent by the public storefront API, is stored only as a hash and is consumed under a
database transaction. Restarting an unconfigured store rotates it. Alternatively
run `python store_admin.py create-admin` on your own store host. Sign in and add
your actual products/prices/stock. Customer registration never grants admin rights.
Prices in the API are integer minor units (100 = 1 AED). STORE_CURRENCY defaults AED.
Data lives in data/store.sqlite3; mount a persistent volume and back it up.

## Actual checkout / revenue

Cash on delivery creates a durable order and reserves stock atomically. The
merchant confirms, ships and marks delivery; cancellation before shipping restores
stock exactly once. Successful order creation is NOT online payment or proof of
revenue. You must supply actual products, delivery, collection, return/tax policies
and business details. There is no income guarantee.

Card/Stripe/Payfort, email, SMS, tax calculation and shipping-provider integrations
are NOT implemented or enabled. Never enter card details here. Connect and test
these services before advertising them. This scaffold does not claim to implement
an earlier plan that listed those external services or a different technology stack.

## Hosting

Environment variables are read from the process, not automatically from .env files.
Set STORE_PUBLIC_ORIGIN to your exact HTTPS store origin and STORE_SECURE_COOKIES=1
for HTTPS. Configure TLS, a persistent database volume, request/login rate limits,
monitoring and backups on the host. This lightweight SQLite deployment is intended
for a single store instance; use a managed database before horizontal scaling.
Keep the store on its own origin in production. Flow preview is authenticated and
is not a publicly deployed business storefront. Deploy/export explicitly to sell.

Session cookies are HTTP-only and SameSite=Lax; only hashed session tokens are
stored. Passwords use salted PBKDF2. Admin creation requires host access; API
registration cannot set role/price/stock/order owner. Customer order queries are
owner-scoped. Browser writes require same-origin JSON requests. Install `requirements-dev.txt` and run `python -m pytest tests` before accepting live traffic.
