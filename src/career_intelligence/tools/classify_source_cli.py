"""
CLI adapter for career_classify_source wrapper.

Usage: python -m career_intelligence.tools.classify_source_cli --url <url>
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify a job URL into its ATS source type")
    parser.add_argument("--url", required=True, help="Job posting URL to classify")
    args = parser.parse_args()

    from career_intelligence.source_classifier import classify_source
    result = classify_source(args.url)
    print(json.dumps(dataclasses.asdict(result), indent=2))


if __name__ == "__main__":
    main()
