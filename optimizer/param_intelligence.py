"""
Parameter Intelligence System

Unified system for understanding EA parameters and generating:
1. WIDE values (for validation - maximize trading)
2. OPTIMIZATION ranges (for genetic optimization)

This uses semantic understanding of parameter names to make intelligent decisions.

Usage:
    python optimizer/param_intelligence.py "EA.mq5" --mode wide
    python optimizer/param_intelligence.py "EA.mq5" --mode optimize
    python optimizer/param_intelligence.py "EA.mq5" --mode both
"""

import re
import json
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ParamInfo:
    """Information about a parameter."""
    name: str
    param_type: str
    default: Any
    comment: str
    category: str  # time, period, threshold, multiplier, bool, fixed, unknown
    wide_value: Any
    opt_min: Any
    opt_max: Any
    opt_step: Any
    should_optimize: bool
    reasoning: str


# Category detection patterns
CATEGORY_PATTERNS = {
    'time_start': [r'_start$', r'^start', r'begin', r'open_hour', r'session.*start'],
    'time_end': [r'_end$', r'^end', r'close', r'close_hour', r'session.*end'],
    'period': [r'period', r'lookback', r'bars', r'length', r'window', r'ma_', r'ema_', r'sma_'],
    'threshold_high': [r'hvn', r'high.*thresh', r'upper', r'max.*thresh', r'overbought'],
    'threshold_low': [r'lvn', r'low.*thresh', r'lower', r'min.*thresh', r'oversold'],
    'threshold': [r'threshold', r'level', r'limit', r'trigger'],
    'multiplier': [r'multiplier', r'factor', r'ratio', r'coefficient', r'atr_'],
    'activation': [r'activation', r'activate', r'trigger_at'],
    'bool_enable': [r'^enable', r'^use_', r'^allow', r'^is_', r'^has_'],
    'fixed': [r'magic', r'slippage', r'deviation', r'comment', r'color', r'arrow', r'^eastresssafety_'],
    'risk': [r'risk', r'lot', r'volume', r'size', r'percent'],
}


def detect_category(name: str, param_type: str) -> str:
    """Detect parameter category from its name."""
    name_lower = name.lower()

    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, name_lower):
                return category

    # Fallback based on type
    if param_type == 'bool':
        return 'bool_enable'

    return 'unknown'


def generate_wide_value(param: dict, category: str) -> tuple:
    """Generate wide (permissive) value for validation."""
    default = param['default']
    name_lower = param['name'].lower()

    if category == 'time_start':
        if "minute" in name_lower:
            return 0, "Expand to 00 minutes for maximum trading hours"
        return 0, "Expand to midnight for maximum trading hours"

    elif category == 'time_end':
        if "minute" in name_lower:
            return 59, "Expand to 59 minutes for maximum trading hours"
        return 23, "Expand to 23:00 for maximum trading hours"

    elif category == 'period':
        if isinstance(default, (int, float)) and default > 10:
            wide = max(5, int(default * 0.5))
            return wide, f"Halved period ({default} -> {wide}) for more responsive signals"
        return default, "Period already short enough"

    elif category == 'threshold_high':
        if isinstance(default, (int, float)):
            wide = round(default * 0.5, 2)
            return wide, f"Lowered high threshold ({default} -> {wide}) to trigger more signals"
        return default, "Non-numeric threshold"

    elif category == 'threshold_low':
        if isinstance(default, (int, float)):
            wide = round(default * 2.0, 2)
            return wide, f"Raised low threshold ({default} -> {wide}) to trigger more signals"
        return default, "Non-numeric threshold"

    elif category == 'threshold':
        if isinstance(default, (int, float)):
            wide = round(default * 0.7, 2)
            return wide, f"Loosened threshold ({default} -> {wide}) for more signals"
        return default, "Non-numeric threshold"

    elif category == 'bool_enable':
        return True, "Enabled feature for more trading activity"

    elif category in ['fixed', 'risk']:
        return default, "Keep fixed/risk params at defaults"

    return default, "Unknown category - keeping default"


def generate_opt_range(param: dict, category: str) -> tuple:
    """Generate optimization range (min, max, step)."""
    default = param['default']
    param_type = param['param_type']
    should_opt = True
    name_lower = param.get('name', '').lower()

    if category in ['fixed']:
        return default, default, 0, False, "Fixed params not optimized"

    elif category == 'risk':
        # Optimize risk but conservatively
        if isinstance(default, (int, float)):
            opt_min = round(default * 0.5, 2)
            opt_max = round(default * 1.5, 2)
            step = round((opt_max - opt_min) / 4, 2)
            return opt_min, opt_max, step, True, f"Risk range: {opt_min}-{opt_max}"
        return default, default, 0, False, "Non-numeric risk param"

    elif category in ['time_start', 'time_end']:
        if isinstance(default, int):
            # Optimize around default ±4 hours
            if "minute" in name_lower:
                opt_min = max(0, default - 15)
                opt_max = min(59, default + 15)
                return opt_min, opt_max, 5, True, f"Time(min) range: {opt_min}-{opt_max} step 5"

            opt_min = max(0, default - 4)
            opt_max = min(23, default + 4)
            return opt_min, opt_max, 1, True, f"Time(hr) range: {opt_min}-{opt_max}"
        return default, default, 0, False, "Non-int time"

    elif category == 'period':
        if isinstance(default, int) and default >= 5:
            opt_min = max(5, default // 2)
            opt_max = default * 2
            step = max(1, (opt_max - opt_min) // 10)
            return opt_min, opt_max, step, True, f"Period range: {opt_min}-{opt_max}"
        return default, default, 0, False, "Period too small"

    elif category in ['threshold', 'threshold_high', 'threshold_low', 'multiplier', 'activation']:
        if isinstance(default, (int, float)):
            abs_default = abs(float(default))
            if abs_default >= 1:
                precision = 2
            elif abs_default >= 0.1:
                precision = 3
            elif abs_default >= 0.01:
                precision = 4
            else:
                precision = 6

            opt_min_raw = float(default) * 0.5
            opt_max_raw = float(default) * 1.5
            step_raw = (opt_max_raw - opt_min_raw) / 4.0

            opt_min = round(opt_min_raw, precision)
            opt_max = round(opt_max_raw, precision)
            step = round(step_raw, precision)

            if step <= 0:
                step = 10 ** (-precision)
            if opt_max < opt_min:
                opt_max = opt_min + step
            return opt_min, opt_max, step, True, f"Range: {opt_min}-{opt_max}"
        return default, default, 0, False, "Non-numeric"

    elif category == 'bool_enable':
        return 0, 1, 1, True, "Test both enabled and disabled"

    return default, default, 0, False, "Unknown category"


def extract_inputs(ea_path: Path) -> list:
    """Extract input parameters from EA source."""
    content = ea_path.read_text(encoding='utf-8', errors='ignore')

    params = []
    pattern = r'input\s+(\w+)\s+(\w+)\s*=\s*([^;]+);(?:\s*//\s*(.*))?'

    for match in re.finditer(pattern, content):
        param_type, name, default_str, comment = match.groups()
        default_str = default_str.strip()

        # Parse default value
        if param_type == 'bool':
            default = default_str.lower() == 'true'
        elif param_type in ['int', 'long']:
            try:
                default = int(float(default_str))
            except:
                default = 0
        elif param_type in ['double', 'float']:
            try:
                default = float(default_str)
            except:
                default = 0.0
        else:
            default = default_str

        params.append({
            'name': name,
            'param_type': param_type,
            'default': default,
            'comment': comment.strip() if comment else ''
        })

    return params


def analyze_ea(ea_path: Path) -> list[ParamInfo]:
    """Analyze all EA parameters and generate intelligence."""
    params = extract_inputs(ea_path)
    results = []

    for param in params:
        category = detect_category(param['name'], param['param_type'])

        wide_value, wide_reason = generate_wide_value(param, category)
        opt_min, opt_max, opt_step, should_opt, opt_reason = generate_opt_range(param, category)

        info = ParamInfo(
            name=param['name'],
            param_type=param['param_type'],
            default=param['default'],
            comment=param['comment'],
            category=category,
            wide_value=wide_value,
            opt_min=opt_min,
            opt_max=opt_max,
            opt_step=opt_step,
            should_optimize=should_opt,
            reasoning=f"Wide: {wide_reason} | Opt: {opt_reason}"
        )
        results.append(info)

    return results


def generate_wide_params_json(analysis: list[ParamInfo]) -> dict:
    """Generate wide_params.json content."""
    return {p.name: p.wide_value for p in analysis}


def generate_opt_inputs(analysis: list[ParamInfo]) -> list[dict]:
    """Generate optimization input entries."""
    inputs = []
    for p in analysis:
        inputs.append({
            'name': p.name,
            'default': p.default,
            'min': p.opt_min,
            'max': p.opt_max,
            'step': p.opt_step,
            'optimize': p.should_optimize
        })
    return inputs


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Parameter Intelligence System')
    parser.add_argument('ea_path', help='Path to EA .mq5 file')
    parser.add_argument('--mode', choices=['wide', 'optimize', 'both', 'analyze'],
                        default='both', help='Output mode')
    args = parser.parse_args()

    ea_path = Path(args.ea_path)
    if not ea_path.exists():
        print(f"Error: File not found: {ea_path}")
        sys.exit(1)

    ea_name = ea_path.stem
    analysis = analyze_ea(ea_path)

    output_dir = Path(__file__).parent.parent / 'runs'
    output_dir.mkdir(exist_ok=True)

    print(f"\n=== Parameter Intelligence: {ea_name} ===\n")

    if args.mode in ['analyze', 'both']:
        print("Parameter Analysis:")
        print("-" * 80)
        for p in analysis:
            opt_flag = "OPT" if p.should_optimize else "FIX"
            print(f"  [{opt_flag}] {p.name} ({p.category})")
            print(f"       Default: {p.default} | Wide: {p.wide_value}")
            if p.should_optimize:
                print(f"       Range: {p.opt_min} to {p.opt_max} step {p.opt_step}")
            print(f"       {p.reasoning}")
            print()

    if args.mode in ['wide', 'both']:
        wide_params = generate_wide_params_json(analysis)
        wide_file = output_dir / f'{ea_name}_wide_params.json'
        wide_file.write_text(json.dumps(wide_params, indent=2))
        print(f"Wide params saved: {wide_file}")

    if args.mode in ['optimize', 'both']:
        opt_inputs = generate_opt_inputs(analysis)
        opt_file = output_dir / f'{ea_name}_opt_inputs.json'
        opt_file.write_text(json.dumps(opt_inputs, indent=2))
        print(f"Optimization inputs saved: {opt_file}")

    # Summary JSON
    result = {
        'ea_name': ea_name,
        'total_params': len(analysis),
        'optimizable': sum(1 for p in analysis if p.should_optimize),
        'categories': {cat: sum(1 for p in analysis if p.category == cat)
                       for cat in set(p.category for p in analysis)},
    }
    print(f"\nSummary: {result['total_params']} params, {result['optimizable']} optimizable")
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
