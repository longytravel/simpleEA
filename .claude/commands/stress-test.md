---
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, Task, AskUserQuestion
description: EA stress test with state-tracked workflow. Stops at each step for user approval.
model: opus
---

# Stress Test Command

This command executes the EA stress test workflow with strict step enforcement.

## Required Reading

**BEFORE ANY ACTION, read these files:**
1. `SYSTEM_REGISTRY.md` - Know what tools exist
2. `WORKFLOW.md` - Know the exact steps
3. `runs/workflow_*.json` - Check for existing state (if resuming)

## How to Use

```
/stress-test EA_Name              # Test by name
/stress-test C:\path\to\EA.mq5    # Test by path
/stress-test --resume             # Resume last workflow
```

## Workflow

The complete workflow has 11 steps. See `WORKFLOW.md` for details.

| Step | Action | Gate |
|------|--------|------|
| 1 | Load EA | File exists |
| 2 | Compile | 0 errors |
| 2b | Fix errors (if needed) | Compiles within 5 attempts |
| 3 | Extract parameters | Params extracted |
| 4 | Create wide INI | INI created |
| 5 | Validate trades | trades > 0 |
| 6 | Create optimization INI | INI created |
| 7 | Run optimization | XML files exist |
| 8 | Parse results | robust_passes > 0 |
| 9 | Backtest robust params | PF >= 1.5, DD <= 30% |
| 10 | Monte Carlo | confidence >= 70% |
| 11 | Report | Summary |

## State Management

Use the workflow state manager to track progress:

```python
from workflow import WorkflowStateManager

manager = WorkflowStateManager()

# New workflow
state = manager.create_workflow("EA_Name", "path/to/EA.mq5", "EURUSD")

# Resume existing
state = manager.load_workflow(Path("runs/workflow_EA_timestamp.json"))

# Before each step
can_start, reason = manager.can_start_step("5_validate_trades")
manager.start_step("5_validate_trades")

# After each step
manager.complete_step("5_validate_trades", {"trades": 306})
# or
manager.fail_step("5_validate_trades", "No trades found")
```

## User Checkpoints

**After EVERY step:**
1. Show what was done
2. Show key outputs/metrics
3. Show pass/fail status
4. Ask user to continue or abort

Example:
```
=== Step 5: Validate Trades ===
Result: 306 trades found
Commission: Included (£7/lot)
Status: PASSED

Ready to proceed to Step 6 (Create Optimization INI)?
```

## Error Fixing

When compilation fails:
1. Read error messages
2. Check `.claude/skills/mql5-fixer/patterns.md`
3. Use `python reference/mql5_indexer.py search "function"` for lookups
4. Apply fixes with Edit tool
5. Recompile

## Settings

All thresholds come from `settings.py`:
- `thresholds.min_profit_factor`: 1.5
- `thresholds.max_drawdown_pct`: 30
- `monte_carlo.confidence_min`: 70
- `optimization.use_cloud`: True (default)
