# simpleEA - Roadmap (Planned / Not Implemented Yet)

This file documents *planned* extensions to the EA Stress Test System.
It is intentionally separate from `SYSTEM_REGISTRY.md` (which is the source of truth for what exists today).

---

## Goals

1. Keep the core 1‑pair workflow fast and repeatable.
2. Offer optional “confidence boosters” after an EA/parameter set looks good.
3. Add an LLM-driven improvement loop that is *safe, auditable, and model-agnostic* (works with Codex or Claude).
4. Avoid breaking the current stable pipeline while adding complexity.

---

## Post-Step-11 Optional Modules (User Menu)

After Step 11 (dashboard + report), the user should be prompted with optional branches:

### A) Walk-Forward Validation (WF)
**Purpose:** Reduce single-split overfitting risk by testing multiple IS/FWD folds.
**Output:** Fold-by-fold summary + aggregate stability metrics (median PF/ROI/DD, worst fold).

### B) Parameter Stability / Sensitivity
**Purpose:** Detect “knife-edge” parameter sets vs broad plateaus.
**Approach:** Sweep ± small deltas around best params; measure degradation curves.
**Output:** Heatmaps / stability score; highlight sensitive parameters.

### C) Execution Stress Suite (Costs/Slippage/Spread/Rollover)
**Purpose:** See how fragile results are to worse execution than backtest.
**Examples:** Spread multiplier (x1.0/x1.5/x2.0), random slippage, rollover blackout windows.
**Output:** “Stress envelope” for PF/ROI/DD and pass/fail under stress.

### D) Multi-Pair Testing (2 modes)
**Purpose:** Either validate portability or discover additional tradable pairs.

1) **Cross-pair generalization check (harsh, quick)**
   - Reuse the *same* parameters from EURUSD and run on other pairs.
   - Expectation: often degrades; if it holds, that’s a strong robustness signal.
   - Status: implemented via `scripts/run_multipair.py` (offline HTML report).

2) **Per-pair optimization (fair, discovery)**
   - For each pair: run full pipeline (optimize → IS/FWD → MC → dashboard).
   - Output: “pair leaderboard” + suggested portfolio set (see correlation controls below).

### E) Timeframe Sweep (M15/H1/H4)
**Purpose:** Discover where the strategy has edge and reduce regime dependence.
**Output:** Per-timeframe leaderboard (per symbol) with comparable gates.

### F) LLM Improvement Loop (Auto)
**Purpose:** Let an LLM propose and apply strategy improvements, then re-test hands-off.
**Output:** A/B comparison dashboard (baseline vs variant), with gates that prevent overfitting.

---

## Pair & Portfolio Selection (Correlation / Concentration Risk)

The term you’re reaching for is usually **correlation** / **concentration risk**:
multiple pairs can move together (especially USD-driven majors), leading to simultaneous drawdowns.

### Proposed default “major” set (starting point)
For low spreads/liquidity: `EURUSD`, `GBPUSD`, `USDJPY`, `USDCHF`, `USDCAD`, `AUDUSD`, `NZDUSD`.

### What we should measure before recommending “go live on multiple pairs”
1. **PnL correlation matrix**: correlation of daily (or weekly) returns of the EA per pair.
2. **Drawdown overlap**: fraction of time pairs are concurrently in drawdown.
3. **Currency exposure overlap**: count overlapping base/quote exposures (e.g. too much USD risk).

Status:
- Implemented (basic): `scripts/run_multipair.py` now reports currency exposure, daily return correlation, and drawdown overlap.
- Planned (advanced): portfolio selection + exposure caps + correlation-minimizing subset selection.

### Portfolio selection (planned)
Given a set of passing pair-configs, select a subset that:
- minimizes correlation / drawdown overlap,
- respects exposure caps (e.g. max N pairs sharing USD),
- maximizes expected return at acceptable risk.

---

## LLM Improvement Loop (Model-Agnostic Design)

We should not rely on a specific runtime (Codex vs Claude).
Instead, make it **file-based** and **schema-driven**.

### Claude/Codex integration (planned)
- Claude: can use existing `.claude/agents/strategy-improver.md` plus `mql5-lookup` / `mql5-fixer` to draft safe changes.
- Codex: can run the same flow directly via Python orchestration scripts.
- **Key rule:** regardless of LLM, the output should be a structured change plan (JSON) so the application step is deterministic and auditable.

### Inputs the LLM reads (already available)
- `runs/dashboards/.../data.json` (all metrics + splits + MC)
- `runs/{EA}_REPORT.txt` (human summary)
- The EA source code (`.mq5`)

### Outputs the LLM must produce (planned)
1. **Suggestion report** (markdown/text) explaining changes and rationale.
2. **A structured change plan** (JSON), e.g.:
   - `variant_name`
   - `changes[]` (constrained to allowed transformations)
   - `new_inputs[]` (if adding parameters)
   - `risk_notes`

### Safe application approach (planned)
- Create a clean copy: `runs/variants/{EA}/{variant_id}/{EA}_{variant_id}.mq5`
- Apply only allow-listed transformations (deterministic patcher).
- Compile, then re-run the pipeline on the variant.
- Produce an A/B comparison dashboard and only “promote” if it improves OOS + stress gates.

---

## Multi-Terminal MT5 (Planned)

As branching grows (multi-pair + improvements), we should support **multiple MT5 instances**:
- One “mainline” terminal for baseline runs.
- One “experimental” terminal for branches (LLM variants, walk-forward, stress).

Planned approach:
- Add a `--terminal` / `--profile` selector across scripts.
- Each profile has distinct data dirs + report output to avoid collisions.

---

## Cloud On/Off (Planned UX)

Cloud is already configurable in optimization INI.
Planned: make “cloud on/off” a first-class user option in the post-step menu (e.g. overnight local runs).
