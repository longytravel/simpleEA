# EA Stress Test Workflow - Definitive Steps

**This document defines the EXACT steps for testing an EA.**
**Each step MUST be completed before proceeding to the next.**
**The agent MUST update state file after each step.**

---

## Complete Workflow (1-Pair Test)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 1: LOAD EA                                                        │
│  Action: Find and validate .mq5 file exists                            │
│  Tool: Check config.MT5_EXPERTS_PATH or user-provided path             │
│  Gate: File exists                                                      │
│  Output: ea_path                                                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 1B: INJECT OnTester (profit-first)                                │
│  Action: Inject/replace OnTester() with profit-first custom scoring     │
│  Tool: python scripts/inject_ontester.py "ea_path"                     │
│  Gate: Injection successful                                             │
│  Output: Modified EA, use_criterion=6                                   │
│  Note: Profit is primary; score penalizes DD + jagged curves            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 2: COMPILE                                                        │
│  Action: Compile MQ5 → EX5                                             │
│  Tool: python scripts/compile_ea.py "ea_path"                          │
│  Gate: 0 errors                                                         │
│  On Fail: → STEP 2B (Fix Errors)                                       │
│  Output: ex5_path                                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                         ┌──────────┴──────────┐
                         │ Errors?             │
                         └──────────┬──────────┘
                                    │ YES
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 2B: FIX COMPILATION ERRORS                                        │
│  Action: Fix errors using reference documentation                       │
│  Tools (in order):                                                      │
│    1. mql5-fixer skill (check patterns.md, mt4-to-mt5.md)              │
│    2. mql5-lookup skill (get correct function signatures)               │
│    3. opus-fixer agent (for complex errors after 3 failed attempts)     │
│  Gate: Compile succeeds OR max_attempts (5) reached                     │
│  Output: fixed code, recompile                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 3: EXTRACT PARAMETERS                                             │
│  Action: Parse EA source to get all input parameters                    │
│  Tool: python optimizer/param_extractor.py "ea_path"                   │
│  Gate: Parameters extracted successfully                                │
│  Output: parameters.json with names, types, defaults, ranges            │
│  User Check: Review parameters, approve which to optimize               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 4: CREATE WIDE PARAMETERS + OPTIMIZATION RANGES                   │
│  Action: Intelligent parameter analysis for BOTH validation and opt     │
│  Tool: python optimizer/param_intelligence.py "EA.mq5" --mode both      │
│  Output:                                                                │
│    - runs/{EA}_wide_params.json  (permissive values for validation)    │
│    - runs/{EA}_opt_inputs.json   (intelligent ranges for optimization) │
│  Gate: Both files created                                               │
│  Claude Review: Check output, override if domain knowledge is better    │
│  NOTE: Script handles common patterns, Claude handles exceptions        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 5: VALIDATE EA TRADES (Simple Backtest)                           │
│  Action: Run SIMPLE backtest with WIDE params - NO OPTIMIZATION         │
│  Tool: python scripts/run_backtest.py "EA" --params runs/{EA}_wide_params.json
│  Period: 4 years (2021.12.24 → 2025.12.24)                             │
│  Gate: total_trades > 0 (expect hundreds/thousands with wide params)   │
│  On Fail: EA doesn't trade → STOP (logic broken)                       │
│  Output: trade_count (loss expected - that's OK for validation)         │
│  User Check: Does it trade heavily? Commission included?                │
│  NOTE: Single backtest, no genetic algorithm, just validation           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 6: CREATE OPTIMIZATION INI                                        │
│  Action: Create INI using intelligent ranges from Step 4                │
│  Tool: python optimizer/ini_builder.py "ea_path" --cloud on --symbol X  │
│  Note: Auto-reads runs/{EA}_opt_inputs.json if it exists               │
│  Settings (from config.py):                                            │
│    - Model: 1-minute OHLC                                              │
│    - Deposit: £3,000, Leverage: 1:100                                  │
│    - In-sample: 3 years (2021.12.24 → 2024.12.24)                      │
│    - Forward: 1 year (2024.12.24 → 2025.12.24)                         │
│    - Cloud: ON (from settings.optimization.use_cloud)                   │
│  Gate: INI file created with parameter ranges                           │
│  Output: runs/EA_SYMBOL_optimize.ini                                    │
│  User Check: Review parameter ranges, approve                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 7: RUN OPTIMIZATION                                               │
│  Action: Execute genetic optimization in MT5                            │
│  Tool: python scripts/run_optimization.py "EA" --ini file.ini          │
│  Timeout: 3600s (1 hour) default, can extend                           │
│  Gate: Optimization completes, XML files exist                          │
│  Output: EA_OPT.xml, EA_OPT.forward.xml                                │
│  User Check: Confirm optimization completed                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 8: PARSE OPTIMIZATION RESULTS                                     │
│  Action: Find parameters profitable on BOTH in-sample AND forward       │
│  Tool: python optimizer/result_parser.py "EA_Name" --symbol SYMBOL      │
│  Gate: robust_passes > 0 (at least one pass profitable on both)         │
│  On Fail: No robust parameters → EA fails stress test                  │
│  Output: best parameters, top 5 results                                 │
│  User Check: Review best params, in-sample vs forward performance       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 9: BACKTEST WITH ROBUST PARAMETERS                                │
│  Action: Run full backtest with best parameters                         │
│  Tool: python scripts/run_backtest.py "EA" --params robust_params.json  │
│  Thresholds (from settings.py):                                        │
│    - min_profit_factor: 1.5 (primary pair)                             │
│    - max_drawdown_pct: 30%                                             │
│    - min_trades: 50                                                     │
│  Gate: PF >= threshold, DD <= threshold                                 │
│  Output: report.htm, metrics                                            │
│  User Check: Review metrics against thresholds                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 10: MONTE CARLO SIMULATION                                        │
│  Action: Shuffle trades 1000x to test robustness                        │
│  Tool: python tester/montecarlo.py "report.htm" -n 1000                │
│  Thresholds (from settings.py):                                        │
│    - confidence_min: 70%                                               │
│    - max_ruin_probability: 5%                                          │
│  Gate: confidence >= 70%, ruin <= 5%                                   │
│  On Fail: Strategy not robust → may work but risky                     │
│  Output: MC results JSON                                                │
│  User Check: Review confidence level, ruin probability                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 11: FINAL REPORT                                                  │
│  Action: Summarize all results                                          │
│  Tool: backtest-analyzer skill                                         │
│  Output: Pass/Fail verdict, metrics table, recommendations              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Step Details with Exact Commands

### Step 1: Load EA
```bash
# If full path provided:
ls "C:\path\to\EA.mq5"

# If name only:
ls "C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\A42909ABCDDDD04324904B57BA9776B8\MQL5\Experts\EA_Name.mq5"
```

### Step 1B: Inject OnTester (profit-first)
```bash
python scripts/inject_ontester.py "path/to/EA.mq5"
```
Output: JSON with `success`, `had_existing`, `use_criterion`
Note: This replaces any existing OnTester(); a one-time backup is created as `*.mq5.ontester.bak`

### Step 1C: Inject Safety (optional but recommended for live)
```bash
python scripts/inject_safety.py "path/to/EA.mq5"
```
Output: JSON with `success`, `changed`, `backup`
Note: Creates a one-time backup as `*.mq5.safety.bak`

### Step 2: Compile
```bash
python scripts/compile_ea.py "path/to/EA.mq5"
```
Output: JSON with `success`, `errors`, `warnings`

### Step 2B: Fix Errors
1. Read error messages
2. Check `.claude/skills/mql5-fixer/patterns.md`
3. Check `.claude/skills/mql5-fixer/mt4-to-mt5.md`
4. Lookup: `python reference/mql5_indexer.py search "function_name"`
5. Apply fix with Edit tool
6. Recompile
7. If still failing after 3 attempts → use opus-fixer agent

### Step 3: Extract Parameters
```bash
python optimizer/param_extractor.py "path/to/EA.mq5"
```
Output: JSON with all parameters, defaults, and auto-generated ranges

### Step 4: Create Wide Parameters (Uses param_intelligence.py)
```bash
# Unified parameter intelligence - generates BOTH wide params and opt ranges
python optimizer/param_intelligence.py "path/to/EA.mq5" --mode both

# Outputs:
#   runs/{EA}_wide_params.json    - Permissive values for validation
#   runs/{EA}_opt_inputs.json     - Optimization ranges

# Claude should REVIEW the output and adjust if:
#   - Parameter semantics are misunderstood
#   - Domain knowledge suggests different ranges
#   - EA has unusual parameter patterns
```

### Step 5: Validate EA Trades (Simple Backtest)
```bash
python scripts/run_backtest.py "EA_Name" --params runs/{EA}_wide_params.json
```
Check: `total_trades > 0` (expect hundreds+), loss is OK for validation
NOTE: NO optimization here - just confirming EA logic works

### Step 6: Create Optimization INI (Uses param_intelligence.py output)
```bash
# ini_builder.py now reads from {EA}_opt_inputs.json if it exists
# Use --criterion 6 for Custom OnTester optimization (after OnTester injection)
python optimizer/ini_builder.py "path/to/EA.mq5" --cloud on --symbol EURUSD --output runs/ --criterion 6
```

### Step 7: Run Optimization
```bash
python scripts/run_optimization.py "EA_Name" --ini runs/EA_optimize.ini --timeout 3600
```

### Step 8: Parse Results
```bash
python optimizer/result_parser.py "EA_Name" --symbol EURUSD
```
Key output: `robust_passes`, `best.parameters`, `best.in_sample`, `best.forward`

### Step 9: Backtest Robust Params
```bash
# First save params to JSON
echo '{"param1": value1, "param2": value2}' > runs/robust_params.json

# Then backtest
python scripts/run_backtest.py "EA_Name" --symbol EURUSD --params runs/robust_params.json
```

### Step 10: Monte Carlo
```bash
python tester/montecarlo.py "path/to/report.htm" -n 1000
```
Note: uses per-trade net results (includes commission + swap) extracted from the MT5 Deals table.
Key output: `confidence_level`, `probability_of_ruin`, `is_robust`

### Step 11: Report (Dashboard)
Generate an offline HTML dashboard (MT5-like overview with equity curve, IS/OOS ranges, MC summary):
```bash
python scripts/generate_dashboard.py --state runs/workflow_EA_*.json
```
Output: `runs/dashboards/{EA}_YYYYMMDD_HHMMSS/index.html` (open in a browser).
Tip: the dashboard is interactive (sortable/filterable passes). Use `compare.html` for IS/FWD vs re-run comparisons.
Use `--passes N` to control how many top robust passes are precomputed (default: 20).

Also generate a human-readable text report (ROI + quality + costs):
```bash
python scripts/generate_text_report.py --state runs/workflow_EA_*.json
```
Output: `runs/{EA}_REPORT.txt`.

Optional: serve dashboards as a local web app:
```bash
python -m http.server -d runs/dashboards 8000
```
Then open `http://localhost:8000/`.

---

## Post-Step Optional Modules (Planned)

After Step 11, the system should offer optional “confidence boosters” (walk-forward, stability, stress, multi-pair, timeframe sweep, LLM improvements).

See `ROADMAP.md` for the current plan (most modules are not implemented yet).

### Optional: Multi-Pair Follow-up (Implemented)
Run a quick “generalization check” using the best params found in the workflow, across a basket of pairs (includes currency exposure + return correlation + drawdown overlap):
```bash
python scripts/run_multipair.py --state runs/workflow_EA_*.json --open
```
Output: `runs/multipair/{EA}_YYYYMMDD_HHMMSS/index.html`

---

## State File Structure

The agent MUST maintain this state file: `runs/workflow_state.json`

```json
{
  "ea_name": "Auction_Theory_Safe",
  "ea_path": "C:\\...\\Auction_Theory_Safe.mq5",
  "symbol": "EURUSD",
  "started_at": "2025-12-26T10:30:00",
  "current_step": 5,
  "steps": {
    "1_load": {
      "status": "passed",
      "output": {"path": "..."}
    },
    "2_compile": {
      "status": "passed",
      "errors": 0,
      "fix_attempts": 0
    },
    "3_extract_params": {
      "status": "passed",
      "param_count": 14,
      "optimize_count": 8
    },
    "4_create_wide_ini": {
      "status": "passed",
      "ini_path": "runs/..."
    },
    "5_validate_trades": {
      "status": "in_progress",
      "trades": null
    },
    "6_create_opt_ini": {
      "status": "blocked",
      "requires": "5_validate_trades"
    }
  },
  "results": {
    "validation_trades": null,
    "optimization_passes": null,
    "robust_params": null,
    "backtest_metrics": null,
    "monte_carlo": null
  }
}
```

---

## Gate Conditions

| Step | Gate | On Fail |
|------|------|---------|
| 1 | File exists | STOP - file not found |
| 1B | Injection successful | STOP - injection error |
| 2 | 0 errors | → Step 2B |
| 2B | Compile succeeds within 5 attempts | STOP - unfixable |
| 3 | Parameters extracted | STOP - parse error |
| 4 | INI created | STOP - error |
| 5 | trades > 0 | STOP - EA doesn't trade |
| 6 | INI created | STOP - error |
| 7 | Optimization completes | STOP - timeout/error |
| 8 | robust_passes > 0 | FAIL - no robust params |
| 9 | PF >= 1.5, DD <= 30% | FAIL - poor performance |
| 10 | confidence >= 70%, ruin <= 5% | WARN - not robust |

---

## User Checkpoints

After each step, STOP and show:
1. What was done
2. Key outputs/metrics
3. Pass/fail status
4. Ask to continue or abort

---

*This workflow is the definitive reference. The stress-tester agent MUST follow these steps in order.*
