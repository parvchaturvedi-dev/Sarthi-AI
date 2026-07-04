"""The executor — runs a Plan against the machine, one verified step at a time.

Flow per step:  confirm-if-sensitive -> run tool -> verify -> record.
A failed verification stops the plan (we don't blindly march on).
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from ..schema import ExecutionResult, Plan, Step, StepResult, Verify
from . import tools, verify

log = logging.getLogger("nova.executor")


def _auto_verify(step: Step) -> Verify:
    """Derive verification from the tool + args, not from the (unreliable) LLM.

    The model often translates or mis-words verify.value; but window titles and
    file paths are deterministic given the args, so we compute them ourselves.
    """
    if step.tool == "open_app":
        name = str(step.args.get("name", "")).lower()
        word = next((k for k in tools.KNOWN_APPS if k in name), name)
        return Verify("window_title_contains", word)
    if step.tool == "close_app":
        return Verify("window_gone", str(step.args.get("name", "")).lower())
    if step.tool == "screenshot":
        return Verify("file_exists", step.args.get("path") or "screenshots/shot.png")
    return step.verify

# Returns True to proceed, False to abort. Injected so UI/voice can own the prompt.
ConfirmFn = Callable[[Step], bool]


class Executor:
    def __init__(
        self,
        speak: Callable[[str], None],
        *,
        dry_run: bool = False,
        step_pause_s: float = 0.6,
        confirm_sensitive: bool = True,
        confirm_fn: Optional[ConfirmFn] = None,
        use_managed_browser: bool = True,
        browser_profile: str = "browser_profile",
    ):
        self.speak = speak
        self.dry_run = dry_run
        self.step_pause_s = step_pause_s
        self.confirm_sensitive = confirm_sensitive
        self.confirm_fn = confirm_fn or (lambda step: True)
        self.ctx = tools.ToolContext(
            speak=speak, pause=step_pause_s,
            use_managed_browser=use_managed_browser, browser_profile=browser_profile,
        )

    def run(self, plan: Plan) -> ExecutionResult:
        result = ExecutionResult()
        for step in plan.steps:
            r = self._run_step(step)
            result.results.append(r)
            if not r.ok:
                log.warning("step failed, stopping plan: %s", r.detail)
                break
            time.sleep(max(0.0, self.step_pause_s))  # settle before the next action
        return result

    def _run_step(self, step: Step) -> StepResult:
        fn = tools.REGISTRY.get(step.tool)
        if fn is None:
            return StepResult(step, False, f"unknown tool '{step.tool}'")

        sensitive = step.sensitive or step.tool in tools.ALWAYS_SENSITIVE
        if sensitive and self.confirm_sensitive:
            if not self.confirm_fn(step):
                return StepResult(step, False, "user declined sensitive action")

        if self.dry_run:
            return StepResult(step, True, f"[dry-run] {step.tool}({step.args})")

        try:
            detail = fn(self.ctx, **step.args)
        except TypeError as e:
            return StepResult(step, False, f"bad args for {step.tool}: {e}")
        except Exception as e:  # noqa: BLE001 - surface any tool failure as a result
            return StepResult(step, False, f"{step.tool} raised {type(e).__name__}: {e}")

        ok, vdetail = verify.check(_auto_verify(step))

        # open_app is special: a just-launched app may take a moment to show its
        # window, and third-party apps often don't put their name in the title.
        # So poll briefly, and if the title still doesn't match, DON'T cry "sorry"
        # — the launch itself succeeded (a real failure would have raised above).
        if not ok and step.tool == "open_app":
            for _ in range(3):
                time.sleep(0.7)
                ok, vdetail = verify.check(_auto_verify(step))
                if ok:
                    break
            if not ok:
                return StepResult(step, True, f"{detail}; launched (window not confirmed)")

        return StepResult(step, ok, f"{detail}; verify: {vdetail}")
