# simpleEA - Agent Instructions

These instructions apply to the whole repo.

## Source of Truth

- `SYSTEM_REGISTRY.md` is the single source of truth for what tools/scripts exist today.
- `WORKFLOW.md` defines the exact core workflow (Steps 1–11).
- `ROADMAP.md` is only for planned work (do not list planned items as implemented in `SYSTEM_REGISTRY.md`).

## Workflow State Files

- Core workflow state files are created as: `runs/workflow_{EA_NAME}_{TIMESTAMP}.json`
- Optional post-step modules MUST record their runs in the same state file under `post_steps[]`.
- Use `scripts/post_step_menu.py` to show the optional module menu + recommendations after Step 11.

## Modularity Rules

- Optional modules must be standalone scripts in `scripts/` (e.g. `scripts/run_execution_stress.py`).
- The optional module catalog lives in `workflow/post_step_modules.py`.
- Keep changes incremental: build one module at a time, add docs, smoke test, then push to GitHub.

## Repo Hygiene

- Do not commit generated results under `runs/` (they are ignored by `.gitignore`).
- Keep documentation readable and accurate; update it with each new implemented module.

