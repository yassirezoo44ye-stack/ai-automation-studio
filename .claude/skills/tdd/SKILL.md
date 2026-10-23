---
name: tdd
description: >
  Apply Test-Driven Development to the Flow project. Use when asked to:
  write tests before fixing a bug, add test coverage to untested code,
  verify a fix with a failing test first, or follow a red-green-refactor
  cycle. Trigger phrases: "TDD", "test first", "write a failing test",
  "add test coverage", "test this", "cover this with tests", "red-green",
  "test-driven", "before we fix", "reproduce with a test".
  Do NOT generate blanket test files for entire modules without a specific
  behaviour to verify. Do NOT modify production code until a failing test
  exists that justifies the change.
---

# TDD Skill — Flow Project

## Test Stacks

| Layer | Framework | Config | Run command |
|-------|-----------|--------|-------------|
| Backend (Python) | pytest + pytest-asyncio | `pytest.ini` / `pyproject.toml` | `python -m pytest tests/<file> -q --tb=short` |
| Frontend (TypeScript/React) | Vitest + Testing Library | `vitest.config.ts` | `npm run test -- --run <file>` |

## The Red-Green-Refactor Cycle

### Step 1 — RED: Write a failing test

Before any production code change:

1. Identify the specific behaviour to verify (one behaviour per test).
2. Write the smallest test that fails for the right reason.
3. Run it and confirm it fails with a meaningful assertion error — not an import error, not a crash.
4. Show the failure output to the user before proceeding.

**A test that passes before the fix is NOT a useful test.** If the test already passes, either the bug is already fixed, or the test doesn't exercise the right behaviour. Stop and investigate.

### Step 2 — GREEN: Implement the minimal fix

Write the smallest production code change that makes the failing test pass.
Do not add unrelated improvements during this step — that belongs in Refactor.

Run the test again. Confirm it passes.

### Step 3 — REFACTOR: Clean up without breaking tests

With green tests as a safety net:
- Remove duplication.
- Rename variables/functions for clarity.
- Extract helpers if a function is now too long.

Run the full relevant test suite after refactoring. All tests must still pass.

## Test Writing Standards

### Backend (pytest)

```python
# One test = one behaviour. Name the test so it reads as a sentence.
# bad:  test_login()
# good: test_login_returns_401_for_wrong_password()

async def test_login_returns_401_for_wrong_password(client, test_user):
    response = await client.post("/api/auth/login", json={
        "email": test_user["email"],
        "password": "wrong-password"
    })
    assert response.status_code == 401
    assert "Invalid" in response.json()["detail"]
```

Rules:
- Use `pytest.mark.asyncio` for async tests.
- Use fixtures from `conftest.py` for DB state — never hardcode test data inline.
- Org-scoped data: always create via an org fixture, never share state between tests.
- No `time.sleep()` — use `asyncio.wait_for` with a timeout or mock time.
- Assert the exact HTTP status code, not just `!= 200`.
- One `assert` per logical outcome (multiple asserts on the same response object is fine).

### Frontend (Vitest + Testing Library)

```typescript
// Test user-observable behaviour, not implementation details.
// bad:  expect(component.state.isLoading).toBe(true)
// good: expect(screen.getByRole('progressbar')).toBeInTheDocument()

it('shows an error message when login fails', async () => {
  server.use(
    http.post('/api/auth/login', () => HttpResponse.json({ detail: 'Invalid email or password' }, { status: 401 }))
  );
  render(<LoginPage />);
  await userEvent.type(screen.getByLabelText(/email/i), 'bad@example.com');
  await userEvent.type(screen.getByLabelText(/password/i), 'wrong');
  await userEvent.click(screen.getByRole('button', { name: /log in/i }));
  expect(await screen.findByText(/invalid email or password/i)).toBeInTheDocument();
});
```

Rules:
- Use `screen` queries, not container queries.
- Prefer `getByRole` > `getByLabelText` > `getByTestId` (last resort).
- Mock API calls with MSW (`src/mocks/`) — do not mock fetch/axios directly.
- `findBy*` for async elements; `getBy*` for elements that must already be present.
- Do not test internal React state — test what the user sees and can do.
- Keep test files co-located with the component or in `tests/` following the existing pattern.

## Regression Testing Protocol

After a fix, always run:

1. **Targeted test**: the specific new test(s) for the fix.
2. **File-level tests**: all tests in the same file as the changed module.
3. **Integration tests**: any test that exercises the endpoint/component end-to-end.
4. **Full suite** (if time permits, or before committing): `python -m pytest tests/ -q` and `npm run test -- --run`.

Report: tests passed / failed / skipped, and any new failures introduced by the fix.

## What This Skill Does NOT Do

- Does not generate test files for entire modules speculatively.
- Does not skip the RED step ("I'll write the test after the fix").
- Does not mock away the thing being tested.
- Does not introduce artificial failures into production code to demonstrate TDD.
- Does not count a pre-existing passing test as evidence a fix is needed.
