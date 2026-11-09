from app.core.chat.prompt_contract import (
    MAX_PROMPT_CHARACTERS,
    measure_prompt,
    prompt_limit_message,
)


def test_prompt_budget_accepts_exact_limit_without_mutating_text():
    original = "  Arabic\n```py\nprint('flow')\n```  "
    budget = measure_prompt(original, maximum=len(original))

    assert budget.accepted is True
    assert budget.characters == len(original)
    assert budget.remaining == 0
    assert original == "  Arabic\n```py\nprint('flow')\n```  "


def test_prompt_budget_rejects_over_limit_and_explains_recovery():
    original = "سياق\n" + "x" * (MAX_PROMPT_CHARACTERS + 1)
    budget = measure_prompt(original)

    assert budget.accepted is False
    assert budget.characters == len(original)
    assert budget.remaining == 0
    message = prompt_limit_message(budget)
    assert "Your text has not been changed" in message
    assert "attach the reference as a file" in message
    assert "split the request into linked parts" in message


def test_prompt_budget_counts_newlines_and_unicode_as_entered():
    text = "العربية\r\ncode\t🧭"
    budget = measure_prompt(text)

    assert budget.characters == len(text)
    assert budget.accepted is True


def test_prompt_budget_rejects_invalid_limit():
    try:
        measure_prompt("prompt", maximum=0)
    except ValueError as exc:
        assert str(exc) == "maximum must be positive"
    else:
        raise AssertionError("Expected an invalid budget to be rejected")
