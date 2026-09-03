"""D3BOUUR's core behavior state machine.

States (see docs/D3BOUUR_Project_Handoff.md §6 for the original design):

    MOVING ----person_detected()----> PERSON_DETECTED --orienting: ENGAGED--> ENGAGING
                                       PERSON_DETECTED --orienting: NO_FACE/TIMEOUT--> MOVING
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
  with real duration once actuators exist. With no engagement_provider
  configured, `_orient_toward_person()` is still a stub and the state
  passes through in the same call as `person_detected()`; with one
  configured, it blocks for the real orientation attempt (turn camera,
  watch for a face) and PERSON_DETECTED naturally takes wall-clock time,
  without the state machine itself changing. It's also no longer guaranteed
  to lead to ENGAGING — see the state diagram above.

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

* **Same decoupling for `_orient_toward_person()`, now that it does
  something real.** `onvif_camera/engage.py`'s `run_engagement_attempt()`
  needs a connect()ed, calibrated `PTZCamera`, an RTSP URL, and (via
  mediapipe) a face-detection model — none of that belongs in a module
  whose whole point is being testable without hardware. So this file
  defines only `Direction` (a plain pan/tilt/label value, zero dependency
  on `onvif_camera`), `EngagementOutcome` (this module's own three-value
  vocabulary — ENGAGED / NO_FACE / TIMEOUT — deliberately not
  `engage.Outcome`, so nothing here imports `engage.py`), and
  `EngagementProvider` (a `Callable[[Direction], EngagementOutcome]`
  Protocol-style type alias, exactly parallel to `ConversationBrainLike`).
  `engage.py` itself is never imported here and has no idea this state
  machine exists. The actual bridge — translating `engage.py`'s real
  `EngagementResult` into an `EngagementOutcome`, and owning the real
  `PTZCamera`/RTSP/`FaceDetector` — lives in the separate
  `engagement_provider.py`, which only the code that wires up real hardware
  needs to import (same role `demo_state_machine.py` already plays for
  `ConversationBrain`). With no provider configured, `_orient_toward_person()`
  falls back to the old stub behavior (always ENGAGED) — so existing tests
  and the existing demo scenarios are unaffected by this change.
"""

import logging
import time
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Direction:
    """Where to turn to look at the person who tripped detection.

    Eventually supplied by which ultrasonic sensor fired (see the sensor
    pin table in docs/D3BOUUR_Project_Handoff.md §13) — simulated by
    test/demo code for now, same as `person_detected()` itself being
    simulated by a direct call rather than a real perception signal.

    `pan`/`tilt` are plain floats in PTZCamera's own 0.0-1.0 dead-reckoning
    fraction space (see onvif_camera/ptz.py) — kept here as bare floats,
    not a PTZCamera type, so this module still has zero dependency on
    onvif_camera/cv2/mediapipe. `label` is optional and only for logging
    (e.g. "front", "left" — which sensor this came from).
    """

    pan: float
    tilt: float
    label: str = ""

    def __str__(self) -> str:
        return f"{self.label or 'unlabeled'}(pan={self.pan:.2f}, tilt={self.tilt:.2f})"


class EngagementOutcome(Enum):
    """This module's own vocabulary for how an orientation attempt ended —
    deliberately distinct from engage.py's `Outcome` enum (ENGAGED /
    RETURN_NO_FACE / RETURN_TIMEOUT) so nothing here needs to import
    engage.py to know its type. See engagement_provider.py for the
    translation between the two."""

    ENGAGED = "engaged"
    NO_FACE = "no_face"
    TIMEOUT = "timeout"


# A callable taking the Direction to look in and returning how it went.
# Exactly parallel to ConversationBrainLike: the state machine only needs
# something matching this shape, never a concrete engage.py import. Pass a
# real EngagementProvider (engagement_provider.RealEngagementProvider) for
# actual hardware, or a trivial fake for tests — same pattern as
# `conversation_brain`.
EngagementProvider = Callable[[Optional[Direction]], EngagementOutcome]

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
        engagement_provider: Optional[EngagementProvider] = None,
        timeout_seconds: float = 8.0,
        clock: Callable[[], float] = time.monotonic,
        on_state_change: Optional[OnStateChange] = None,
    ) -> None:
        self._brain = conversation_brain
        # Optional by design, like knowledge_base was for ConversationBrain:
        # without one, _orient_toward_person() falls back to the old stub
        # (always ENGAGED) — existing tests/demos that don't pass one keep
        # their exact prior behavior. With one, PERSON_DETECTED really can
        # end without a conversation (RETURN_NO_FACE / RETURN_TIMEOUT).
        self._engagement_provider = engagement_provider
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._on_state_change = on_state_change
        self._state = State.MOVING
        self._last_activity: Optional[float] = None

    @property
    def state(self) -> State:
        return self._state

    def person_detected(self, direction: Optional[Direction] = None) -> None:
        """Fire when a person is detected while MOVING. No-op otherwise —
        already dealing with someone.

        `direction` is where to look (see Direction) — simulated by the
        caller for now, same as this event itself being simulated. Only
        transitions on to ENGAGING if orienting actually finds someone who
        wants to talk (EngagementOutcome.ENGAGED); otherwise it resumes
        MOVING directly, without ever starting a conversation."""
        if self._state is not State.MOVING:
            logger.info("person_detected ignored — already in %s", self._state.value)
            return

        self._transition(State.PERSON_DETECTED, "person detected")
        outcome = self._orient_toward_person(direction)

        if outcome is EngagementOutcome.ENGAGED:
            self._transition(State.ENGAGING, "oriented toward person, starting conversation")
            self._last_activity = self._clock()
        else:
            self._transition(State.MOVING, f"resume (orientation: {outcome.value})")

    def _orient_toward_person(self, direction: Optional[Direction]) -> EngagementOutcome:
        """Stop movement, turn head servo/camera toward the person, and
        decide whether they actually want to engage. Delegates to
        `self._engagement_provider` if one is configured (see
        engagement_provider.RealEngagementProvider for the real hardware
        path); falls back to the old always-ENGAGED stub otherwise. A
        provider failure (camera/detector trouble) is treated as NO_FACE
        rather than crashing the state machine — same "must not crash
        mid-demo" reasoning as visitor_said()'s broad except."""
        if self._engagement_provider is None:
            logger.info(
                "[stub] no engagement_provider configured — stopping movement + "
                "turning head servo toward person (direction=%s)",
                direction,
            )
            return EngagementOutcome.ENGAGED

        logger.info("Orienting toward person (direction=%s) via engagement_provider", direction)
        try:
            outcome = self._engagement_provider(direction)
        except Exception:
            logger.exception("engagement_provider failed — treating as NO_FACE, staying safe")
            return EngagementOutcome.NO_FACE

        logger.info("Engagement attempt outcome: %s", outcome.value)
        return outcome

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
