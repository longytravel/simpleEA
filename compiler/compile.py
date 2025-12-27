"""
MQL5 Compiler Module
Wraps MetaEditor64.exe for compilation.
"""
import subprocess
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MT5_EDITOR


@dataclass
class CompileError:
    """Represents a compilation error."""
    line: int
    column: int
    error_code: str
    message: str
    raw: str


@dataclass
class CompileResult:
    """Result of compilation attempt."""
    success: bool
    errors: list[CompileError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ex5_path: Optional[Path] = None
    log_output: str = ""


class Compiler:
    """Compiles MQL5 files using MetaEditor64.exe."""

    def __init__(self, metaeditor_path: Optional[Path] = None):
        self.metaeditor = metaeditor_path or MT5_EDITOR

    def compile(self, mq5_path: Path) -> CompileResult:
        """
        Compile an MQL5 file.

        Args:
            mq5_path: Path to the .mq5 file

        Returns:
            CompileResult with success status and any errors/warnings
        """
        mq5_path = Path(mq5_path)
        if not mq5_path.exists():
            return CompileResult(
                success=False,
                errors=[CompileError(0, 0, "FILE_NOT_FOUND", f"File not found: {mq5_path}", "")],
            )

        # Log file will be created next to the source file
        log_path = mq5_path.with_suffix('.log')

        # Build command
        cmd = [
            str(self.metaeditor),
            f'/compile:{mq5_path}',
            '/log',
        ]

        try:
            # Run MetaEditor
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(mq5_path.parent),
            )

            # Read log file if it exists
            log_output = ""
            if log_path.exists():
                with open(log_path, 'r', encoding='utf-16-le', errors='ignore') as f:
                    log_output = f.read()

            # Parse the log output
            return self._parse_log(log_output, mq5_path)

        except subprocess.TimeoutExpired:
            return CompileResult(
                success=False,
                errors=[CompileError(0, 0, "TIMEOUT", "Compilation timed out", "")],
            )
        except Exception as e:
            return CompileResult(
                success=False,
                errors=[CompileError(0, 0, "EXCEPTION", str(e), "")],
            )

    def _parse_log(self, log_output: str, mq5_path: Path) -> CompileResult:
        """Parse MetaEditor log output for errors and warnings."""
        errors = []
        warnings = []

        # Check for expected .ex5 file
        ex5_path = mq5_path.with_suffix('.ex5')
        success = ex5_path.exists()

        # Parse error lines
        # Format: file.mq5(line,col) : error 123: message
        error_pattern = re.compile(
            r'([^(]+)\((\d+),(\d+)\)\s*:\s*(error|warning)\s+(\d+):\s*(.*)',
            re.IGNORECASE
        )

        for line in log_output.split('\n'):
            line = line.strip()
            if not line:
                continue

            match = error_pattern.search(line)
            if match:
                _, line_num, col_num, level, code, message = match.groups()
                if level.lower() == 'error':
                    success = False
                    errors.append(CompileError(
                        line=int(line_num),
                        column=int(col_num),
                        error_code=code,
                        message=message,
                        raw=line,
                    ))
                else:
                    warnings.append(line)

            # Also check for simple "error" or "Result: N errors" patterns
            elif 'error' in line.lower() and 'Result:' in line:
                # "Result: 2 errors, 0 warnings"
                if re.search(r'Result:\s*(\d+)\s*error', line):
                    num_errors = int(re.search(r'Result:\s*(\d+)\s*error', line).group(1))
                    if num_errors > 0:
                        success = False

        return CompileResult(
            success=success,
            errors=errors,
            warnings=warnings,
            ex5_path=ex5_path if success else None,
            log_output=log_output,
        )


if __name__ == "__main__":
    # Test compilation
    compiler = Compiler()
    # Test with a file that should exist
    test_path = Path(r"C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\010E047102812FC0C18890992854220E\MQL5\Experts\RSI_Divergence_Pro.mq5")
    if test_path.exists():
        result = compiler.compile(test_path)
        print(f"Success: {result.success}")
        print(f"Errors: {len(result.errors)}")
        for err in result.errors:
            print(f"  Line {err.line}: {err.message}")
