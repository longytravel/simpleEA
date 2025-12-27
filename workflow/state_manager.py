"""
Workflow State Manager

Enforces step-by-step execution of the stress test workflow.
The agent MUST use this to track progress and cannot skip steps.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict, field
from enum import Enum


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


# Define the workflow steps in order
WORKFLOW_STEPS = [
    "1_load",
    "2_compile",
    "2b_fix_errors",  # Optional, only if compile fails
    "3_extract_params",
    "4_create_wide_ini",
    "5_validate_trades",
    "6_create_opt_ini",
    "7_run_optimization",
    "8_parse_results",
    "9_backtest_robust",
    "10_monte_carlo",
    "11_report"
]

# Steps that can be skipped
OPTIONAL_STEPS = ["2b_fix_errors"]

# Step dependencies
STEP_DEPENDENCIES = {
    "2_compile": ["1_load"],
    "2b_fix_errors": ["2_compile"],
    "3_extract_params": ["1_load"],  # Can run after load, even if compile pending
    "4_create_wide_ini": ["3_extract_params"],
    "5_validate_trades": ["2_compile", "4_create_wide_ini"],
    "6_create_opt_ini": ["5_validate_trades"],
    "7_run_optimization": ["6_create_opt_ini"],
    "8_parse_results": ["7_run_optimization"],
    "9_backtest_robust": ["8_parse_results"],
    "10_monte_carlo": ["9_backtest_robust"],
    "11_report": ["10_monte_carlo"]
}


@dataclass
class StepState:
    """State of a single workflow step."""
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    attempts: int = 0


@dataclass
class WorkflowState:
    """Complete workflow state."""
    ea_name: str
    ea_path: str
    symbol: str = "EURUSD"
    timeframe: str = "H1"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    current_step: str = "1_load"
    steps: Dict[str, StepState] = field(default_factory=dict)

    def __post_init__(self):
        # Initialize all steps if not provided
        if not self.steps:
            for step in WORKFLOW_STEPS:
                self.steps[step] = StepState()


class WorkflowStateManager:
    """
    Manages workflow state with enforcement.

    Rules:
    1. Steps must be completed in order (dependencies)
    2. Cannot skip required steps
    3. State is persisted to JSON after each update
    4. Only one step can be in_progress at a time
    """

    def __init__(self, state_dir: Path = None):
        """Initialize state manager."""
        if state_dir is None:
            state_dir = Path(__file__).parent.parent / "runs"
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state: Optional[WorkflowState] = None
        self.state_file: Optional[Path] = None

    def create_workflow(self, ea_name: str, ea_path: str, symbol: str = "EURUSD") -> WorkflowState:
        """Create a new workflow state."""
        self.state = WorkflowState(
            ea_name=ea_name,
            ea_path=ea_path,
            symbol=symbol
        )

        # Create state file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.state_file = self.state_dir / f"workflow_{ea_name}_{timestamp}.json"
        self._save()

        return self.state

    def load_workflow(self, state_file: Path) -> WorkflowState:
        """Load existing workflow state."""
        self.state_file = Path(state_file)
        with open(self.state_file, 'r') as f:
            data = json.load(f)

        # Reconstruct state
        steps = {}
        for step_name, step_data in data.get('steps', {}).items():
            steps[step_name] = StepState(
                status=StepStatus(step_data['status']),
                started_at=step_data.get('started_at'),
                completed_at=step_data.get('completed_at'),
                output=step_data.get('output', {}),
                error=step_data.get('error'),
                attempts=step_data.get('attempts', 0)
            )

        self.state = WorkflowState(
            ea_name=data['ea_name'],
            ea_path=data['ea_path'],
            symbol=data.get('symbol', 'EURUSD'),
            timeframe=data.get('timeframe', 'H1'),
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', ''),
            current_step=data.get('current_step', '1_load'),
            steps=steps
        )

        return self.state

    def can_start_step(self, step_name: str) -> tuple[bool, str]:
        """
        Check if a step can be started.

        Returns:
            (can_start, reason)
        """
        if not self.state:
            return False, "No workflow loaded"

        if step_name not in WORKFLOW_STEPS:
            return False, f"Unknown step: {step_name}"

        # Check dependencies
        dependencies = STEP_DEPENDENCIES.get(step_name, [])
        for dep in dependencies:
            dep_status = self.state.steps.get(dep, StepState()).status

            # Special case: 2b_fix_errors only needed if 2_compile failed
            if dep == "2_compile" and step_name == "2b_fix_errors":
                if dep_status != StepStatus.FAILED:
                    return False, "Fix errors step only needed if compile failed"
            elif dep in OPTIONAL_STEPS:
                # Optional steps don't block
                continue
            elif dep_status != StepStatus.PASSED:
                return False, f"Dependency '{dep}' not passed (status: {dep_status.value})"

        # Check if already completed
        step_status = self.state.steps.get(step_name, StepState()).status
        if step_status == StepStatus.PASSED:
            return False, f"Step '{step_name}' already passed"

        return True, "OK"

    def start_step(self, step_name: str) -> tuple[bool, str]:
        """
        Mark a step as in_progress.

        Returns:
            (success, message)
        """
        can_start, reason = self.can_start_step(step_name)
        if not can_start:
            return False, reason

        # Update state
        self.state.steps[step_name].status = StepStatus.IN_PROGRESS
        self.state.steps[step_name].started_at = datetime.now().isoformat()
        self.state.steps[step_name].attempts += 1
        self.state.current_step = step_name
        self.state.updated_at = datetime.now().isoformat()

        self._save()
        return True, f"Started step: {step_name}"

    def complete_step(self, step_name: str, output: Dict[str, Any] = None) -> tuple[bool, str]:
        """
        Mark a step as passed.

        Returns:
            (success, message)
        """
        if not self.state:
            return False, "No workflow loaded"

        step = self.state.steps.get(step_name)
        if not step:
            return False, f"Unknown step: {step_name}"

        if step.status != StepStatus.IN_PROGRESS:
            return False, f"Step '{step_name}' not in progress (status: {step.status.value})"

        # Update state
        step.status = StepStatus.PASSED
        step.completed_at = datetime.now().isoformat()
        if output:
            step.output = output

        self.state.updated_at = datetime.now().isoformat()

        # Find next step
        current_idx = WORKFLOW_STEPS.index(step_name)
        if current_idx < len(WORKFLOW_STEPS) - 1:
            next_step = WORKFLOW_STEPS[current_idx + 1]
            # Skip optional steps if not needed
            if next_step == "2b_fix_errors" and self.state.steps["2_compile"].status == StepStatus.PASSED:
                next_step = WORKFLOW_STEPS[current_idx + 2]
            self.state.current_step = next_step

        self._save()
        return True, f"Completed step: {step_name}"

    def fail_step(self, step_name: str, error: str) -> tuple[bool, str]:
        """
        Mark a step as failed.

        Returns:
            (success, message)
        """
        if not self.state:
            return False, "No workflow loaded"

        step = self.state.steps.get(step_name)
        if not step:
            return False, f"Unknown step: {step_name}"

        step.status = StepStatus.FAILED
        step.completed_at = datetime.now().isoformat()
        step.error = error

        self.state.updated_at = datetime.now().isoformat()
        self._save()

        return True, f"Failed step: {step_name} - {error}"

    def get_status(self) -> Dict[str, Any]:
        """Get current workflow status."""
        if not self.state:
            return {"error": "No workflow loaded"}

        return {
            "ea_name": self.state.ea_name,
            "symbol": self.state.symbol,
            "current_step": self.state.current_step,
            "steps": {
                name: {
                    "status": step.status.value,
                    "attempts": step.attempts,
                    "output": step.output if step.output else None
                }
                for name, step in self.state.steps.items()
            }
        }

    def get_next_step(self) -> Optional[str]:
        """Get the next step that can be executed."""
        if not self.state:
            return None

        for step_name in WORKFLOW_STEPS:
            step = self.state.steps.get(step_name, StepState())

            # Skip passed steps
            if step.status == StepStatus.PASSED:
                continue

            # Skip optional steps that aren't needed
            if step_name == "2b_fix_errors":
                compile_step = self.state.steps.get("2_compile", StepState())
                if compile_step.status != StepStatus.FAILED:
                    continue

            # Check if can start
            can_start, _ = self.can_start_step(step_name)
            if can_start:
                return step_name

        return None  # All steps complete

    def _save(self):
        """Save state to JSON file."""
        if not self.state_file:
            return

        data = {
            "ea_name": self.state.ea_name,
            "ea_path": self.state.ea_path,
            "symbol": self.state.symbol,
            "timeframe": self.state.timeframe,
            "created_at": self.state.created_at,
            "updated_at": self.state.updated_at,
            "current_step": self.state.current_step,
            "steps": {
                name: {
                    "status": step.status.value,
                    "started_at": step.started_at,
                    "completed_at": step.completed_at,
                    "output": step.output,
                    "error": step.error,
                    "attempts": step.attempts
                }
                for name, step in self.state.steps.items()
            }
        }

        with open(self.state_file, 'w') as f:
            json.dump(data, f, indent=2)


def get_workflow_commands() -> str:
    """Return help text for workflow commands."""
    return """
WORKFLOW STATE MANAGER COMMANDS
===============================

Create new workflow:
    manager = WorkflowStateManager()
    state = manager.create_workflow("EA_Name", "path/to/EA.mq5", "EURUSD")

Load existing workflow:
    state = manager.load_workflow(Path("runs/workflow_EA_timestamp.json"))

Check if step can start:
    can_start, reason = manager.can_start_step("5_validate_trades")

Start a step:
    success, msg = manager.start_step("5_validate_trades")

Complete a step:
    success, msg = manager.complete_step("5_validate_trades", {"trades": 306})

Fail a step:
    success, msg = manager.fail_step("5_validate_trades", "No trades found")

Get current status:
    status = manager.get_status()

Get next step:
    next_step = manager.get_next_step()
"""


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print(get_workflow_commands())
    else:
        # Demo
        print("Workflow State Manager Demo")
        print("=" * 40)

        manager = WorkflowStateManager()
        state = manager.create_workflow("TestEA", "/path/to/TestEA.mq5", "EURUSD")

        print(f"Created workflow: {manager.state_file}")
        print(f"Current step: {state.current_step}")
        print(f"Next step: {manager.get_next_step()}")

        # Try to start step 5 (should fail - dependencies not met)
        can, reason = manager.can_start_step("5_validate_trades")
        print(f"\nCan start step 5? {can} - {reason}")

        # Start step 1
        success, msg = manager.start_step("1_load")
        print(f"\nStart step 1: {msg}")

        # Complete step 1
        success, msg = manager.complete_step("1_load", {"path": "/path/to/EA.mq5"})
        print(f"Complete step 1: {msg}")
        print(f"Next step: {manager.get_next_step()}")
