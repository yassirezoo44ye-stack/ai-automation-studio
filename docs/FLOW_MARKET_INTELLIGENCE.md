# Flow Market Intelligence — Phase 1

Research-only, simulation-only module. The paper portfolio is an in-memory prototype, not an authenticated multi-tenant API or production service.

## Implemented
- Deterministic virtual buy/sell fills using Decimal arithmetic.
- Rejects insufficient virtual cash, overselling, invalid values and malformed symbols.
- Equity valuation against supplied price marks.
- Unit tests covering successful and rejected operations.

## Not implemented
Market data ingestion, AI analysis, backtesting, persistent storage, authentication, multi-tenant isolation, dashboards, scheduled jobs, fees/slippage, or live order execution.

## Safety boundary
No brokerage API, wallet, real money movement, or live order placement is provided. Do not expose this prototype as a production trading endpoint.

## Next
Add historical-data ingestion and reproducible backtesting with fees and slippage; then authenticated tenant-isolated persistence and UI behind a feature flag. Keep deployment and merge gated by owner approval.
