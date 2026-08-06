#!/usr/bin/env python3
"""Demo/proof for the D3BOUUR behavior state machine.

Run from this directory (no colcon build needed, same convention as
d3bouur_conversation/demo_chat.py):

    python3 demo_state_machine.py

No real hardware is involved. "Person detected" and "conversation ended"
are simulated by calling the state machine's event methods directly, in
place of a test script that would later fire them from real sensor/NLU
signals. The conversation brain IS real (Ollama, local) — this proves the
Engaging state actually drives it, not a stub.

Demonstrates both ways out of Engaging:
    1. Natural End — conversation_ended() fired after a couple of real turns.
    2. Timeout — no activity, tick() called periodically until it resumes
       on its own.
Plus one robustness check: firing an event in a state that doesn't expect
it is ignored, not a crash.
"""

import logging
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONVERSATION_PKG_DIR = SCRIPT_DIR.parent / "d3bouur_conversation"
sys.path.insert(0, str(CONVERSATION_PKG_DIR))

from d3bouur_behavior import BehaviorStateMachine, State  # noqa: E402
from d3bouur_conversation import ConversationBrain, KnowledgeBase  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

TIMEOUT_SECONDS = 6.0


def build_state_machine() -> BehaviorStateMachine:
    knowledge_base = KnowledgeBase()
    brain = ConversationBrain(knowledge_base=knowledge_base)
    return BehaviorStateMachine(conversation_brain=brain, timeout_seconds=TIMEOUT_SECONDS)


def scenario_natural_end(sm: BehaviorStateMachine) -> None:
    print("\n=== Scenario 1: Natural End ===")
    sm.person_detected()
    assert sm.state is State.ENGAGING, f"expected ENGAGING, got {sm.state}"

    sm.visitor_said("Bonjour !")
    sm.visitor_said("Quelles formations proposez-vous ?")

    sm.conversation_ended()
    assert sm.state is State.MOVING, f"expected MOVING after natural end, got {sm.state}"
    print("Scenario 1 PASSED — resumed to MOVING via Natural End.")


def scenario_timeout(sm: BehaviorStateMachine) -> None:
    print(f"\n=== Scenario 2: Timeout (no activity for {TIMEOUT_SECONDS:.0f}s) ===")
    sm.person_detected()
    assert sm.state is State.ENGAGING, f"expected ENGAGING, got {sm.state}"

    start = time.monotonic()
    while sm.state is State.ENGAGING:
        time.sleep(1.0)
        elapsed = time.monotonic() - start
        print(f"  ... {elapsed:.1f}s elapsed, no visitor_said() calls, timeout at {TIMEOUT_SECONDS:.0f}s")
        sm.tick()

    assert sm.state is State.MOVING, f"expected MOVING after timeout, got {sm.state}"
    print("Scenario 2 PASSED — resumed to MOVING via Timeout.")


def scenario_ignored_event(sm: BehaviorStateMachine) -> None:
    print("\n=== Scenario 3: Invalid event is ignored, not a crash ===")
    assert sm.state is State.MOVING
    sm.conversation_ended()  # meaningless while MOVING — should be a no-op
    assert sm.state is State.MOVING, "conversation_ended() while MOVING should be ignored"
    print("Scenario 3 PASSED — conversation_ended() while MOVING was safely ignored.")


def main() -> None:
    sm = build_state_machine()
    print(f"Initial state: {sm.state.value}")

    scenario_natural_end(sm)
    scenario_timeout(sm)
    scenario_ignored_event(sm)

    print("\nAll scenarios passed.")


if __name__ == "__main__":
    main()
