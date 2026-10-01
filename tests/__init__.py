# Every test imported through the `tests` package (python -m unittest discover, or
# `from tests...` imports) runs under the private temp root; see tests/_test_root.py.
from ._test_root import ensure_test_root as _ensure_test_root

_ensure_test_root()
