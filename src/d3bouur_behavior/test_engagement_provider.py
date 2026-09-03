#!/usr/bin/env python3
"""Tests engagement_provider.RealEngagementProvider — the bridge between
engage.py's real Outcome/EngagementResult and state_machine's EngagementOutcome
— without a real camera.

demo_engagement.py proves the *state machine's* branching logic using a
FakeEngagementProvider standing in entirely for this file's real class. This
script instead proves the real bridge's own translation and argument
forwarding: engage.py's `run_engagement_attempt()` is mocked out (it needs a
live RTSP connection, which doesn't exist here) but everything else —
importing the real engage.py/ptz.py, constructing a real PTZCamera object,
running RealEngagementProvider.__call__ end-to-end through its real code —
is exercised for real. cv2, mediapipe, and onvif-zeep are genuinely
installed in this dev environment, so this only mocks the one thing that
actually requires hardware.

Run from this directory:

    python3 test_engagement_provider.py
"""

import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent / "onvif_camera"))

from d3bouur_behavior.engagement_provider import RealEngagementProvider  # noqa: E402
from d3bouur_behavior.state_machine import Direction, EngagementOutcome  # noqa: E402
from engage import EngagementResult, Outcome  # noqa: E402
from ptz import PTZCamera  # noqa: E402

FRONT = Direction(pan=0.5, tilt=0.6, label="front")


def make_provider() -> RealEngagementProvider:
    # PTZCamera's constructor does no network I/O (only connect() does), so
    # this is safe without a real camera — run_engagement_attempt is mocked
    # below anyway, so `cam` is never actually used to move anything.
    cam = PTZCamera(ip="0.0.0.0", port=8899, user="u", password="p")
    cam.full_pan_time = 5.0
    cam.full_tilt_time = 3.0
    cam.pan_pos = 0.5
    cam.tilt_pos = 0.5
    # A sentinel, not a real FaceDetector — avoids loading mediapipe's model
    # for a test where run_engagement_attempt is mocked and never actually
    # calls face_present() on it. RealEngagementProvider only needs to
    # forward this object unchanged; identity-checked in test_forwards_args.
    face_detector = object()
    return RealEngagementProvider(
        cam=cam,
        rtsp_url="rtsp://user:pass@192.0.2.1:554/live/ch00_0",
        distance_m=lambda: 1.5,
        face_detector=face_detector,
    ), cam, face_detector


def test_outcome_mapping() -> None:
    print("=== Outcome mapping: engage.Outcome -> state_machine.EngagementOutcome ===")
    cases = [
        (Outcome.ENGAGED, EngagementOutcome.ENGAGED),
        (Outcome.RETURN_NO_FACE, EngagementOutcome.NO_FACE),
        (Outcome.RETURN_TIMEOUT, EngagementOutcome.TIMEOUT),
    ]
    for real_outcome, expected in cases:
        provider, _, _ = make_provider()
        fake_result = EngagementResult(
            outcome=real_outcome, elapsed_s=1.0, best_streak_s=0.5, distance_m=1.5, reason="test"
        )
        with patch("d3bouur_behavior.engagement_provider.run_engagement_attempt", return_value=fake_result) as mock_run:
            got = provider(FRONT)
        assert got is expected, f"{real_outcome} should map to {expected}, got {got}"
        assert mock_run.call_count == 1
        print(f"  {real_outcome.name} -> {got.value}  OK")
    print("test_outcome_mapping PASSED\n")


def test_forwards_args() -> None:
    print("=== Direction and config correctly forwarded to run_engagement_attempt ===")
    provider, cam, face_detector = make_provider()
    fake_result = EngagementResult(
        outcome=Outcome.ENGAGED, elapsed_s=2.0, best_streak_s=2.5, distance_m=1.4, reason="test"
    )
    with patch("d3bouur_behavior.engagement_provider.run_engagement_attempt", return_value=fake_result) as mock_run:
        provider(FRONT)

    _, kwargs = mock_run.call_args
    assert kwargs["cam"] is cam
    assert kwargs["rtsp_url"] == "rtsp://user:pass@192.0.2.1:554/live/ch00_0"
    assert kwargs["pan_target"] == FRONT.pan
    assert kwargs["tilt_target"] == FRONT.tilt
    assert kwargs["face_detector"] is face_detector
    assert kwargs["distance_m"]() == 1.5
    print("test_forwards_args PASSED\n")


def test_none_direction_raises() -> None:
    print("=== direction=None raises, rather than silently misbehaving ===")
    provider, _, _ = make_provider()
    try:
        provider(None)
    except ValueError as exc:
        print(f"  raised ValueError as expected: {exc}")
        print("test_none_direction_raises PASSED\n")
        return
    raise AssertionError("expected ValueError for direction=None")


def test_satisfies_engagement_provider_protocol() -> None:
    print("=== RealEngagementProvider is usable as a BehaviorStateMachine EngagementProvider ===")
    from d3bouur_behavior import BehaviorStateMachine, State

    class FakeBrain:
        def chat(self, message: str):
            class R:
                text = "ok"
                provider = "fake"
                elapsed = 0.0

            return R()

    provider, _, _ = make_provider()
    fake_result = EngagementResult(
        outcome=Outcome.ENGAGED, elapsed_s=1.0, best_streak_s=3.0, distance_m=1.5, reason="test"
    )
    sm = BehaviorStateMachine(conversation_brain=FakeBrain(), engagement_provider=provider, timeout_seconds=5.0)
    with patch("d3bouur_behavior.engagement_provider.run_engagement_attempt", return_value=fake_result):
        sm.person_detected(FRONT)
    assert sm.state is State.ENGAGING, f"expected ENGAGING via real RealEngagementProvider, got {sm.state}"
    print("test_satisfies_engagement_provider_protocol PASSED\n")


def main() -> None:
    test_outcome_mapping()
    test_forwards_args()
    test_none_direction_raises()
    test_satisfies_engagement_provider_protocol()
    print("All engagement_provider tests passed.")


if __name__ == "__main__":
    main()
