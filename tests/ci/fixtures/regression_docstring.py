"""Regression fixture for CCE-87.

This module exists ONLY to be read by test_docstring_flag_value_lint.py
as a synthetic negative-path input. It must contain --FLAG VALUE shapes
in the module docstring OUTSIDE any fenced code block, so the lint
correctly detects them as the CCE-80 class of mkdocs-autorefs trap.

Usage: do not import. Treated as a data file by the test.

  --bar BAZ
  [--qux QUUX]
"""

PLACEHOLDER = True  # importable but no-op so static analysis doesn't object
