"""Bridges onvif_camera/engage.py's real engagement detection into
BehaviorStateMachine's `EngagementProvider` interface (state_machine.py).

This is the one file that knows about both sides — `engage.py` has zero
knowledge of this module or of BehaviorStateMachine, and state_machine.py
has zero knowledge of engage.py (see its module docstring). That mirrors
exactly how demo_state_machine.py is the one place that knows about both
BehaviorStateMachine and the real ConversationBrain: the "plug the real
thing in" step is deliberately kept separate from both things it plugs
together, so either side can be tested (or replaced) without the other.

Only import this module where real hardware is actually being wired up
(e.g. a future real-hardware demo/launch script) — importing it pulls in
`engage.py`, which pulls in cv2/mediapipe/onvif-zeep at module level, which
`d3bouur_behavior/__init__.py` deliberately does not do, so plain
`from d3bouur_behavior import BehaviorStateMachine` stays free of that
dependency chain for unit tests.

`onvif_camera/` is plain scripts, not an installed package (see its own
files' `from ptz import PTZCamera`-style flat imports) — the sys.path
insert below is the same "point at that directory" convention
demo_state_machine.py already uses for d3bouur_conversation.
"""

import sys
from pathlib import Path
from typing import Callable, Optional

_ONVIF_CAMERA_DIR = Path(__file__).resolve().parents[2] / "onvif_camera"
sys.path.insert(0, str(_ONVIF_CAMERA_DIR))

from engage import EngagementConfig, FaceDetector, Outcome, run_engagement_attempt  # noqa: E402
from ptz import PTZCamera  # noqa: E402

from .state_machine import Direction, EngagementOutcome  # noqa: E402

# engage.py's Outcome has two "give up" cases with different confidence
# levels (RETURN_NO_FACE vs RETURN_TIMEOUT — see its module docstring); the
# state machine only needs "did it work or not", but keeps both distinct
# (not collapsed into one NOT_ENGAGED) since the log line at each transition
# is more useful with the real reason attached.
_OUTCOME_MAP = {
    Outcome.ENGAGED: EngagementOutcome.ENGAGED,
    Outcome.RETURN_NO_FACE: EngagementOutcome.NO_FACE,
    Outcome.RETURN_TIMEOUT: EngagementOutcome.TIMEOUT,
}


class RealEngagementProvider:
    """Real hardware path: a connect()ed + calibrated `PTZCamera`, the
    camera's RTSP URL, and a distance reading getter (eventually the
    ultrasonic sensor that triggered `person_detected()` — see Direction's
    docstring; a fixed/simulated value works fine for testing) — wired up
    as a `state_machine.EngagementProvider`.

    Construct once, reuse across every `person_detected()` call: it holds
    one `FaceDetector` (loads mediapipe's model once), not a fresh one per
    attempt — same reasoning as PiperTTS/VoskSTT loading their models once.
    """

    def __init__(
        self,
        cam: PTZCamera,
        rtsp_url: str,
        distance_m: Callable[[], float],
        return_pan: float = 0.5,
        return_tilt: Optional[float] = None,
        face_detector: Optional[FaceDetector] = None,
        config: Optional[EngagementConfig] = None,
    ) -> None:
        self._cam = cam
        self._rtsp_url = rtsp_url
        self._distance_m = distance_m
        self._return_pan = return_pan
        self._return_tilt = return_tilt
        self._face_detector = face_detector or FaceDetector()
        self._config = config

    def __call__(self, direction: Optional[Direction]) -> EngagementOutcome:
        """Satisfies EngagementProvider — this is what BehaviorStateMachine
        actually calls from `_orient_toward_person()`."""
        if direction is None:
            raise ValueError(
                "RealEngagementProvider requires a Direction (pan/tilt target) — "
                "person_detected() must be called with one once a real ultrasonic "
                "trigger supplies it."
            )

        result = run_engagement_attempt(
            cam=self._cam,
            rtsp_url=self._rtsp_url,
            pan_target=direction.pan,
            tilt_target=direction.tilt,
            distance_m=self._distance_m,
            return_pan=self._return_pan,
            return_tilt=self._return_tilt,
            face_detector=self._face_detector,
            config=self._config,
        )
        return _OUTCOME_MAP[result.outcome]

    def close(self) -> None:
        """Releases the held FaceDetector's mediapipe resources. Call once
        the provider is no longer needed (e.g. on shutdown) — mirrors
        FaceDetector's own close()/context-manager support."""
        self._face_detector.close()
