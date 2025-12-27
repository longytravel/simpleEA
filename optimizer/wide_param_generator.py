"""
Wide Parameter Generator for EA Validation

This script extracts EA parameters and generates WIDE (permissive) values
for validation backtesting. It uses intelligent heuristics based on
parameter naming conventions.

Usage:
    python optimizer/wide_param_generator.py "path/to/EA.mq5"

Output:
    runs/{EA_name}_wide_params.json
"""

import re
import json
import sys
from pathlib import Path

# Parameter type patterns and how to widen them
WIDEN_RULES = {
    # Time-based parameters - expand to maximum range
    'hour': {'type': 'time_hour', 'wide_logic': 'expand_hours'},
    'start': {'type': 'time_hour', 'wide_logic': 'expand_hours'},
    'end': {'type': 'time_hour', 'wide_logic': 'expand_hours'},
    'session': {'type': 'time_hour', 'wide_logic': 'expand_hours'},

    # Period/lookback - shorter = more responsive = more signals
    'period': {'type': 'period', 'wide_logic': 'reduce_period'},
    'lookback': {'type': 'period', 'wide_logic': 'reduce_period'},
    'bars': {'type': 'period', 'wide_logic': 'reduce_period'},
    'length': {'type': 'period', 'wide_logic': 'reduce_period'},

    # Thresholds - loosen to trigger more signals
    'threshold': {'type': 'threshold', 'wide_logic': 'loosen_threshold'},
    'level': {'type': 'threshold', 'wide_logic': 'loosen_threshold'},
    'min': {'type': 'threshold', 'wide_logic': 'lower_minimum'},
    'max': {'type': 'threshold', 'wide_logic': 'raise_maximum'},

    # Multipliers - widen range
    'multiplier': {'type': 'multiplier', 'wide_logic': 'widen_multiplier'},
    'factor': {'type': 'multiplier', 'wide_logic': 'widen_multiplier'},
    'ratio': {'type': 'multiplier', 'wide_logic': 'widen_multiplier'},

    # Enable/disable - enable features for more activity
    'enable': {'type': 'bool', 'wide_logic': 'enable_feature'},
    'use': {'type': 'bool', 'wide_logic': 'enable_feature'},
    'allow': {'type': 'bool', 'wide_logic': 'enable_feature'},

    # Fixed - don't change these
    'magic': {'type': 'fixed', 'wide_logic': 'keep_default'},
    'slippage': {'type': 'fixed', 'wide_logic': 'keep_default'},
    'deviation': {'type': 'fixed', 'wide_logic': 'keep_default'},
    'comment': {'type': 'fixed', 'wide_logic': 'keep_default'},
}

# Keep risk reasonable
RISK_PATTERNS = ['risk', 'lot', 'volume', 'size']


def extract_inputs(ea_path: Path) -> list:
    """Extract input parameters from EA source."""
    content = ea_path.read_text(encoding='utf-8', errors='ignore')

    params = []
    # Match: input type name = value; // comment
    pattern = r'input\s+(\w+)\s+(\w+)\s*=\s*([^;]+);(?:\s*//\s*(.*))?'

    for match in re.finditer(pattern, content):
        param_type, name, default, comment = match.groups()
        default = default.strip()

        # Parse default value
        if param_type == 'bool':
            value = default.lower() == 'true'
        elif param_type in ['int', 'long']:
            value = int(float(default))
        elif param_type in ['double', 'float']:
            value = float(default)
        else:
            value = default

        params.append({
            'name': name,
            'type': param_type,
            'default': value,
            'comment': comment.strip() if comment else ''
        })

    return params


def classify_parameter(param: dict) -> str:
    """Determine how to widen this parameter based on its name."""
    name_lower = param['name'].lower()

    # Check for risk parameters first - keep reasonable
    for risk_word in RISK_PATTERNS:
        if risk_word in name_lower:
            return 'keep_default'

    # Check against widen rules
    for keyword, rule in WIDEN_RULES.items():
        if keyword in name_lower:
            return rule['wide_logic']

    # Default: keep as-is
    return 'keep_default'


def apply_wide_logic(param: dict, logic: str) -> any:
    """Apply widening logic to generate permissive value."""
    default = param['default']
    param_type = param['type']
    name_lower = param['name'].lower()

    if logic == 'keep_default':
        return default

    elif logic == 'expand_hours':
        # Time hours: expand to near-24h coverage
        if 'start' in name_lower:
            return 0  # Start at midnight
        elif 'end' in name_lower:
            return 23  # End at 23:00
        else:
            return default

    elif logic == 'reduce_period':
        # Shorter periods = more responsive = more trades
        if isinstance(default, (int, float)) and default > 10:
            return max(5, int(default * 0.5))  # Halve it, min 5
        return default

    elif logic == 'loosen_threshold':
        # Lower thresholds trigger more signals
        if isinstance(default, (int, float)):
            if 'hvn' in name_lower or 'high' in name_lower:
                return default * 0.5  # Lower high threshold
            elif 'lvn' in name_lower or 'low' in name_lower:
                return default * 2.0  # Raise low threshold
            else:
                return default * 0.7  # Generally loosen
        return default

    elif logic == 'lower_minimum':
        if isinstance(default, (int, float)):
            return default * 0.5
        return default

    elif logic == 'raise_maximum':
        if isinstance(default, (int, float)):
            return default * 1.5
        return default

    elif logic == 'widen_multiplier':
        # Keep multipliers reasonable but allow more range
        return default

    elif logic == 'enable_feature':
        # Enable features for more trading activity
        if param_type == 'bool':
            return True
        return default

    return default


def generate_wide_params(ea_path: Path) -> dict:
    """Generate wide parameters for an EA."""
    params = extract_inputs(ea_path)

    wide_params = {}
    analysis = []

    for param in params:
        logic = classify_parameter(param)
        wide_value = apply_wide_logic(param, logic)

        # Round floats nicely
        if isinstance(wide_value, float):
            wide_value = round(wide_value, 2)

        wide_params[param['name']] = wide_value

        # Track changes for reporting
        if wide_value != param['default']:
            analysis.append({
                'name': param['name'],
                'default': param['default'],
                'wide': wide_value,
                'logic': logic,
                'comment': param['comment']
            })

    return wide_params, analysis


def main():
    if len(sys.argv) < 2:
        print("Usage: python wide_param_generator.py <EA.mq5>")
        sys.exit(1)

    ea_path = Path(sys.argv[1])
    if not ea_path.exists():
        print(f"Error: File not found: {ea_path}")
        sys.exit(1)

    ea_name = ea_path.stem
    wide_params, analysis = generate_wide_params(ea_path)

    # Save to runs folder
    output_dir = Path(__file__).parent.parent / 'runs'
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f'{ea_name}_wide_params.json'
    output_file.write_text(json.dumps(wide_params, indent=2))

    # Print analysis
    print(f"\n=== Wide Parameters for {ea_name} ===\n")
    print(f"Total parameters: {len(wide_params)}")
    print(f"Modified for validation: {len(analysis)}\n")

    if analysis:
        print("Changes made:")
        print("-" * 60)
        for change in analysis:
            print(f"  {change['name']}: {change['default']} -> {change['wide']}")
            print(f"    Logic: {change['logic']}")
            if change['comment']:
                print(f"    ({change['comment']})")
            print()

    print(f"Output: {output_file}")

    # Also output JSON for programmatic use
    result = {
        'ea_name': ea_name,
        'output_file': str(output_file),
        'total_params': len(wide_params),
        'modified_count': len(analysis),
        'changes': analysis,
        'wide_params': wide_params
    }
    print("\n" + json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
