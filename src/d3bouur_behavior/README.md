# d3bouur_behavior

The behavior state machine that ties D3BOUUR's core loop together: moving,
noticing a visitor, having a conversation with them, and going back to moving
once it's over.

## Status: **CONFIRMED WORKING**

Verified by actually running `demo_state_machine.py` against a real, locally
running Ollama instance (not a mock), and `demo_engagement.py` +
`test_engagement_provider.py` against the real `onvif_camera/engage.py`
engagement logic (via a real `RealEngagementProvider`, with only the
hardware-dependent `run_engagement_attempt()` call itself mocked out — see
[Testing](#testing) below for exact commands and what each proves.

**What's NOT yet wired, still simulated:**
- There's no real sensor input. "A person was detected" is simulated by a test
  script calling `person_detected(direction)` directly — there is no
  perception node or ultrasonic signal behind it yet, so `direction` (which
  way to look) is also simulated rather than coming from a real ultrasonic
  trigger.
- `_orient_toward_person()` now calls real engagement logic (see below) when
  an `engagement_provider` is configured, but `engage.py`'s own
  `trigger_head_servo()` is still a stub that only logs — no real Arduino
  `S:angle` command is sent. It's already shaped correctly for that: it
  receives the same `pan_target`/`tilt_target` floats `Direction` carries,
  so filling it in later is a self-contained change inside `engage.py`, not
  a reshaping of this interface.
- "The conversation is over" (Natural End) is also simulated by the test
  script calling `conversation_ended()` directly — there's no real NLU/LLM
  end-of-turn detection deciding this on its own yet.
- No real camera or Arduino is connected in this dev environment, so
  `RealEngagementProvider` itself has only been tested with
  `run_engagement_attempt()` mocked out (see `test_engagement_provider.py`)
  — the real face-detection logic inside `engage.py` was already verified
  standalone against the real camera in an earlier session (see
  `onvif_camera`'s own testing), but the two haven't yet been proven
  together end-to-end against real hardware.

In short: the state machine's logic, its connection to the *real*
conversation brain, and now its connection to `engage.py`'s *real*
engagement-decision logic (via a real `RealEngagementProvider`, hardware
mocked) are all proven. Only the last hop — real camera + real Arduino
servo — is not; that's intentionally left for later, once real hardware is
reachable from wherever this code runs (the Pi 5).

## How this fits into the overall robot

```
   MOVING ──person_detected(direction)──> PERSON_DETECTED ──orienting: ENGAGED──> ENGAGING
                                                │                                    │
                                                │ orienting: NO_FACE / TIMEOUT        │
                                                ▼                        ┌────────────┤
                                             MOVING                      │            │
                                                                conversation_ended()  tick(), no activity
                                                                (Natural End)          for timeout_seconds
                                                                          │            │
                                                                          ▼            ▼
                                                                       MOVING  <────  MOVING
                                                                            (Timeout)
```

- **MOVING** — the robot's default state (patrolling/mapping/idle).
- **PERSON_DETECTED** — momentary: the robot stops and orients its head/camera
  toward the visitor, then decides whether they actually want to talk.
  `_orient_toward_person(direction)` calls the configured
  `engagement_provider` (see below) — real hardware, or a stub that's
  always ENGAGED if none is configured (the pre-wiring behavior, still the
  default). Only an `ENGAGED` outcome continues on to ENGAGING; `NO_FACE`
  or `TIMEOUT` resumes MOVING directly, without ever starting a
  conversation.
- **ENGAGING** — the conversation is live. Each turn of visitor speech is fed
  to the real `ConversationBrain` (from `d3bouur_conversation`) via
  `visitor_said(text)`, which returns the brain's reply.
- **Exit paths**, both returning to MOVING:
  - **Natural End** — `conversation_ended()` fires when the conversation
    reaches a clear close.
  - **Timeout** — `tick()`, called periodically, resumes MOVING on its own if
    nothing happened for `timeout_seconds` (default 8s, 6s in the demo).

The module is deliberately **not a ROS 2 node** yet and doesn't import
`d3bouur_conversation` or `onvif_camera` directly:
- It only requires an object with a `.chat(text)` method for the
  conversation side (see `ConversationBrainLike` in `state_machine.py`).
- It only requires a `Callable[[Direction], EngagementOutcome]` for the
  engagement side (see `EngagementProvider`) — `Direction` (a plain
  pan/tilt/label value) and `EngagementOutcome` (this module's own
  ENGAGED/NO_FACE/TIMEOUT vocabulary) are both defined locally, so nothing
  here imports `onvif_camera/engage.py` or its `cv2`/`mediapipe`/
  `onvif-zeep` dependencies.

That means it can be unit-tested with trivial fakes for both — no Ollama,
no camera, no mediapipe required (see `demo_engagement.py`). The real bridge
from `engage.py`'s actual `EngagementResult`/`Outcome` to this module's
`EngagementOutcome` lives in the separate `engagement_provider.py`
(`RealEngagementProvider`) — only code that wires up real hardware needs to
import that file, exactly the same role `demo_state_machine.py` already
plays for the real `ConversationBrain`. Firing an event in a state that
doesn't expect it (e.g. `conversation_ended()` while MOVING) is logged and
ignored, not an error — real sensor/speech events can't be prevented from
arriving at an inconvenient time; the same is true of a failed
`engagement_provider` call, which is treated as a safe `NO_FACE` rather than
crashing the state machine mid-demo.

## Testing

Requires [Ollama](https://ollama.com) running locally (the demo builds a real
`ConversationBrain`, not a stub):

```bash
cd src/d3bouur_behavior
python3 demo_state_machine.py
```

This runs three scenarios and asserts on the resulting state after each:

1. **Natural End** — `person_detected()` → two real `visitor_said()` turns
   against Ollama → `conversation_ended()` → asserts state is back to MOVING.
2. **Timeout** — `person_detected()`, then no activity; `tick()` is called
   once a second until it resumes MOVING on its own once `timeout_seconds`
   elapses.
3. **Ignored event** — calls `conversation_ended()` while still in MOVING and
   asserts it's a no-op, not a crash.

Last real run: all three scenarios passed (`All scenarios passed.`), with
real Ollama replies logged for each `visitor_said()` call — cold-start
latency on the first call was ~44s, ~2.5s on the follow-up, which matters
for live-demo pacing.

### Engagement wiring

```bash
cd src/d3bouur_behavior

# State machine's own branching logic (ENGAGED -> ENGAGING, NO_FACE/TIMEOUT
# -> MOVING, a failed provider treated as safe NO_FACE) — no camera, no
# Ollama, a FakeEngagementProvider standing in for the real thing.
python3 demo_engagement.py

# The real bridge (engagement_provider.RealEngagementProvider) against the
# real engage.py/ptz.py code — only run_engagement_attempt() itself is
# mocked (it needs a live RTSP connection); cv2/mediapipe/onvif-zeep are
# genuinely imported and exercised.
python3 test_engagement_provider.py
```

`demo_engagement.py` runs five scenarios: ENGAGED (starts a real fake-brain
conversation, asserts the right `Direction` was forwarded), RETURN_NO_FACE
and RETURN_TIMEOUT (both resume MOVING immediately, never engaging), a
provider exception (treated as safe NO_FACE, doesn't crash), and omitting
`engagement_provider` entirely (confirms the pre-wiring stub — always
ENGAGED — is unchanged, so `demo_state_machine.py` above still passes as-is).

`test_engagement_provider.py` proves `RealEngagementProvider` correctly maps
every `engage.Outcome` value to the right `EngagementOutcome`, forwards
`Direction`/config to `run_engagement_attempt()` unchanged, raises on a
missing `Direction` rather than misbehaving silently, and plugs into a real
`BehaviorStateMachine` end-to-end.

Last real run: all scenarios/tests passed on both scripts.

**Not yet tested**: either script against an actual connected camera —
`run_engagement_attempt()` is mocked in both because there's no real camera
or Arduino reachable from this dev machine (see Status above).

No colcon build is needed to run any of these demos/tests (same convention
as `d3bouur_conversation`'s `demo_chat.py`) — they import the package
directly via a `sys.path` insert. `colcon build` is only needed once this is
wrapped into a real ROS 2 node.
