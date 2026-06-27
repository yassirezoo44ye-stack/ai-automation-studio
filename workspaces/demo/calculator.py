#!/usr/bin/env python3
"""Command-line calculator supporting add, subtract, multiply, and divide operations."""

import argparse
import sys


def add(a: float, b: float) -> float:
    """Return the sum of a and b."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return the difference of a and b."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of a and b."""
    return a * b


def divide(a: float, b: float) -> float:
    """Return the quotient of a and b. Raises ValueError on division by zero."""
    if b == 0:
        raise ValueError("Division by zero is not allowed.")
    return a / b


OPERATIONS = {
    "add":      add,
    "subtract": subtract,
    "multiply": multiply,
    "divide":   divide,
}

OP_SYMBOLS = {
    "add":      "+",
    "subtract": "-",
    "multiply": "×",
    "divide":   "÷",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="calculator",
        description="A command-line calculator that performs basic arithmetic operations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python calculator.py add 10 5          ->  10 + 5 = 15.0\n"
            "  python calculator.py subtract 10 5     ->  10 - 5 = 5.0\n"
            "  python calculator.py multiply 4 7      ->  4 × 7 = 28.0\n"
            "  python calculator.py divide 20 4       ->  20 ÷ 4 = 5.0\n"
            "  python calculator.py add 1.5 2.3       ->  1.5 + 2.3 = 3.8\n"
        ),
    )

    parser.add_argument(
        "operation",
        choices=list(OPERATIONS.keys()),
        metavar="operation",
        help="arithmetic operation to perform: add | subtract | multiply | divide",
    )

    parser.add_argument(
        "a",
        type=float,
        metavar="NUM1",
        help="first operand (integer or float)",
    )

    parser.add_argument(
        "b",
        type=float,
        metavar="NUM2",
        help="second operand (integer or float)",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="show a detailed expression instead of just the result",
    )

    return parser


def format_number(n: float) -> str:
    """Return an int-style string when the value is a whole number, else float."""
    return str(int(n)) if n == int(n) else str(n)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    operation_fn = OPERATIONS[args.operation]

    try:
        result = operation_fn(args.a, args.b)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        symbol = OP_SYMBOLS[args.operation]
        a_str = format_number(args.a)
        b_str = format_number(args.b)
        r_str = format_number(result)
        print(f"{a_str} {symbol} {b_str} = {r_str}")
    else:
        print(format_number(result))


if __name__ == "__main__":
    main()
