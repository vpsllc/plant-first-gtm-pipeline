"""Print the Clay formula regexes generated from pipeline/filters.py (no network, no credits).

Paste the output into clay/CLAY_SETUP.md whenever filters.py changes. The offline tests
fail if the two drift apart, so the Clay demo can never contradict the scripts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.filters import js_regex_literals  # noqa: E402

include, exclude = js_regex_literals()
print(f"const include = {include};")
print(f"const exclude = {exclude};")
