# EA Stress Test System

Stress-tests Expert Advisors through compilation, optimization, backtesting, and Monte Carlo simulation.

## Documentation

| File | Purpose |
|------|---------|
| **SYSTEM_REGISTRY.md** | Complete inventory of all tools, scripts, and skills |
| **WORKFLOW.md** | The exact 11-step workflow with commands and gates |
| **settings.py** | All configurable thresholds (PF, DD, MC, etc.) |
| **config.py** | MT5 paths and defaults |

## Quick Start

```bash
# Use the stress-tester agent for guided workflow
# Or run individual scripts:

python scripts/compile_ea.py "EA.mq5"                    # Compile
python optimizer/param_intelligence.py "EA.mq5" --mode both  # Generate wide + opt params
python scripts/run_backtest.py "EA" --params runs/{EA}_wide_params.json  # Validate trades
python optimizer/ini_builder.py "EA.mq5" --cloud on      # Create optimization INI
python scripts/run_optimization.py "EA" --ini X          # Optimize
python optimizer/result_parser.py "EA"                   # Find robust params
python tester/montecarlo.py "report.htm"                 # Monte Carlo
python scripts/generate_dashboard.py --ea "EA" --passes 20  # Dashboard (runs/dashboards/*/index.html)
python scripts/post_step_menu.py --state runs/workflow_EA_*.json  # Post-step menu + recommendations
python scripts/run_execution_stress.py --state runs/workflow_EA_*.json --open  # Execution stress suite
```

## Key Directories

```
.claude/
-- agents/stress-tester.md          # Main workflow agent
-- agents/post-step-advisor.md      # Post-step menu + recommendations
-- skills/mql5-fixer/               # Fix compilation errors
-- skills/mql5-lookup/              # Reference documentation
-- skills/parameter-optimizer/      # Parameter extraction

scripts/                        # CLI tools
optimizer/                      # Param extraction, INI building, result parsing
tester/                        # Backtest, Monte Carlo
workflow/                      # State management
reference/cache/               # Pre-cached MQL5 docs (48 files)
runs/                          # Output directory
```

## Thresholds (settings.py)

- Profit Factor: >= 1.5
- Max Drawdown: <= 30%
- Min Trades: >= 50
- MC Confidence: >= 70%
- Ruin Probability: <= 5%

## MQL5 Reference

```bash
python reference/mql5_indexer.py search "OrderSend"
python reference/mql5_indexer.py get "CTrade"
cat reference/cache/ctrade.txt  # Fastest
```
