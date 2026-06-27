#!/usr/bin/env python3
"""Unit tests for calculator.py"""

import pytest
from calculator import add, subtract, multiply, divide


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------
class TestAdd:
    def test_positive_numbers(self):
        assert add(3, 5) == 8

    def test_negative_numbers(self):
        assert add(-4, -6) == -10

    def test_mixed_sign(self):
        assert add(-3, 7) == 4

    def test_floats(self):
        assert add(1.5, 2.5) == pytest.approx(4.0)

    def test_zero(self):
        assert add(0, 0) == 0


# ---------------------------------------------------------------------------
# subtract
# ---------------------------------------------------------------------------
class TestSubtract:
    def test_positive_numbers(self):
        assert subtract(10, 4) == 6

    def test_negative_result(self):
        assert subtract(3, 7) == -4

    def test_floats(self):
        assert subtract(5.5, 2.2) == pytest.approx(3.3)

    def test_same_numbers(self):
        assert subtract(9, 9) == 0


# ---------------------------------------------------------------------------
# multiply
# ---------------------------------------------------------------------------
class TestMultiply:
    def test_positive_numbers(self):
        assert multiply(3, 4) == 12

    def test_by_zero(self):
        assert multiply(99, 0) == 0

    def test_negative_numbers(self):
        assert multiply(-3, -4) == 12

    def test_mixed_sign(self):
        assert multiply(-3, 4) == -12

    def test_floats(self):
        assert multiply(2.5, 4) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# divide
# ---------------------------------------------------------------------------
class TestDivide:
    def test_even_division(self):
        assert divide(10, 2) == 5.0

    def test_float_result(self):
        assert divide(7, 2) == pytest.approx(3.5)

    def test_negative_divisor(self):
        assert divide(10, -2) == -5.0

    def test_both_negative(self):
        assert divide(-10, -2) == 5.0

    def test_divide_by_zero_raises(self):
        with pytest.raises(ValueError, match="Division by zero"):
            divide(5, 0)

    def test_divide_zero_numerator(self):
        assert divide(0, 5) == 0.0
