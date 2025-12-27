"""
Post-step optional modules catalog.

This file exists to prevent "LLM forgetting": it is the single, importable list
of optional modules that can be run after the core workflow completes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class PostStepModule:
    id: str
    title: str
    description: str
    implemented: bool
    command_template: str
    state_key: Optional[str] = None  # name used in workflow.post_steps tracking


POST_STEP_MODULES: List[PostStepModule] = [
    PostStepModule(
        id="execution_stress",
        title="Execution Stress Suite",
        description="Offline sensitivity to spread/slippage/commission (fast, deterministic).",
        implemented=True,
        command_template='python scripts/run_execution_stress.py --state "{state}" --open',
        state_key="execution_stress",
    ),
    PostStepModule(
        id="multipair",
        title="Multi-Pair Follow-up",
        description="Generalization check across a basket of pairs + correlation/drawdown overlap.",
        implemented=True,
        command_template='python scripts/run_multipair.py --state "{state}" --open',
        state_key="multipair",
    ),
    PostStepModule(
        id="timeframes",
        title="Timeframe Sweep",
        description="Re-run best params across multiple timeframes on the same symbol.",
        implemented=True,
        command_template='python scripts/run_timeframes.py --state "{state}" --open',
        state_key="timeframes",
    ),
    PostStepModule(
        id="walk_forward",
        title="Walk-Forward Validation",
        description="Multi-fold IS/FWD validation to reduce single-split overfitting risk.",
        implemented=True,
        command_template='python scripts/run_walk_forward.py --state "{state}" --open',
        state_key="walk_forward",
    ),
    PostStepModule(
        id="param_sensitivity",
        title="Parameter Sensitivity Sweep",
        description="Local perturbation sweep around best params to detect knife-edge settings.",
        implemented=False,
        command_template='(planned) python scripts/run_param_sensitivity.py --state "{state}" --open',
        state_key="param_sensitivity",
    ),
    PostStepModule(
        id="llm_improvement_loop",
        title="LLM Improvement Loop",
        description="Have an LLM propose safe EA changes, fork a variant, then re-optimize A/B.",
        implemented=False,
        command_template='(planned) python scripts/run_llm_improve.py --state "{state}"',
        state_key="llm_improvement_loop",
    ),
]
