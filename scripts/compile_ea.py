#!/usr/bin/env python3
"""
CLI wrapper for EA compilation.
Outputs JSON for Claude Code to parse.

Usage:
    python compile_ea.py <path_to_mq5_file>
"""

import sys
import json
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from compiler import Compiler


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "success": False,
            "error": "Usage: python compile_ea.py <path_to_mq5_file>"
        }))
        sys.exit(1)

    mq5_path = Path(sys.argv[1])

    if not mq5_path.exists():
        print(json.dumps({
            "success": False,
            "error": f"File not found: {mq5_path}"
        }))
        sys.exit(1)

    compiler = Compiler()
    result = compiler.compile(mq5_path)

    output = {
        "success": result.success,
        "source_file": str(mq5_path),
        "output_file": str(result.ex5_path) if result.ex5_path else None,
        "errors": [
            {
                "line": err.line,
                "column": err.column,
                "code": err.error_code,
                "message": err.message
            }
            for err in result.errors
        ],
        "warnings": result.warnings,
        "log_output": result.log_output
    }

    print(json.dumps(output, indent=2))
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
