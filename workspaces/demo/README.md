# Command-Line Calculator

A simple yet fully-featured command-line calculator written in Python that supports **add**, **subtract**, **multiply**, and **divide** operations.

## Requirements

- Python 3.7 or higher
- `pytest` (only required to run the test suite)

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Usage

```
python calculator.py <operation> <NUM1> <NUM2> [--verbose]
```

| Argument | Description |
|----------|-------------|
| `operation` | One of `add`, `subtract`, `multiply`, `divide` |
| `NUM1` | First operand (integer or float) |
| `NUM2` | Second operand (integer or float) |
| `--verbose` / `-v` | Print the full expression (e.g. `10 + 5 = 15`) |

---

## Examples

```bash
# Addition
python calculator.py add 10 5
# Output: 15

# Subtraction
python calculator.py subtract 10 5
# Output: 5

# Multiplication
python calculator.py multiply 4 7
# Output: 28

# Division
python calculator.py divide 20 4
# Output: 5

# Floating-point numbers
python calculator.py add 1.5 2.3
# Output: 3.8

# Verbose mode
python calculator.py multiply 6 7 --verbose
# Output: 6 × 7 = 42

# Division by zero (handled gracefully)
python calculator.py divide 10 0
# Output (stderr): Error: Division by zero is not allowed.
# Exit code: 1
```

---

## Running Tests

```bash
pytest test_calculator.py -v
```

Expected output:

```
test_calculator.py::TestAdd::test_positive_numbers PASSED
test_calculator.py::TestAdd::test_negative_numbers PASSED
...
20 passed in 0.XXs
```

---

## Project Structure

```
.
├── calculator.py       # Main calculator script
├── test_calculator.py  # Unit tests
├── requirements.txt    # Python dependencies
└── README.md           # This file
```
