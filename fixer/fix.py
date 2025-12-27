"""
MQL5 Code Fixer Module
Attempts to automatically fix common compilation errors.
"""
import re
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from compiler.compile import CompileError


class Fixer:
    """
    Attempts to fix common MQL5 compilation errors.

    For the prototype, uses rule-based fixes.
    Can be extended with LLM-based fixing in the future.
    """

    # Common error patterns and their fixes
    ERROR_PATTERNS = {
        # Missing semicolon
        r"';' - semicolon expected": "add_semicolon",
        # Undeclared identifier
        r"'(\w+)' - undeclared identifier": "declare_variable",
        # Wrong parameters count
        r"wrong parameters count": "fix_params",
        # Array required
        r"array required": "fix_array",
        # Implicit conversion
        r"implicit conversion": "fix_type",
    }

    def __init__(self):
        self.fixes_applied = []

    def fix(self, mq5_path: Path, errors: list[CompileError]) -> Optional[str]:
        """
        Attempt to fix compilation errors in the source file.

        Args:
            mq5_path: Path to the .mq5 file
            errors: List of compilation errors

        Returns:
            Fixed source code, or None if no fixes could be applied
        """
        with open(mq5_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        original_lines = lines.copy()
        self.fixes_applied = []

        for error in errors:
            lines = self._apply_fix(lines, error)

        # Check if any changes were made
        if lines == original_lines:
            return None

        return ''.join(lines)

    def _apply_fix(self, lines: list[str], error: CompileError) -> list[str]:
        """Apply a fix for a specific error."""

        # Try each pattern
        for pattern, fix_method in self.ERROR_PATTERNS.items():
            if re.search(pattern, error.message, re.IGNORECASE):
                method = getattr(self, f'_fix_{fix_method}', None)
                if method:
                    lines = method(lines, error)
                    self.fixes_applied.append(f"{fix_method} at line {error.line}")
                break

        return lines

    def _fix_add_semicolon(self, lines: list[str], error: CompileError) -> list[str]:
        """Add missing semicolon at the end of a line."""
        if 0 < error.line <= len(lines):
            line = lines[error.line - 1].rstrip()
            if not line.endswith(';') and not line.endswith('{') and not line.endswith('}'):
                lines[error.line - 1] = line + ';\n'
        return lines

    def _fix_declare_variable(self, lines: list[str], error: CompileError) -> list[str]:
        """
        Attempt to declare an undeclared variable.
        This is tricky without context - log for manual review.
        """
        # Extract variable name from error message
        match = re.search(r"'(\w+)' - undeclared identifier", error.message)
        if match:
            var_name = match.group(1)
            self.fixes_applied.append(f"Cannot auto-fix undeclared variable: {var_name}")
        return lines

    def _fix_fix_params(self, lines: list[str], error: CompileError) -> list[str]:
        """
        Attempt to fix wrong parameter count.
        Usually requires manual review.
        """
        self.fixes_applied.append(f"Cannot auto-fix parameter count at line {error.line}")
        return lines

    def _fix_fix_array(self, lines: list[str], error: CompileError) -> list[str]:
        """
        Attempt to fix array-related errors.
        """
        self.fixes_applied.append(f"Cannot auto-fix array error at line {error.line}")
        return lines

    def _fix_fix_type(self, lines: list[str], error: CompileError) -> list[str]:
        """
        Attempt to fix type conversion issues.
        Add explicit casts where needed.
        """
        if 0 < error.line <= len(lines):
            line = lines[error.line - 1]
            # Common fix: wrap in explicit cast
            # This is a placeholder - real implementation would need more context
            self.fixes_applied.append(f"Type conversion issue at line {error.line} - may need manual fix")
        return lines

    def save_fixed(self, mq5_path: Path, fixed_code: str) -> None:
        """Save the fixed code back to the file."""
        with open(mq5_path, 'w', encoding='utf-8') as f:
            f.write(fixed_code)

    def get_fixes_report(self) -> str:
        """Get a report of all fixes applied."""
        if not self.fixes_applied:
            return "No fixes applied"
        return "\n".join(self.fixes_applied)


if __name__ == "__main__":
    # Test the fixer
    fixer = Fixer()
    test_errors = [
        CompileError(10, 5, "100", "';' - semicolon expected", "test.mq5(10,5): error 100: ';' - semicolon expected"),
    ]

    # Create a test file
    test_code = '''int OnInit()
{
    int x = 5
    return 0;
}
'''
    test_path = Path("test_fix.mq5")
    with open(test_path, 'w') as f:
        f.write(test_code)

    fixed = fixer.fix(test_path, test_errors)
    if fixed:
        print("Fixed code:")
        print(fixed)
    else:
        print("No fixes applied")

    test_path.unlink()
