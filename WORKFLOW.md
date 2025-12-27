# EA Stress Test Workflow - Definitive Steps

This document defines the EXACT steps for testing an EA.
Each step MUST be completed before proceeding to the next.

Core workflow = Steps 1-11 (single pair).
Optional post-step modules run after Step 11.

---

## Source Of Truth

- What exists today: `SYSTEM_REGISTRY.md`
- Planned work only: `ROADMAP.md`
- Per-run state file: `runs/workflow_{EA_NAME}_YYYYMMDD_HHMMSS.json`
- Optional module runs are recorded in the same state file under `post_steps[]`

---

## Core Workflow (1-Pair Test)

### Step 1: Load EA
- Gate: `.mq5` exists
- Output: `ea_path`

```bash
ls "C:\\Users\\User\\AppData\\Roaming\\MetaQuotes\\Terminal\\A42909ABCDDDD04324904B57BA9776B8\\MQL5\\Experts\\EA_Name.mq5"
```

### Step 1B: Inject OnTester (profit-first)
- Purpose: replace/add `OnTester()` so optimization is profit-first with DD/smoothness penalty
- Gate: injection successful

```bash
python scripts/inject_ontester.py "path\\to\\EA_Name.mq5"
```

### Step 1C: Inject Safety (optional, recommended for live)
- Purpose: add simple live-safety guards (spread/rollover/Friday close)
- Gate: injection successful

```bash
python scripts/inject_safety.py "path\\to\\EA_Name.mq5"
```

### Step 2: Compile
- Gate: 0 errors
- Output: `ex5_path`

```bash
python scripts/compile_ea.py "path\\to\\EA_Name.mq5"
```

### Step 2B: Fix Compilation Errors (only if Step 2 failed)
- Gate: compile succeeds within 5 attempts
- Tools: `mql5-fixer` + `mql5-lookup` (see `SYSTEM_REGISTRY.md`)

### Step 3: Extract Parameters
- Gate: parameters extracted

```bash
python optimizer/param_extractor.py "path\\to\\EA_Name.mq5"
```

### Step 4: Create Wide Params + Intelligent Opt Inputs
- Gate: `{EA}_wide_params.json` and `{EA}_opt_inputs.json` written to `runs/`

```bash
python optimizer/param_intelligence.py "path\\to\\EA_Name.mq5" --mode both
```

### Step 5: Validate EA Trades (simple backtest, wide params)
- Gate: `total_trades > 0`
- Note: profitability is NOT expected here (wide params are intentionally loose)

```bash
python scripts/run_backtest.py "EA_Name" --symbol EURUSD --timeframe H1 --params runs/EA_Name_wide_params.json
```

### Step 6: Create Optimization INI
- Gate: INI created
- Note: uses intelligent ranges if `{EA}_opt_inputs.json` exists

```bash
python optimizer/ini_builder.py "path\\to\\EA_Name.mq5" --cloud on --symbol EURUSD --output runs/
```

### Step 7: Run Optimization (MT5)
- Gate: optimization completes and XML exports exist

```bash
python scripts/run_optimization.py "EA_Name" --ini runs/EA_Name_optimize.ini --timeout 3600
```

### Step 8: Parse Optimization Results (robust pass selection)
- Gate: robust passes found
- Output: `runs/{EA}_best_params.json`

```bash
python optimizer/result_parser.py "EA_Name"
```

### Step 9: Backtest With Robust Parameters
- Gate: review PF/DD/trades against thresholds (see `settings.py`)

```bash
python scripts/run_backtest.py "EA_Name" --symbol EURUSD --timeframe H1 --params runs/EA_Name_best_params.json
```

### Step 10: Monte Carlo (trade shuffling)
- Gate: confidence >= 70% and ruin <= 5% (defaults in `settings.py`)
- Note: uses per-trade net results (includes commission + swap) extracted from the MT5 Deals table

```bash
python tester/montecarlo.py "path\\to\\report.htm" -n 1000
```

### Step 11: Final Report (Dashboard + Text Report)

```bash
python scripts/generate_dashboard.py --state runs/workflow_EA_Name_*.json --passes 20
python scripts/generate_text_report.py --state runs/workflow_EA_Name_*.json
```

Outputs:
- Dashboard: `runs/dashboards/{EA}_YYYYMMDD_HHMMSS/index.html`
- Text report: `runs/{EA}_REPORT.txt`

---

## Post-Step Optional Modules (Menu + Implemented Modules)

After Step 11, run the advisor menu:

```bash
python scripts/post_step_menu.py --state runs/workflow_EA_Name_*.json
```

This prints:
- Recommended next modules + reasons (based on the results)
- Implemented vs planned modules
- Exact commands to run

### Implemented: Execution Stress Suite (offline)
```bash
python scripts/run_execution_stress.py --state runs/workflow_EA_Name_*.json --open
```
Output: `runs/stress/{EA}_YYYYMMDD_HHMMSS/index.html`

### Implemented: Multi-Pair Follow-up
```bash
python scripts/run_multipair.py --state runs/workflow_EA_Name_*.json --open
```
Output: `runs/multipair/{EA}_YYYYMMDD_HHMMSS/index.html`

### Implemented: Timeframe Sweep
```bash
python scripts/run_timeframes.py --state runs/workflow_EA_Name_*.json --open
```
Output: `runs/timeframes/{EA}_YYYYMMDD_HHMMSS/index.html`

Planned modules are tracked in `ROADMAP.md`.

---

## Gate Conditions (Defaults)

Thresholds live in `settings.py` (do not hardcode them elsewhere).

Core gates:
- Trades: `total_trades >= 50`
- Drawdown: `max_drawdown_pct <= 30`
- Profit Factor: `profit_factor >= 1.5` (system may still flag a "conditional pass" below this; see reports)

Monte Carlo gates:
- Confidence: `>= 70%`
- Ruin: `<= 5%`

