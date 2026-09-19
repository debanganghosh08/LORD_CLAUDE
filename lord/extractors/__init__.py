"""Language extractors.

`extract(root, rel, language, source)` dispatches to the extractor for the
language. Python uses the standard-library AST and yields CONFIRMED results.
JavaScript/TypeScript use line-oriented heuristics and yield INFERRED results.
Any other language returns an Extraction with confidence UNKNOWN so callers
can say "analysis unavailable" instead of "nothing found".
"""

from __future__ import annotations

from pathlib import Path

from lord.report import UNKNOWN
from lord.symbols import Extraction

SUPPORTED: dict[str, str] = {
    "python": "confirmed",
    "javascript": "inferred",
    "typescript": "inferred",
}


def extract(root: Path, rel: str, language: str, source: str) -> Extraction:
    if language == "python":
        from lord.extractors.python_ast import extract_python

        return extract_python(root, rel, source)
    if language in ("javascript", "typescript"):
        from lord.extractors.js_ts import extract_js_ts

        return extract_js_ts(root, rel, source, language)
    return Extraction(file=rel, language=language, confidence=UNKNOWN, error=f"analysis unavailable for language {language or 'unknown'!r}")
