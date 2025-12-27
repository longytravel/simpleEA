# EA Stress Test System - Complete Registry

**This is the SINGLE SOURCE OF TRUTH for what exists in this system.**
**Any agent or workflow MUST consult this file to know what tools to use.**

Planned work is documented separately in `ROADMAP.md` (not implemented yet).

---

## Configuration Files

| File | Purpose | Key Settings |
|------|---------|--------------|
| `config.py` | MT5 paths, defaults | `MT5_TERMINAL`, `MT5_EXPERTS_PATH`, `BACKTEST_FROM/TO` |
| `settings.py` | Thresholds, criteria | PF thresholds, MC settings, cloud agents on/off |
| `stress_test_settings.json` | Saved settings | Created by `settings.py --save` |

---

## Skills (Claude Code)

### 1. mql5-lookup
**Location:** `.claude/skills/mql5-lookup/`
**Purpose:** Look up MQL5 reference documentation (7000 pages)
**When to use:** Need function signatures, correct API usage, parameter types

**Commands:**
```bash
# Search for a topic
python reference/mql5_indexer.py search "OrderSend"

# Get full documentation
python reference/mql5_indexer.py get "CTrade"

# Pre-cached topics (FASTEST)
cat reference/cache/ctrade.txt
cat reference/cache/trade_functions.txt
```

**Cached topics (48 files):** `reference/cache/`
- Trading: `ctrade.txt`, `trade_functions.txt`, `mqltraderequest.txt`
- Indicators: `ima.txt`, `irsi.txt`, `imacd.txt`, `ibands.txt`, `iatr.txt`
- Data: `copybuffer.txt`, `copyrates.txt`, `csymbolinfo.txt`

---

### 2. mql5-fixer
**Location:** `.claude/skills/mql5-fixer/`
**Purpose:** Fix MQL5 compilation errors
**When to use:** After compile fails, to fix errors

**Process:**
1. Check `patterns.md` for known patterns
2. Check `mt4-to-mt5.md` if MT4 code detected
3. Use `mql5-lookup` for correct signatures
4. Apply minimal fixes with Edit tool
5. Recompile to verify

**Supporting files:**
- `patterns.md` - Common error patterns
- `mt4-to-mt5.md` - MT4 migration patterns
- `examples.md` - Real fix examples

---

### 3. parameter-optimizer
**Location:** `.claude/skills/parameter-optimizer/`
**Purpose:** Extract parameters and create optimization INI files
**When to use:** Before optimization, to create config

**Scripts:**
```bash
# Extract parameters from EA
python optimizer/param_extractor.py "path/to/EA.mq5"

# Create optimization INI (with intelligent ranges)
python optimizer/ini_builder.py "path/to/EA.mq5" --cloud on --output runs/

# Create WIDE params for validation (use larger expansion)
# Note: param_extractor.py auto-generates +/-50% ranges
```

**Range generation rules (in param_extractor.py):**
- Periods: +/-50%, step = default/4
- Multipliers: +/-50%, step = 0.25
- Skip: MagicNumber, LotSize, RiskPercent, Slippage

---

### 4. backtest-analyzer
**Location:** `.claude/skills/backtest-analyzer/`
**Purpose:** Interpret backtest results, score strategies
**When to use:** After backtest completes

**Thresholds (from settings.py):**
| Metric | Poor | Acceptable | Good | Excellent |
|--------|------|------------|------|-----------|
| Profit Factor | <1.0 | 1.0-1.5 | 1.5-2.5 | >2.5 |
| Max Drawdown | >40% | 25-40% | 15-25% | <15% |
| Win Rate | <35% | 35-50% | 50-65% | >65% |

---

### 5. mql5-coder
**Location:** `.claude/skills/mql5-coder/`
**Purpose:** Write new MQL5 code
**When to use:** Creating new EAs or major modifications

**Supporting files:**
- `templates.md` - EA templates
- `best-practices.md` - Coding standards

---

## Agents (Claude Code)

### 1. stress-tester
**Location:** `.claude/agents/stress-tester.md`
**Purpose:** Execute the full stress test workflow with state tracking
**When to use:** Running `/stress-test` command

---

### 2. post-step-advisor
**Location:** `.claude/agents/post-step-advisor.md`
**Purpose:** Show optional post-step modules + recommendations (prevents "LLM forgetting")
**When to use:** After Step 11, to decide what confidence boosters to run next

---

### 3. strategy-improver
**Location:** `.claude/agents/strategy-improver.md`
**Purpose:** Suggest improvements to EA logic
**When to use:** After stress test, to improve failing EAs

---

## Python Scripts

### Compilation
| Script | Purpose | Example |
|--------|---------|---------|
| `scripts/compile_ea.py` | Compile MQ5 -> EX5 | `python scripts/compile_ea.py "EA.mq5"` |

### Tester / Criterion
| Script | Purpose | Example |
|--------|---------|---------|
| `scripts/inject_ontester.py` | Inject profit-first OnTester() custom scoring (creates `*.mq5.ontester.bak` once) | `python scripts/inject_ontester.py "EA.mq5"` |
| `scripts/inject_safety.py` | Inject basic live-safety guards (spread + rollover + Friday close) (creates `*.mq5.safety.bak` once) | `python scripts/inject_safety.py "EA.mq5"` |

### Optimization
| Script | Purpose | Example |
|--------|---------|---------|
| `optimizer/param_intelligence.py` | **Unified param analysis** | `python optimizer/param_intelligence.py "EA.mq5" --mode both` |
| `optimizer/param_extractor.py` | Extract EA inputs (legacy) | `python optimizer/param_extractor.py "EA.mq5"` |
| `optimizer/ini_builder.py` | Create opt INI | `python optimizer/ini_builder.py "EA.mq5" --cloud on` |
| `scripts/run_optimization.py` | Run optimization | `python scripts/run_optimization.py "EA" --ini file.ini` |
| `optimizer/result_parser.py` | Find robust params | `python optimizer/result_parser.py "EA_Name"` |

**param_intelligence.py outputs:**
- `{EA}_wide_params.json` - Permissive values for validation backtest
- `{EA}_opt_inputs.json` - Intelligent optimization ranges

### Backtesting
| Script | Purpose | Example |
|--------|---------|---------|
| `scripts/run_backtest.py` | Run backtest | `python scripts/run_backtest.py "EA" --symbol EURUSD` |
| `scripts/post_step_menu.py` | Post-step menu/advisor (shows optional modules + recommendations; reads `post_steps[]` from state) | `python scripts/post_step_menu.py --state runs/workflow_EA_*.json` |
| `scripts/run_execution_stress.py` | Optional execution stress suite (offline spread/slippage/commission sensitivity) | `python scripts/run_execution_stress.py --state runs/workflow_EA_*.json --open` |
| `scripts/run_walk_forward.py` | Optional walk-forward validation (multi-fold IS/OOS backtests using fixed params) | `python scripts/run_walk_forward.py --state runs/workflow_EA_*.json --open` |
| `scripts/run_multipair.py` | Optional multi-pair follow-up + offline HTML report (includes correlation/drawdown overlap, currency exposure, portfolio suggestions) | `python scripts/run_multipair.py --state runs/workflow_EA_*.json --open` |
| `scripts/run_timeframes.py` | Optional timeframe sweep follow-up + offline HTML report | `python scripts/run_timeframes.py --state runs/workflow_EA_*.json --open` |
| `scripts/generate_dashboard.py` | Interactive offline dashboard (sortable/filterable passes + compare page) | `python scripts/generate_dashboard.py --state runs/workflow_EA_*.json --passes 20` |
| `scripts/generate_text_report.py` | Human-readable text report (ROI + quality + costs) | `python scripts/generate_text_report.py --state runs/workflow_EA_*.json` |
| `scripts/run_workflow.py` | Run core workflow Steps 1-11 with state tracking (used by web UI) | `python scripts/run_workflow.py --ea-path "EA.mq5"` |
| `scripts/web_app.py` | Local web UI (offline) to browse runs, select EAs from detected MT5 terminals, start workflows, and launch post-step modules | `python scripts/web_app.py --open` |
| `parser/report.py` | Parse HTML report | Used internally |
| `parser/trade_extractor.py` | Extract trades | Used by Monte Carlo |

### Testing
| Script | Purpose | Example |
|--------|---------|---------|
| `tester/montecarlo.py` | Monte Carlo sim | `python tester/montecarlo.py "report.htm" -n 1000` |
| `tester/multipair.py` | Multi-pair test | `python tester/multipair.py "EA" --pairs EURUSD GBPUSD` |
| `tester/walk_forward.py` | Walk-forward (multi-fold) validation (internal; used by `scripts/run_walk_forward.py`) | Used by script |

### Reference
| Script | Purpose | Example |
|--------|---------|---------|
| `reference/mql5_indexer.py` | Search docs | `python reference/mql5_indexer.py search "OrderSend"` |
| `reference/lookup.py` | Python API | `from reference.lookup import mql5_lookup` |

### Ranking
| Script | Purpose | Example |
|--------|---------|---------|
| `scripts/rank_ea.py` | Score EAs | `python scripts/rank_ea.py --show-leaderboard` |

---

## Workflow Internals

| File | Purpose |
|------|---------|
| `workflow/state_manager.py` | Enforces step dependencies and persists `runs/workflow_*.json` |
| `workflow/post_steps.py` | Records optional post-step module runs into `post_steps[]` in the state file |
| `workflow/post_step_modules.py` | Catalog of post-step modules (prevents "LLM forgetting") |

---

## Workflow Steps -> Tools Mapping

| Step | What Happens | Tools/Scripts to Use |
|------|--------------|---------------------|
| **1. Load EA** | Find .mq5 file | Check `config.MT5_EXPERTS_PATH` |
| **1B. Inject OnTester** | Profit-first custom optimization scoring | `scripts/inject_ontester.py` (creates `*.mq5.ontester.bak` once) |
| **1C. Inject Safety** | Add spread/rollover live guards (optional but recommended) | `scripts/inject_safety.py` (creates `*.mq5.safety.bak` once) |
| **2. Compile** | MQ5 -> EX5 | `scripts/compile_ea.py` |
| **2B. Fix Errors** | If compile fails | `mql5-fixer` skill -> `mql5-lookup` (max 5 attempts) |
| **3. Extract Params** | Get input params | `optimizer/param_extractor.py` |
| **4. Create Wide Params** | Intelligent param analysis | `optimizer/param_intelligence.py "EA.mq5" --mode both` |
| **5. Validate Trades** | Simple backtest, wide params | `scripts/run_backtest.py "EA" --params runs/{EA}_wide_params.json` |
| **6. Create Opt INI** | Uses intelligent ranges | `optimizer/ini_builder.py --cloud on` (reads opt_inputs.json) |
| **7. Run Optimization** | Genetic algo | `scripts/run_optimization.py` |
| **8. Parse Results** | Find robust params | `optimizer/result_parser.py` |
| **9. Backtest Robust** | Test best params | `scripts/run_backtest.py --params` |
| **10. Monte Carlo** | Shuffle trades | `tester/montecarlo.py` |
| **11. Report** | Dashboard + text report + verdict | `scripts/generate_dashboard.py --state` + `scripts/generate_text_report.py --state` |

**KEY:** Step 4/5 is VALIDATION (simple backtest with wide params, loss expected). Step 6+ is OPTIMIZATION.

---

## Key Settings (settings.py)

```python
# Thresholds
min_profit_factor: 1.5      # For passing
max_drawdown_pct: 30.0      # Maximum allowed
min_trades: 50              # Statistical significance

# Monte Carlo
iterations: 1000            # Number of shuffles
confidence_min: 70.0        # Must be >= 70%
max_ruin_probability: 5.0   # Must be <= 5%

# Optimization
use_cloud: True             # MQL5 Cloud Network ON by default

# Fixer
max_attempts: 5             # Before giving up
use_opus_for_complex: True  # Use Opus agent for hard errors
```

---

## File Locations

```
MT5 Terminal Data:
C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\A42909ABCDDDD04324904B57BA9776B8\

-- MQL5\Experts\           # EA source files (.mq5, .ex5)
-- Tester\                 # Backtest results
   -- reports\             # HTML reports
   -- *.xml                # Optimization results

Project:
C:\Users\User\Projects\simpleEA\

-- runs\                   # Output directory for state + outputs
-- runs\dashboards\         # Offline HTML dashboards (index.html)
-- runs\multipair\           # Offline multi-pair reports (index.html)
-- runs\timeframes\          # Offline timeframe sweep reports (index.html)
-- runs\stress\              # Offline execution stress reports (index.html)
-- reference\cache\        # Pre-cached MQL5 documentation (48 files)
-- webapp\                 # Local web UI static assets (served by scripts/web_app.py)
```

---

## CRITICAL REMINDERS

1. **Always use mql5-lookup BEFORE fixing errors** - don't guess signatures
2. **After compile fails, use mql5-fixer skill** - it knows the patterns
3. **Max 5 fix attempts** - then report to user for manual intervention
4. **param_extractor.py generates ranges automatically** - use it
5. **result_parser.py finds ROBUST params** - profitable on BOTH periods
6. **settings.py has all thresholds** - check before hardcoding
7. **Cloud agents default ON** - check settings.optimization.use_cloud

---

*Last updated: 2025-12-27*
