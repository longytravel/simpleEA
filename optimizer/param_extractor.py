"""
EA Parameter Extractor

Parses MQL5 source files to extract input parameters and their default values.
"""

import re
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Any


@dataclass
class EAParameter:
    """Represents an EA input parameter."""
    name: str
    type: str  # int, double, bool, string, enum
    default: Any
    comment: str = ""

    # Optimization settings (generated)
    optimize: bool = True
    min_val: Optional[float] = None
    step: Optional[float] = None
    max_val: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtractionResult:
    """Result of parameter extraction."""
    success: bool
    ea_name: str
    parameters: List[EAParameter]
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "ea_name": self.ea_name,
            "parameters": [p.to_dict() for p in self.parameters],
            "error": self.error
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class ParameterExtractor:
    """Extracts input parameters from MQL5 source files."""

    # Parameters that should NOT be optimized
    SKIP_PATTERNS = [
        r'magic', r'lot', r'comment', r'slippage', r'deviation',
        r'color', r'arrow', r'email', r'push', r'alert',
        r'eastresssafety',
    ]

    def extract(self, source_path: Path) -> ExtractionResult:
        """
        Extract input parameters from an EA source file.

        Args:
            source_path: Path to .mq5 file

        Returns:
            ExtractionResult with list of parameters
        """
        if not source_path.exists():
            return ExtractionResult(
                success=False,
                ea_name="",
                parameters=[],
                error=f"File not found: {source_path}"
            )

        try:
            # Read source file
            content = self._read_source(source_path)
            ea_name = source_path.stem

            # Extract input declarations
            parameters = self._parse_inputs(content)

            # Generate optimization ranges
            for param in parameters:
                self._generate_range(param)

            return ExtractionResult(
                success=True,
                ea_name=ea_name,
                parameters=parameters
            )

        except Exception as e:
            return ExtractionResult(
                success=False,
                ea_name=source_path.stem,
                parameters=[],
                error=str(e)
            )

    def _read_source(self, path: Path) -> str:
        """Read source file with various encodings."""
        for encoding in ['utf-8', 'utf-16', 'latin-1']:
            try:
                with open(path, 'r', encoding=encoding) as f:
                    return f.read()
            except:
                continue
        raise ValueError(f"Could not read file with any encoding: {path}")

    def _parse_inputs(self, content: str) -> List[EAParameter]:
        """Parse input declarations from source code."""
        parameters = []

        # Pattern for input declarations:
        # input int/double/bool/string/ENUM_* Name = Value; // Comment
        pattern = r'''
            ^\s*input\s+                           # input keyword
            (int|double|bool|string|ENUM_\w+)\s+   # type
            (\w+)\s*                               # name
            =\s*                                   # equals
            ([^;]+?)                               # default value
            \s*;\s*                                # semicolon
            (?://\s*(.*))?                         # optional comment
            $
        '''

        for match in re.finditer(pattern, content, re.MULTILINE | re.VERBOSE):
            param_type = match.group(1)
            param_name = match.group(2)
            default_str = match.group(3).strip()
            comment = match.group(4) or ""

            # Parse default value
            default = self._parse_value(default_str, param_type)

            param = EAParameter(
                name=param_name,
                type=self._normalize_type(param_type),
                default=default,
                comment=comment.strip()
            )

            parameters.append(param)

        return parameters

    def _parse_value(self, value_str: str, param_type: str) -> Any:
        """Parse a default value string into the appropriate type."""
        value_str = value_str.strip()

        if param_type == 'bool':
            return value_str.lower() == 'true'
        elif param_type == 'int':
            try:
                return int(value_str)
            except:
                return 0
        elif param_type == 'double':
            try:
                return float(value_str)
            except:
                return 0.0
        elif param_type == 'string':
            # Remove quotes
            return value_str.strip('"\'')
        else:
            # Enum or other - keep as string
            return value_str

    def _normalize_type(self, param_type: str) -> str:
        """Normalize type names."""
        if param_type.startswith('ENUM_'):
            return 'enum'
        return param_type.lower()

    def _generate_range(self, param: EAParameter) -> None:
        """Generate optimization range for a parameter."""
        # Check if should skip optimization
        name_lower = param.name.lower()
        for pattern in self.SKIP_PATTERNS:
            if re.search(pattern, name_lower, re.IGNORECASE):
                param.optimize = False
                return

        # Skip strings and unknown types
        if param.type in ('string', 'enum'):
            param.optimize = False
            return

        # Handle booleans
        if param.type == 'bool':
            param.min_val = 0
            param.max_val = 1
            param.step = 1
            return

        # Handle numeric types
        default = float(param.default) if param.default else 0

        if default == 0:
            # Can't expand from 0, use reasonable defaults
            if 'period' in name_lower or 'length' in name_lower:
                param.min_val = 5
                param.max_val = 50
                param.step = 5
            else:
                param.min_val = 1
                param.max_val = 100
                param.step = 10
            return

        # Expand by ~50% in each direction
        expansion = 0.5

        if param.type == 'int':
            min_val = max(1, int(default * (1 - expansion)))
            max_val = int(default * (1 + expansion))

            # Calculate step (aim for ~10 steps)
            range_size = max_val - min_val
            step = max(1, range_size // 10)

            # Round step to nice numbers
            if step >= 10:
                step = (step // 5) * 5

            param.min_val = min_val
            param.max_val = max_val
            param.step = step

        elif param.type == 'double':
            min_val = max(0.0, default * (1 - expansion))
            max_val = default * (1 + expansion)

            # Calculate step based on magnitude (avoid rounding tiny values to 0.00)
            abs_default = abs(default)
            if abs_default >= 1:
                step = 0.25
                precision = 2
            elif abs_default >= 0.1:
                step = 0.1
                precision = 3
            elif abs_default >= 0.01:
                step = 0.01
                precision = 4
            else:
                step = 0.0001
                precision = 6

            min_val = round(min_val, precision)
            max_val = round(max_val, precision)
            if max_val < min_val:
                max_val = min_val + step

            param.min_val = min_val
            param.max_val = max_val
            param.step = step


def extract_parameters(source_path: str) -> ExtractionResult:
    """Convenience function to extract parameters."""
    extractor = ParameterExtractor()
    return extractor.extract(Path(source_path))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python param_extractor.py <EA.mq5>")
        sys.exit(1)

    result = extract_parameters(sys.argv[1])
    print(result.to_json())

    if result.success:
        print(f"\n--- Summary ---")
        print(f"EA: {result.ea_name}")
        print(f"Parameters found: {len(result.parameters)}")

        optimize_count = sum(1 for p in result.parameters if p.optimize)
        print(f"To optimize: {optimize_count}")

        print("\nOptimizable parameters:")
        for p in result.parameters:
            if p.optimize:
                print(f"  {p.name}: {p.min_val} -> {p.max_val} (step {p.step})")

        print("\nFixed parameters:")
        for p in result.parameters:
            if not p.optimize:
                print(f"  {p.name}: {p.default}")
