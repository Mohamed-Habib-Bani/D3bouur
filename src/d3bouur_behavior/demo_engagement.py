#!/usr/bin/env python3
"""Demo/proof that engage.py's engagement logic is correctly wired into
BehaviorStateMachine's `_orient_toward_person()`, via the EngagementProvider
interface (state_machine.py) engagement_provider.py bridges to.

Run from this directory (no colcon build needed, same convention as
demo_state_machine.py):

    python3 demo_engagement.py

No real camera/Arduino involved — same reasoning as demo_state_machine.py's
"conversation ended" being simulated: `person_detected(direction)` is called
directly with a simulated Direction, standing in for a future real
ultrasonic trigger. What's under test here is the state machine's own
branching logic (does it correctly go to ENGAGING only on ENGAGED, and back
to MOVING on NO_FACE/TIMEOUT), driven by a FakeEngagementProvider that
returns whichever EngagementOutcome each scenario needs — exactly the same
"trivial fake standing in for the real thing" approach demo_state_machine.py
uses for ConversationBrain, just on the engagement side instead. This is
deliberately NOT a test of engage.py's own real face-detection logic (that
was already verified standalone against the real camera in an earlier
session, per onvif_camera's own testing) or of the RealEngagementProvider
translation layer (see test_engagement_provider.py for that, which mocks
engage.py's run_engagement_attempt() instead of the state machine).

The conversation brain here is a lightweight fake, not real Ollama — this
demo's focus is the orientation branch, already proven separately by
demo_state_machine.py against a real brain; no need to pay Ollama's latency
for a test that isn't exercising that path.
"""

import logging
import sys
from pathlib import Path
from typing import List, Optional

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from d3bouur_behavior import (  # noqa: E402
    BehaviorStateMachine,
    ChatResultLike,
    Direction,
    EngagementOutcome,
    State,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class FakeChatResult:
    def __init__(self, text: str) -> None:
        self.text = text
        self.provider = "fake"
        self.elapsed = 0.0


class FakeConversationBrain:
    """Stands in for ConversationBrain — this demo isn't exercising
    conversation behavior, only the orientation/engagement branch."""

    def chat(self, message: str) -> ChatResultLike:
        return FakeChatResult(f"(fake reply to: {message!r})")


class FakeEngagementProvider:
    """Stands in for engagement_provider.RealEngagementProvider. Scripted
    with a fixed outcome (or a list consumed one-per-call) so each scenario
    can force exactly the branch it wants to exercise, without a real
    camera. Records every Direction it was called with, so tests can assert
    the state machine actually forwarded the right one."""

    def __init__(self, outcomes: List[EngagementOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.calls: List[Optional[Direction]] = []

    def __call__(self, direction: Optional[Direction]) -> EngagementOutcome:
        self.calls.append(direction)
        if not self._outcomes:
            raise AssertionError("FakeEngagementProvider called more times than scripted")
        return self._outcomes.pop(0)


FRONT = Direction(pan=0.5, tilt=0.6, label="front")


def build_state_machine(outcomes: List[EngagementOutcome]) -> tuple[BehaviorStateMachine, FakeEngagementProvider]:
    provider = FakeEngagementProvider(outcomes)
    sm = BehaviorStateMachine(
        conversation_brain=FakeConversationBrain(),
        engagement_provider=provider,
        timeout_seconds=6.0,
    )
    return sm, provider


def scenario_engaged(sm: BehaviorStateMachine, provider: FakeEngagementProvider) -> None:
    print("\n=== Scenario 1: ENGAGED — face persisted, starts a conversation ===")
    sm.person_detected(FRONT)
    assert sm.state is State.ENGAGING, f"expected ENGAGING, got {sm.state}"
    assert provider.calls == [FRONT], f"expected provider called with [{FRONT}], got {provider.calls}"

    sm.visitor_said("Bonjour !")
    sm.conversation_ended()
    assert sm.state is State.MOVING, f"expected MOVING after natural end, got {sm.state}"
    print("Scenario 1 PASSED — ENGAGED led to a real conversation, direction forwarded correctly.")


def scenario_no_face(sm: BehaviorStateMachine, provider: FakeEngagementProvider) -> None:
    print("\n=== Scenario 2: NO_FACE — nothing there, resumes MOVING immediately ===")
    sm.person_detected(FRONT)
    assert sm.state is State.MOVING, f"expected immediate MOVING on NO_FACE, got {sm.state}"
    assert provider.calls == [FRONT]
    print("Scenario 2 PASSED — RETURN_NO_FACE resumed MOVING without ever engaging.")


def scenario_timeout(sm: BehaviorStateMachine, provider: FakeEngagementProvider) -> None:
    print("\n=== Scenario 3: TIMEOUT — face seen but never persisted, resumes MOVING ===")
    left = Direction(pan=0.1, tilt=0.5, label="left")
    sm.person_detected(left)
    assert sm.state is State.MOVING, f"expected immediate MOVING on TIMEOUT, got {sm.state}"
    assert provider.calls == [left]
    print("Scenario 3 PASSED — RETURN_TIMEOUT resumed MOVING without ever engaging.")


def scenario_provider_failure() -> None:
    print("\n=== Scenario 4: provider raises — treated as safe NO_FACE, no crash ===")

    def broken_provider(direction: Optional[Direction]) -> EngagementOutcome:
        raise RuntimeError("simulated camera/detector failure")

    sm = BehaviorStateMachine(
        conversation_brain=FakeConversationBrain(),
        engagement_provider=broken_provider,
        timeout_seconds=6.0,
    )
    sm.person_detected(FRONT)
    assert sm.state is State.MOVING, f"expected MOVING after provider failure, got {sm.state}"
    print("Scenario 4 PASSED — provider exception didn't crash the state machine.")


def scenario_no_provider_stub_unchanged() -> None:
    print("\n=== Scenario 5: no engagement_provider — old stub behavior unchanged ===")
    sm = BehaviorStateMachine(conversation_brain=FakeConversationBrain(), timeout_seconds=6.0)
    sm.person_detected()  # no Direction either — still valid, matches old no-arg call
    assert sm.state is State.ENGAGING, f"expected ENGAGING (stub always-ENGAGED), got {sm.state}"
    print("Scenario 5 PASSED — omitting engagement_provider preserves the pre-wiring stub behavior.")


def main() -> None:
    sm, provider = build_state_machine([EngagementOutcome.ENGAGED])
    scenario_engaged(sm, provider)

    sm, provider = build_state_machine([EngagementOutcome.NO_FACE])
    scenario_no_face(sm, provider)

    sm, provider = build_state_machine([EngagementOutcome.TIMEOUT])
    scenario_timeout(sm, provider)

    scenario_provider_failure()
    scenario_no_provider_stub_unchanged()

    print("\nAll scenarios passed.")


if __name__ == "__main__":
    main()
