"""The contract between the brain and the machine.

The LLM's ONLY job is to produce a Plan: a spoken acknowledgement, an ordered
list of Steps (tool calls), and a final spoken confirmation. It never runs code
itself. The executor consumes this and is the sole owner of side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Verify:
    """How the executor confirms a step actually happened.

    type:
      window_title_contains  -> active window title includes `value`
      always                  -> treated as success (for side-effect-free steps)
    """
    type: str = "always"
    value: str = ""


@dataclass
class Step:
    tool: str                                  # must exist in the tool registry
    args: Dict[str, Any] = field(default_factory=dict)
    verify: Verify = field(default_factory=Verify)
    sensitive: bool = False                    # requires user confirmation first

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Step":
        v = d.get("verify") or {}
        if isinstance(v, str):                 # tolerate a bare string from the LLM
            v = {"type": "window_title_contains", "value": v}
        return Step(
            tool=d["tool"],
            args=d.get("args", {}) or {},
            verify=Verify(**{**{"type": "always", "value": ""}, **v}),
            sensitive=bool(d.get("sensitive", False)),
        )


@dataclass
class Plan:
    say: str = ""                              # spoken immediately, before acting
    steps: List[Step] = field(default_factory=list)
    final: str = ""                            # spoken after successful execution

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Plan":
        return Plan(
            say=d.get("say", "") or "",
            steps=[Step.from_dict(s) for s in (d.get("steps") or [])],
            final=d.get("final", "") or "",
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StepResult:
    step: Step
    ok: bool
    detail: str = ""


@dataclass
class ExecutionResult:
    results: List[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def first_failure(self) -> Optional[StepResult]:
        return next((r for r in self.results if not r.ok), None)
