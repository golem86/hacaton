"""Strict JUnit gate: exact case count and no failures, errors, skips or incomplete reports."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: assert-junit.py JUNIT.xml EXPECTED_CASES")
    root = ET.parse(Path(sys.argv[1])).getroot()
    if root.tag not in {"testsuite", "testsuites"}:
        raise SystemExit("Invalid JUnit root")
    suites = [root] if root.tag == "testsuite" else list(root)
    keys = ("tests", "failures", "errors", "skipped")
    if not suites or any(suite.tag != "testsuite" or any(suite.get(key) is None for key in keys)
                         for suite in suites):
        raise SystemExit("Missing or incomplete JUnit testsuite")
    totals = {key: sum(int(suite.get(key)) for suite in suites) for key in keys}
    cases = [case for suite in suites for case in suite.findall("testcase")]
    actual = {
        "failures": sum(case.find("failure") is not None for case in cases),
        "errors": sum(case.find("error") is not None for case in cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
    }
    if len(cases) != totals["tests"] or any(actual[key] != totals[key] for key in actual):
        raise SystemExit("JUnit counters do not match testcase records")
    expected = int(sys.argv[2])
    print({**totals, "expected": expected})
    if totals["tests"] != expected or any(totals[key] for key in ("failures", "errors", "skipped")):
        raise SystemExit(f"Expected exactly {expected} test cases and zero failures/errors/skips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
