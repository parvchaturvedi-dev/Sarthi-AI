"""The command lifecycle, wired end to end.

    utterance -> plan (brain) -> speak ack -> execute+verify (agent) -> confirm/repair

Everything else (voice, UI, wake) calls `Pipeline.handle(text)`. This is the
single seam where the whole assistant comes together.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from .agent.executor import Executor
from .brain.planner import Planner, _p
from .memory.store import Memory
from .schema import Plan, Step
from .voice.tts import Speaker

log = logging.getLogger("nova.pipeline")

# UI/voice supplies this to ask the user before a sensitive step. Default: allow.
ConfirmFn = Callable[[Step], bool]


class Pipeline:
    def __init__(
        self,
        planner: Planner,
        executor: Executor,
        speaker: Speaker,
        memory: Optional[Memory] = None,
    ):
        self.planner = planner
        self.executor = executor
        self.speaker = speaker
        self.memory = memory
        self.language = getattr(planner, "language", "hindi")

    def handle(self, utterance: str, context: str = "") -> Plan:
        """Plan one command and run it end to end. Returns the executed Plan."""
        utterance = (utterance or "").strip()
        if not utterance:
            return Plan()
        log.info("utterance: %r", utterance)
        plan = self.planner.plan(utterance, context=context)
        return self.run_plan(plan, utterance)

    def run_plan(self, plan: Plan, utterance: str = "") -> Plan:
        """Speak + execute + verify + confirm a plan that is already built.

        Lets the conversation engine hand over either a fast rule-plan or an
        LLM plan through the same speak/execute/log path.
        """
        if plan.say:
            self.speaker.say(plan.say)

        result = self.executor.run(plan) if plan.steps else None

        if result is not None and not result.ok:
            fail = result.first_failure
            detail = fail.detail if fail else "something went wrong"
            log.warning("execution failed: %s", detail)
            self.speaker.say(_p(self.language, "sorry"))
        elif plan.final:
            self.speaker.say(plan.final)

        if self.memory is not None:
            ok = result.ok if result is not None else True
            try:
                self.memory.log(utterance, json.dumps(plan.to_dict()), ok)
            except Exception as e:  # noqa: BLE001
                log.debug("memory log failed: %s", e)

        return plan
