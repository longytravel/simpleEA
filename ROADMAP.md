# simpleEA - Roadmap (Status + Planned)

This file documents extensions to the EA Stress Test System and their status.
It is intentionally separate from `SYSTEM_REGISTRY.md` (which is the source of truth for what exists today).

---

## Goals

1. Keep the core 1-pair workflow fast and repeatable.
2. Offer optional "confidence boosters" after an EA/parameter set looks good.
3. Add an LLM-driven improvement loop that is safe, auditable, and model-agnostic (Codex or Claude).
4. Avoid breaking the current stable pipeline while adding complexity.

---

## Post-Step Optional Modules (User Menu)

After Step 11 (dashboard + report), the user should be prompted with optional branches.

Menu status:
- Implemented: `scripts/post_step_menu.py` (reads `workflow/post_step_modules.py` + state `post_steps[]`)

### A) Walk-Forward Validation (multi-fold)
Purpose: reduce single-split overfitting risk by testing multiple IS/FWD folds.
Output: fold-by-fold summary + aggregate stability metrics (median PF/ROI/DD, worst fold).
Status: implemented via `scripts/run_walk_forward.py` (offline HTML report).

### B) Parameter Stability / Sensitivity Sweep
Purpose: detect "knife-edge" parameter sets vs broad plateaus.
Approach: sweep +/- small deltas around best params; measure degradation curves.
Output: heatmaps / stability score; highlight sensitive parameters.
Status: planned.

### C) Execution Stress Suite (Costs/Slippage/Spread)
Purpose: see how fragile results are to worse execution than backtest.
Examples: spread multiplier (x1.0/x1.5/x2.0), slippage pips/side, commission multiplier.
Output: sensitivity table + pass/fail gates under stress.
Status: implemented via `scripts/run_execution_stress.py` (offline HTML report).

### D) Multi-Pair Testing (2 modes)
Purpose: either validate portability or discover additional tradable pairs.

1) Cross-pair generalization check (harsh, quick)
   - Reuse the same parameters from the primary pair and run on other pairs.
   - Expectation: often degrades; if it holds, that's a strong robustness signal.
   - Status: implemented via `scripts/run_multipair.py` (offline HTML report).

2) Per-pair optimization (fair, discovery)
   - For each pair: run full pipeline (optimize -> IS/FWD -> MC -> dashboard).
   - Output: pair leaderboard + suggested portfolio set (see correlation controls below).
   - Status: planned.

### E) Timeframe Sweep (M15/H1/H4)
Purpose: discover where the strategy has edge and reduce regime dependence.
Output: per-timeframe leaderboard (per symbol) with comparable gates.
Status: implemented via `scripts/run_timeframes.py` (offline HTML report).

### F) LLM Improvement Loop (Auto)
Purpose: let an LLM propose and apply strategy improvements, then re-test hands-off.
Output: A/B comparison dashboard (baseline vs variant), with gates that prevent overfitting.
Status: planned.

---

## Pair & Portfolio Selection (Correlation / Concentration Risk)

The term you're reaching for is usually correlation / concentration risk:
multiple pairs can move together (especially USD-driven majors), leading to simultaneous drawdowns.

### Proposed default "major" set (starting point)
For low spreads/liquidity:
`EURUSD`, `GBPUSD`, `USDJPY`, `USDCHF`, `USDCAD`, `AUDUSD`, `NZDUSD`.

### What we should measure before recommending "go live on multiple pairs"
1. PnL correlation matrix: correlation of daily (or weekly) returns of the EA per pair.
2. Drawdown overlap: fraction of time pairs are concurrently in drawdown.
3. Currency exposure overlap: overlapping base/quote exposures (e.g. too much USD risk).

Status:
- Implemented (basic): `scripts/run_multipair.py` reports currency exposure, daily return correlation, and drawdown overlap.
- Implemented (basic): `scripts/run_multipair.py` includes heuristic portfolio suggestions.
- Planned (advanced): exposure caps + correlation-minimizing subset selection across per-pair optimized configs.

---

## LLM Improvement Loop (Model-Agnostic Design)

Do not rely on a specific runtime (Codex vs Claude). Make it file-based and schema-driven.

Inputs the LLM reads (already available):
- `runs/dashboards/.../data.json` (all metrics + splits + MC)
- `runs/{EA}_REPORT.txt` (human summary)
- The EA source code (`.mq5`)

Outputs the LLM must produce (planned):
1. Suggestion report (markdown/text) explaining changes and rationale.
2. A structured change plan (JSON), constrained to allow-listed transformations.

Safe application approach (planned):
- Create a clean copy: `runs/variants/{EA}/{variant_id}/{EA}_{variant_id}.mq5`
- Apply only allow-listed transformations (deterministic patcher).
- Compile, then re-run the pipeline on the variant.
- Produce an A/B comparison dashboard and only promote if it improves OOS + stress gates.

---

## Multi-Terminal MT5 (Planned)

As branching grows (multi-pair + improvements), support multiple MT5 instances:
- One mainline terminal for baseline runs.
- One experimental terminal for branches (LLM variants, walk-forward, stress).

Planned approach:
- Add a `--terminal` / `--profile` selector across scripts.
- Each profile has distinct data dirs + output dirs to avoid collisions.

---

## Cloud On/Off (Planned UX)

Cloud is already configurable in optimization INI.
Planned: make "cloud on/off" a first-class user option in the post-step menu (e.g. overnight local runs).

---

## Local Web UI (Planned)

Goal: a local web app that shows the workflow steps, current progress, and post-step options.

Constraints:
- No external API calls required (runs locally/offline).
- Uses the existing CLI scripts (subprocess) and reads/writes the existing state files in `runs/`.

Approach:
- UI reads `runs/workflow_*.json` to show step statuses and post-step runs (`post_steps[]`).
- Buttons trigger existing scripts (e.g. `scripts/run_walk_forward.py`) via subprocess and stream logs.
- UI links directly to the generated offline HTML outputs (dashboards, post-step reports).
