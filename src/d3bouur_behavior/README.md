# d3bouur_behavior

The behavior state machine that ties D3BOUUR's core loop together: moving,
noticing a visitor, having a conversation with them, and going back to moving
once it's over.

## Status: **CONFIRMED WORKING**

Verified by actually running `demo_state_machine.py` against a real, locally
running Ollama instance (not a mock) — see [Testing](#testing) below for the
exact command and what it proves.

**What's NOT yet wired, still simulated:**
- There's no real sensor input. "A person was detected" is simulated by a test
  script calling `person_detected()` directly — there is no perception node,
  camera trigger, or ultrasonic signal behind it yet.
- `_orient_toward_person()` (stop moving, turn the head servo) is a stub that
  only logs — no real Arduino `S:angle` command is sent.
- "The conversation is over" (Natural End) is also simulated by the test
  script calling `conversation_ended()` directly — there's no real NLU/LLM
  end-of-turn detection deciding this on its own yet.

In short: the state machine's logic and its connection to the *real*
conversation brain are proven. Its connection to real hardware and real
perception is not — that wiring is intentionally left for later, once
`onvif_camera`'s `engage.py` (face-presence detection) and real ultrasonic
input exist as ROS 2 topics.

## How this fits into the overall robot

```
   MOVING ──person_detected()──> PERSON_DETECTED ──(auto)──> ENGAGING
                                                                 │
                        ┌────────────────────────────────────────┤
                        │                                        │
              conversation_ended()                          tick(), no activity
              (Natural End)                                  for timeout_seconds
                        │                                        │
                        ▼                                        ▼
                     MOVING  <───────────────────────────────  MOVING
                                  (Timeout)
```

- **MOVING** — the robot's default state (patrolling/mapping/idle).
- **PERSON_DETECTED** — momentary: the robot stops and orients its head/camera
  toward the visitor before starting to talk. Real physical actions (stop
  moving, turn servo) belong here once they exist — today `_orient_toward_person()`
  is a stub, so this state is passed through immediately.
- **ENGAGING** — the conversation is live. Each turn of visitor speech is fed
  to the real `ConversationBrain` (from `d3bouur_conversation`) via
  `visitor_said(text)`, which returns the brain's reply.
- **Exit paths**, both returning to MOVING:
  - **Natural End** — `conversation_ended()` fires when the conversation
    reaches a clear close.
  - **Timeout** — `tick()`, called periodically, resumes MOVING on its own if
    nothing happened for `timeout_seconds` (default 8s, 6s in the demo).

The module is deliberately **not a ROS 2 node** yet and doesn't import
`d3bouur_conversation` directly — it only requires an object with a
`.chat(text)` method (see `ConversationBrainLike` in `state_machine.py`), so
it can be unit-tested with a trivial fake brain, no Ollama required. Only the
demo script chooses to plug in the real brain. Firing an event in a state
that doesn't expect it (e.g. `conversation_ended()` while MOVING) is logged
and ignored, not an error — real sensor/speech events can't be prevented from
arriving at an inconvenient time.

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

No colcon build is needed to run the demo (same convention as
`d3bouur_conversation`'s `demo_chat.py`) — it imports the package directly
via a `sys.path` insert. `colcon build` is only needed once this is wrapped
into a real ROS 2 node.
