"""D3BOUUR's core behavior state machine.

States (see docs/D3BOUUR_Project_Handoff.md §6 for the original design):

    MOVING ----person_detected()----> PERSON_DETECTED --(auto)--> ENGAGING
    ENGAGING --conversation_ended()--> MOVING   (Natural End)
    ENGAGING --tick(), timed out------> MOVING   (Timeout)

Design choices, and why:

* **Framework-agnostic, not a ROS 2 node.** The architecture doc places this
  as a ROS 2 node with topics to real sensor/perception/navigation nodes —
  but none of those exist yet, so a topic-based design today would just be
  plumbing with nothing real on either end. This mirrors how
  d3bouur_conversation was built: pure Python, directly testable, wrapped in
  a thin rclpy node later once there's something real to subscribe to.

* **"Person Detected" is a real, momentary state, not folded into the
  MOVING->ENGAGING transition.** Per the handoff doc, entering it means
  stopping the robot and turning the head servo — real physical actions
  with real duration once actuators exist. `_orient_toward_person()` is a
  stub today, so the state currently passes through in the same call as
  `person_detected()`, but the structure is already correct: swap the stub
  for a blocking servo call later and PERSON_DETECTED will naturally take
  wall-clock time without changing the state machine itself.

* **No separate "Resume" state.** Resuming just means "go back to MOVING" —
  there's no distinct action or duration attached to it beyond that, so
  giving it its own enum value would be a state with no behavior of its
  own. Both exit paths call the same `_resume_moving()`.

* **Events are the only way in or out of a state** (`person_detected()`,
  `visitor_said()`, `conversation_ended()`, `tick()`) — nothing here decides
  *when* a person is detected or *when* a conversation is "over"; that
  judgment belongs to whatever fires the event (today: a test script:
  eventually: perception nodes on the detection side, and — this is an open
  design question, not solved here — likely an NLU/LLM-based end-of-turn
  signal on the natural-end side). Firing an event in a state that doesn't
  expect it is logged and ignored, not an error: real-world events
  (sensors, speech) arrive asynchronously and can't be prevented from
  arriving at an inconvenient time.

* **Decoupled from ConversationBrain by structural typing (Protocol), not a
  concrete import.** This module works with any object exposing
  `.chat(text) -> object with .text/.provider/.elapsed`. That means unit
  tests can hand it a trivial fake brain with no Ollama and no dependency
  on the d3bouur_conversation package at all — only the demo script, which
  chooses to plug in the real ConversationBrain, needs that dependency.
  Consequently `visitor_said()` catches a broad `Exception` around the
  brain call rather than a specific error type it has no way to know about
  — normally too broad, but justified here because the one hard
  requirement (per the project's "technology demonstration platform"
  framing) is that a broken conversation turn must never crash the state
  machine mid-demo.
"""

import logging
import time
from enum import Enum
from typing import Callable, Optional, Protocol

logger = logging.getLogger(__name__)


class State(Enum):
    MOVING = "moving_mapping"
    PERSON_DETECTED = "person_detected"
    ENGAGING = "engaging"


class ExitReason(Enum):
    TIMEOUT = "timeout"
    NATURAL_END = "natural_end"


class ChatResultLike(Protocol):
    text: str
    provider: str
    elapsed: float


class ConversationBrainLike(Protocol):
    def chat(self, message: str) -> ChatResultLike: ...


OnStateChange = Callable[[State, State, str], None]


class BehaviorStateMachine:
    """Ties movement, person detection, and conversation together.

    `conversation_brain` only needs a `.chat(text)` method (see
    ConversationBrainLike) — pass the real ConversationBrain for an actual
    demo, or a stub for fast/offline unit tests.
    """

    def __init__(
        self,
        conversation_brain: ConversationBrainLike,
        timeout_seconds: float = 8.0,
        clock: Callable[[], float] = time.monotonic,
        on_state_change: Optional[OnStateChange] = None,
    ) -> None:
        self._brain = conversation_brain
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._on_state_change = on_state_change
        self._state = State.MOVING
        self._last_activity: Optional[float] = None

    @property
    def state(self) -> State:
        return self._state

    def person_detected(self) -> None:
        """Fire when a person is detected while MOVING. No-op otherwise —
        already dealing with someone."""
        if self._state is not State.MOVING:
            logger.info("person_detected ignored — already in %s", self._state.value)
            return

        self._transition(State.PERSON_DETECTED, "person detected")
        self._orient_toward_person()
        self._transition(State.ENGAGING, "oriented toward person, starting conversation")
        self._last_activity = self._clock()

    def _orient_toward_person(self) -> None:
        """Stub: stop movement, turn head servo toward the person. No real
        actuators wired up yet (see docs/D3BOUUR_Project_Handoff.md §6)."""
        logger.info("[stub] stopping movement + turning head servo toward person")

    def visitor_said(self, text: str) -> Optional[ChatResultLike]:
        """Feed one turn of visitor speech (today: typed by a test script;
        eventually: STT output) to the conversation brain. Only valid while
        ENGAGING. Any activity here resets the timeout clock."""
        if self._state is not State.ENGAGING:
            logger.info("visitor_said ignored — not engaging (state=%s)", self._state.value)
            return None

        self._last_activity = self._clock()
        try:
            result = self._brain.chat(text)
        except Exception:
            logger.exception("conversation brain failed on turn %r — continuing demo", text)
            return None

        logger.info("D3BOUUR [%s, %.2fs]: %s", result.provider, result.elapsed, result.text)
        return result

    def conversation_ended(self) -> None:
        """Fire when the conversation reaches a clear close (Natural End).
        Only valid while ENGAGING."""
        if self._state is not State.ENGAGING:
            logger.info("conversation_ended ignored — not engaging (state=%s)", self._state.value)
            return
        self._resume_moving(ExitReason.NATURAL_END)

    def tick(self) -> None:
        """Call periodically (e.g. from a loop or, later, a ROS 2 timer
        callback) to check for timeout. No-op outside ENGAGING."""
        if self._state is not State.ENGAGING or self._last_activity is None:
            return
        elapsed = self._clock() - self._last_activity
        if elapsed >= self._timeout_seconds:
            self._resume_moving(ExitReason.TIMEOUT)

    def _resume_moving(self, reason: ExitReason) -> None:
        self._transition(State.MOVING, f"resume ({reason.value})")
        self._last_activity = None

    def _transition(self, new_state: State, why: str) -> None:
        old_state = self._state
        self._state = new_state
        logger.info("%s -> %s  (%s)", old_state.value, new_state.value, why)
        if self._on_state_change:
            self._on_state_change(old_state, new_state, why)
