"""
ptz.py — ONVIF PTZ control with heartbeat-sustained movement,
          dead-reckoning position tracking, and interactive calibration.

Tested against: V380 Pro PTZ camera (Macro-Video / AliOS firmware).
Should work with any ONVIF-compatible PTZ camera that supports ContinuousMove.

ADAPTING TO A DIFFERENT CAMERA
────────────────────────────────
1. Find the ONVIF port.  It is NOT always 80/8080.  Run:
       nmap -p 1-65535 --open <camera_ip>
   then try connecting on each open port until ONVIFCamera() succeeds.
   Common non-standard ports seen in the wild: 8899, 8080, 5000, 8000.

2. Set IP, PORT, USER, PASS at the bottom of this file (or pass them in).

3. Run calibration once:
       cam = PTZCamera(IP, PORT, USER, PASS)
       cam.connect()
       cam.calibrate()
   Follow the prompts, then copy the reported FULL_PAN_TIME / FULL_TILT_TIME
   into your config.

4. Check direction signs.  Call cam.move_raw(pan=1, tilt=0, duration=1) and
   watch the camera.  If it moved right when you expected left, set
   cam.pan_sign = -1.  Same for tilt: positive ONVIF tilt = UP by spec, but
   some cameras reverse this — set cam.tilt_sign = -1 if up/down are swapped.

FEATURES NOT INCLUDED (investigated but not solved on reference camera)
────────────────────────────────────────────────────────────────────────
- IR / night-vision LED control: IrCutFilter exists via ONVIF but does NOT
  control the physical IR LEDs on the reference camera.  AuxiliaryMove is
  not implemented.  Controlling LEDs requires breaking the proprietary
  port-8089 / port-8800 binary protocol, which needs a Wireshark capture
  of the phone app's traffic and AES key extraction from the APK.
- Speaker / two-way audio: No AudioOutputConfiguration is exposed via ONVIF.
  The speaker is driven by the same proprietary protocol (see above).
"""

import time
import threading
from typing import Optional

from onvif import ONVIFCamera  # pip install onvif-zeep


# ─── Defaults — override in PTZCamera constructor or after calibrate() ─────────

DEFAULT_SPEED             = 0.5   # ONVIF velocity magnitude, range 0.0–1.0
DEFAULT_HEARTBEAT         = 1.0   # seconds between ContinuousMove resends
                                  # camera firmware auto-stops after ~1-2 s
                                  # so keep this comfortably under 1.5 s
DEFAULT_STOP_SETTLE       = 0.3   # seconds to wait after Stop() before the
                                  # next move command — needed because cheap
                                  # firmwares are still processing Stop when
                                  # the next command arrives
DEFAULT_CONNECT_RETRIES   = 3     # connect() attempts before giving up
DEFAULT_CONNECT_RETRY_DELAY = 2.0 # seconds between connect() attempts


class PTZConnectionError(RuntimeError):
    """Camera could not be reached (initial connect, or reconnect after a drop)."""


class PTZCamera:
    """
    Wraps an ONVIF PTZ camera with:
      - heartbeat-sustained ContinuousMove  (camera won't silently stop mid-pan)
      - dead-reckoning position tracking    (0.0 = one extreme, 1.0 = other)
      - interactive calibration helper
      - manual position reset               (for after power cycles / drift)
    """

    def __init__(
        self,
        ip: str,
        port: int,
        user: str,
        password: str,
        speed: float = DEFAULT_SPEED,
        heartbeat_interval: float = DEFAULT_HEARTBEAT,
        stop_settle: float = DEFAULT_STOP_SETTLE,
    ):
        self.ip   = ip
        self.port = port
        self.user = user
        self.password = password

        self.speed             = speed
        self.heartbeat_interval = heartbeat_interval
        self.stop_settle       = stop_settle

        # The speed full_pan_time/full_tilt_time were actually measured at.
        # Defaults to the constructor's speed (the common case: you build the
        # object at your calibration speed). calibrate() updates this to
        # self.speed at the moment it actually measures the times, so it
        # stays correct even if you change self.speed before calibrating.
        # move_to_pan()/move_to_tilt()/home() all scale their move duration
        # by (calibration_speed / current speed) — without this, changing
        # self.speed after calibrating silently makes every fractional move
        # travel the wrong physical distance while dead-reckoning keeps
        # reporting the intended (wrong) position as if it were reached.
        self.calibration_speed = speed

        # Direction signs: set to -1 to flip an axis if the camera moves
        # opposite to what you expect.  Test with move_raw() and adjust.
        self.pan_sign  = 1
        self.tilt_sign = 1

        # Calibration: seconds to traverse the full range at self.speed.
        # Run calibrate() to measure these, or set manually.
        self.full_pan_time:  Optional[float] = None
        self.full_tilt_time: Optional[float] = None

        # Dead-reckoning position, 0.0–1.0 for each axis.
        # None means "uncalibrated / unknown".
        self.pan_pos:  Optional[float] = None
        self.tilt_pos: Optional[float] = None

        # ONVIF service handles, set by connect()
        self._cam:         Optional[ONVIFCamera] = None
        self._ptz          = None
        self._media_token: Optional[str] = None

    # ─── Connection ───────────────────────────────────────────────────────────

    def connect(
        self,
        max_retries: int = DEFAULT_CONNECT_RETRIES,
        retry_delay: float = DEFAULT_CONNECT_RETRY_DELAY,
    ) -> None:
        """
        Connect to the camera's ONVIF service and resolve the media profile token.

        Retries up to `max_retries` times with `retry_delay` seconds between
        attempts before giving up — a momentary WiFi drop shouldn't require the
        caller to handle the exception themselves on the first try.

        Raises PTZConnectionError if the camera is unreachable after all attempts.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            print(f"Connecting to ONVIF at {self.ip}:{self.port} ... (attempt {attempt}/{max_retries})")
            try:
                self._cam   = ONVIFCamera(self.ip, self.port, self.user, self.password)
                media       = self._cam.create_media_service()
                profiles    = media.GetProfiles()
                self._media_token = profiles[0].token
                self._ptz   = self._cam.create_ptz_service()
                print(f"Connected.  Media token: {self._media_token}")
                return
            except Exception as e:
                last_exc = e
                self._cam = None
                self._ptz = None
                print(f"  connect attempt {attempt} failed: {e}")
                if attempt < max_retries:
                    time.sleep(retry_delay)

        raise PTZConnectionError(
            f"Could not connect to camera at {self.ip}:{self.port} after "
            f"{max_retries} attempts"
        ) from last_exc

    def _require_connection(self) -> None:
        if self._ptz is None:
            raise RuntimeError("Not connected — call connect() first.")

    def _call_with_reconnect(self, fn, action: str):
        """
        Run fn(). If it raises, try one reconnect and one retry of fn() before
        giving up. Used to ride out a momentary WiFi drop during a move/stop
        command instead of letting the whole operation die silently.
        """
        try:
            return fn()
        except Exception as e:
            print(f"{action} failed ({e}); attempting to reconnect...")
            try:
                self.connect()
            except PTZConnectionError as reconnect_exc:
                raise PTZConnectionError(
                    f"{action} failed and reconnect failed: {reconnect_exc}"
                ) from e
            print(f"Reconnected — retrying {action}...")
            return fn()

    # ─── Low-level ONVIF calls ────────────────────────────────────────────────

    def _send_move(self, pan: float, tilt: float) -> None:
        """Send one ContinuousMove command.  pan/tilt are signed velocities."""
        self._require_connection()

        def do_send():
            req = self._ptz.create_type("ContinuousMove")
            req.ProfileToken = self._media_token
            req.Velocity = {
                "PanTilt": {"x": pan, "y": tilt},
                "Zoom":    {"x": 0},
            }
            self._ptz.ContinuousMove(req)

        self._call_with_reconnect(do_send, action="ContinuousMove")

    def stop(self) -> None:
        """Send Stop and wait for the camera to settle."""
        self._require_connection()
        self._call_with_reconnect(
            lambda: self._ptz.Stop({"ProfileToken": self._media_token}),
            action="Stop",
        )
        time.sleep(self.stop_settle)

    # ─── Heartbeat-sustained movement ─────────────────────────────────────────

    def move_raw(self, pan: float, tilt: float, duration: float) -> None:
        """
        Move using raw signed ONVIF velocities (pan/tilt each –1.0 to 1.0)
        for `duration` seconds, resending the command every heartbeat_interval
        so the camera firmware's auto-stop timer never fires.

        Applies pan_sign / tilt_sign corrections before sending.

        Does NOT update position tracking — use move() for that.
        """
        self._require_connection()
        signed_pan  = pan  * self.pan_sign
        signed_tilt = tilt * self.tilt_sign
        self._send_move(signed_pan, signed_tilt)
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            time.sleep(min(self.heartbeat_interval, max(remaining, 0)))
            if time.monotonic() < deadline:
                self._send_move(signed_pan, signed_tilt)
        self.stop()

    def move(
        self,
        pan_dir: float,
        tilt_dir: float,
        duration: float,
        speed: Optional[float] = None,
    ) -> None:
        """
        Move in the given directions for `duration` seconds with heartbeat,
        then update the dead-reckoning position.

        pan_dir / tilt_dir: -1, 0, or +1  (direction; sign corrections applied)
        speed:              0.0–1.0 velocity magnitude (defaults to self.speed)

        Position tracking:
          Each axis is tracked as a float 0.0–1.0 where 0.0 = one extreme and
          1.0 = the other.  The mapping of which physical extreme is 0 vs 1 is
          determined by which direction you move during calibration.  Tracking
          is dead-reckoning and drifts — reset with reset_pan() / reset_tilt()
          when the camera is physically at a known extreme.
        """
        spd = speed if speed is not None else self.speed
        pan_vel  = pan_dir  * spd
        tilt_vel = tilt_dir * spd

        self.move_raw(pan_vel, tilt_vel, duration)

        # Update dead-reckoning position
        self._update_position(pan_dir, tilt_dir, spd, duration)

    def _update_position(
        self, pan_dir: float, tilt_dir: float, speed: float, duration: float
    ) -> None:
        # Denominator uses calibration_speed (the speed full_pan_time/
        # full_tilt_time were actually measured at), NOT self.speed — self.speed
        # is whatever the caller currently has set, which may differ (e.g. a
        # sweep deliberately run slower than calibration). Using self.speed
        # here made this silently wrong whenever the two diverged: the move's
        # commanded duration (see duration_for_pan_fraction()) is scaled
        # against calibration_speed, so the position update has to match that
        # same reference or dead-reckoning drifts out of sync with reality.
        if self.full_pan_time and self.pan_pos is not None and pan_dir != 0:
            delta = (pan_dir * speed * duration) / (self.full_pan_time * self.calibration_speed)
            self.pan_pos = max(0.0, min(1.0, self.pan_pos + delta))

        if self.full_tilt_time and self.tilt_pos is not None and tilt_dir != 0:
            delta = (tilt_dir * speed * duration) / (self.full_tilt_time * self.calibration_speed)
            self.tilt_pos = max(0.0, min(1.0, self.tilt_pos + delta))

    # ─── Percentage-based movement ────────────────────────────────────────────

    def duration_for_pan_fraction(self, fraction: float, speed: Optional[float] = None) -> float:
        """
        Seconds needed to traverse `fraction` (0.0-1.0) of the full pan range
        at `speed` (defaults to self.speed). Scaled by
        (calibration_speed / speed) so it stays correct even when speed
        differs from whatever full_pan_time was actually measured at.
        """
        if self.full_pan_time is None:
            raise RuntimeError("Pan not calibrated — run calibrate() first.")
        spd = speed if speed is not None else self.speed
        return abs(fraction) * self.full_pan_time * (self.calibration_speed / spd)

    def duration_for_tilt_fraction(self, fraction: float, speed: Optional[float] = None) -> float:
        """Tilt counterpart to duration_for_pan_fraction()."""
        if self.full_tilt_time is None:
            raise RuntimeError("Tilt not calibrated — run calibrate() first.")
        spd = speed if speed is not None else self.speed
        return abs(fraction) * self.full_tilt_time * (self.calibration_speed / spd)

    def move_to_pan(self, target: float, speed: Optional[float] = None) -> None:
        """
        Move to a pan position expressed as a fraction 0.0–1.0.
        Requires calibration (full_pan_time must be set) and a known current
        position (pan_pos must not be None).
        """
        if self.pan_pos is None:
            raise RuntimeError("Pan position unknown — reset_pan() to set a known origin.")
        spd    = speed if speed is not None else self.speed
        diff   = target - self.pan_pos
        if abs(diff) < 0.005:
            return
        direction = 1 if diff > 0 else -1
        duration  = self.duration_for_pan_fraction(diff, speed=spd)
        self.move(direction, 0, duration, speed=spd)

    def move_to_tilt(self, target: float, speed: Optional[float] = None) -> None:
        """
        Move to a tilt position expressed as a fraction 0.0–1.0.
        Requires calibration and a known current tilt_pos.
        """
        if self.tilt_pos is None:
            raise RuntimeError("Tilt position unknown — reset_tilt() to set a known origin.")
        spd    = speed if speed is not None else self.speed
        diff   = target - self.tilt_pos
        if abs(diff) < 0.005:
            return
        direction = 1 if diff > 0 else -1
        duration  = self.duration_for_tilt_fraction(diff, speed=spd)
        self.move(0, direction, duration, speed=spd)

    # ─── Position reset ───────────────────────────────────────────────────────

    def reset_pan(self, value: float = 0.0) -> None:
        """
        Declare the current physical pan position to be `value` (default 0.0).
        Use this after manually moving the camera to a known extreme, or after
        a power cycle, to resync the dead-reckoning tracker.
        """
        self.pan_pos = value
        print(f"Pan position reset to {value:.2f}")

    def reset_tilt(self, value: float = 0.0) -> None:
        """
        Declare the current physical tilt position to be `value` (default 0.0).
        """
        self.tilt_pos = value
        print(f"Tilt position reset to {value:.2f}")

    def home(
        self,
        pan_target: float = 0.0,
        tilt_target: float = 0.0,
        margin: float = 1.25,
    ) -> None:
        """
        Drive pan AND tilt simultaneously to a real, physically verified
        extreme, then declare that position as the new dead-reckoning
        reference for both axes.

        Unlike reset_pan()/reset_tilt() alone — which only *declare* a
        position and trust the caller to have actually put the camera there
        (a real risk for tilt in particular, since there's rarely a
        convenient way to manually verify it) — this method drives there
        itself. It reuses the same overshoot trick calibrate() depends on:
        commanding a move for longer than the measured full-range traversal
        time guarantees hitting the physical/software limit before time runs
        out, regardless of where the camera started. `margin` adds a safety
        buffer on top of that (heartbeat/network jitter, calibration
        imprecision) — default 1.25 (25% extra).

        pan_target/tilt_target must each be 0.0 or 1.0 — an "extreme" can
        only be reliably reached this way at the actual ends of the range,
        never an intermediate position. Both axes move together using one
        move_raw() call (it already accepts pan+tilt at once), and duration
        is margin * max(full_pan_time, full_tilt_time) — the longer of the
        two, so the slower axis is guaranteed saturated too even if it
        started at its opposite extreme.

        Works even before pan_pos/tilt_pos are known (e.g. right after
        connect()), so this can replace a manual reset_pan(0.0) /
        reset_tilt(<guess>) as the very first call after connect() +
        calibrate() — every later move_to_pan()/move_to_tilt() is then
        computed from a position that was actually verified, not assumed.

        Duration is scaled by (calibration_speed / self.speed), so this is
        safe to call even if self.speed has changed since calibrate() ran —
        unlike move_to_pan()/move_to_tilt(), you don't need to restore the
        calibration speed first.
        """
        if self.full_pan_time is None or self.full_tilt_time is None:
            raise RuntimeError(
                "Camera not calibrated — full_pan_time/full_tilt_time must be "
                "set (see calibrate()) before home() can compute a safe duration."
            )
        if pan_target not in (0.0, 1.0) or tilt_target not in (0.0, 1.0):
            raise ValueError(
                "home() only drives to a real extreme — pan_target/tilt_target "
                "must each be 0.0 or 1.0."
            )

        pan_dir  = -1.0 if pan_target  == 0.0 else 1.0
        tilt_dir = -1.0 if tilt_target == 0.0 else 1.0
        scale    = self.calibration_speed / self.speed
        duration = margin * max(self.full_pan_time, self.full_tilt_time) * scale

        print(
            f"Homing both axes: pan toward {'0%' if pan_dir < 0 else '100%'}, "
            f"tilt toward {'0%' if tilt_dir < 0 else '100%'}, "
            f"for {duration:.1f}s ({margin:.2f}x the longer of "
            f"full_pan_time={self.full_pan_time:.1f}s / full_tilt_time={self.full_tilt_time:.1f}s, "
            f"scaled {scale:.2f}x for speed={self.speed} vs calibration_speed={self.calibration_speed}) "
            "to guarantee both hit their limit..."
        )
        self.move_raw(pan_dir * self.speed, tilt_dir * self.speed, duration)

        self.reset_pan(pan_target)
        self.reset_tilt(tilt_target)
        print("Homed — both axes now at a physically verified reference position.")

    def print_position(self) -> None:
        """Print current tracked position for both axes."""
        pan_s  = f"{self.pan_pos:.1%}"  if self.pan_pos  is not None else "unknown"
        tilt_s = f"{self.tilt_pos:.1%}" if self.tilt_pos is not None else "unknown"
        print(f"Position — pan: {pan_s}   tilt: {tilt_s}")

    # ─── Calibration ──────────────────────────────────────────────────────────

    def calibrate(self) -> None:
        """
        Interactive calibration helper.

        Measures how many seconds it takes to traverse the full pan range and
        the full tilt range at the current self.speed.  Run this once per camera
        and store the results.

        Procedure:
          1. Manually (physically) position the camera at one extreme in each
             axis before starting, OR use the prompts to drive it there first.
          2. For each axis the camera will move continuously while a timer runs.
          3. Press Enter the INSTANT the camera visually reaches the far extreme.
          4. The elapsed time is recorded as the full-range traversal time.

        After calibration, reset_pan(0.0) and reset_tilt(0.0) are called so
        position tracking begins from the calibrated 0% extreme.
        calibration_speed is set to self.speed as it stood during this run —
        move_to_pan()/move_to_tilt()/home() scale their durations against it,
        so self.speed can be changed freely afterward (e.g. a slower sweep)
        without breaking positioning.
        """
        self._require_connection()
        print("\n" + "=" * 60)
        print("  CALIBRATION")
        print("=" * 60)
        print(f"  Speed used for calibration: {self.speed}")
        print("  self.speed can be changed after this — move_to_pan()/move_to_tilt()/")
        print("  home() all scale against the speed measured here (calibration_speed).\n")

        self.full_pan_time  = self._calibrate_axis("PAN",  pan_dir=1,  tilt_dir=0)
        self.full_tilt_time = self._calibrate_axis("TILT", pan_dir=0,  tilt_dir=1)
        self.calibration_speed = self.speed

        self.reset_pan(0.0)
        self.reset_tilt(0.0)

        print("\n" + "=" * 60)
        print("  Calibration complete!")
        print(f"  full_pan_time      = {self.full_pan_time:.3f}")
        print(f"  full_tilt_time     = {self.full_tilt_time:.3f}")
        print(f"  calibration_speed  = {self.calibration_speed}")
        print("  Copy these values into your config or PTZCamera constructor.")
        print("  Position has been set to (0.0, 0.0) — camera is at the")
        print("  extreme it was at when each timing run ended.")
        print("=" * 60 + "\n")

    def _calibrate_axis(self, axis: str, pan_dir: float, tilt_dir: float) -> float:
        """
        Time a single axis traversal interactively.
        Returns the elapsed seconds for the full range.
        """
        print(f"\n── {axis} calibration ──")
        print(f"  Manually move the camera to the {axis} = 0% extreme (one end).")
        input("  Press Enter when it is physically at that extreme... ")

        stop_event = threading.Event()
        pan_vel    = pan_dir  * self.speed * self.pan_sign
        tilt_vel   = tilt_dir * self.speed * self.tilt_sign
        heartbeat_error: list = []   # holds the exception, if the thread hits one it can't recover from

        def heartbeat_loop():
            try:
                self._send_move(pan_vel, tilt_vel)
                while not stop_event.wait(timeout=self.heartbeat_interval):
                    self._send_move(pan_vel, tilt_vel)
            except Exception as e:
                # _send_move already retried a reconnect internally and still failed —
                # nothing more this thread can do. Stash the error and stop looping;
                # the main thread (blocked on input()) reports it once the user returns.
                heartbeat_error.append(e)
                stop_event.set()

        print(f"  Camera is now moving toward the {axis} = 100% extreme.")
        print("  Press Enter the INSTANT it reaches the far end.")
        t_start = time.monotonic()
        hb = threading.Thread(target=heartbeat_loop, daemon=True)
        hb.start()

        input("")           # blocks until user presses Enter
        elapsed = time.monotonic() - t_start

        stop_event.set()    # signal heartbeat thread to exit
        hb.join(timeout=self.heartbeat_interval + 1)

        if heartbeat_error:
            raise PTZConnectionError(
                f"Lost connection to camera during {axis} calibration and could not "
                f"reconnect: {heartbeat_error[0]}"
            ) from heartbeat_error[0]

        self.stop()         # send Stop to camera

        print(f"  {axis} full-range time at speed {self.speed}: {elapsed:.3f} s")
        return elapsed

    # ─── Level-tilt calibration ────────────────────────────────────────────────

    def find_level_tilt(self, from_extreme: float = 0.0) -> float:
        """
        Interactive helper to measure the tilt fraction that gives a level,
        room-height view — NOT assumed to be 0.5. A tilt range has no
        guarantee of being centered on the horizon (e.g. a down-biased
        mount can put the true level view well below the midpoint), so this
        measures it against the real camera the same way calibrate()
        measures full_pan_time/full_tilt_time: by timing a move against your
        own judgement, not assuming a fraction.

        Procedure:
          1. Drives tilt to `from_extreme` (0.0 or 1.0) using the same
             overshoot trick as home(), so timing starts from a real,
             verified position rather than wherever tilt_pos claims to be.
          2. Moves continuously away from that extreme. Watch the live feed
             and press Enter the INSTANT the view looks level — room height,
             not floor or ceiling. If the room's lower half is mostly
             featureless flooring (which confuses panorama stitching), bias
             slightly toward eye-level wall/furniture content instead of
             literal geometric level.
          3. Returns the measured fraction (and leaves the camera positioned
             there, tilt_pos updated) — copy it into your LEVEL_TILT config
             constant so future runs don't need to re-measure it.

        Requires full_tilt_time to be set (calibrate() or set manually).
        """
        if self.full_tilt_time is None:
            raise RuntimeError("Tilt not calibrated — run calibrate() first.")
        if from_extreme not in (0.0, 1.0):
            raise ValueError("from_extreme must be 0.0 or 1.0 — a real, overshoot-reachable extreme.")

        # Tilt-only version of home()'s overshoot trick — drive to a verified
        # extreme without touching pan.
        home_dir = -1.0 if from_extreme == 0.0 else 1.0
        scale    = self.calibration_speed / self.speed
        home_duration = 1.25 * self.full_tilt_time * scale
        print(f"Driving tilt to a verified {from_extreme:.0%} extreme ({home_duration:.1f}s)...")
        self.move_raw(0.0, home_dir * self.speed, home_duration)
        self.reset_tilt(from_extreme)

        sweep_dir = -home_dir   # move away from the extreme just reached
        tilt_vel  = sweep_dir * self.speed * self.tilt_sign
        print(f"\nTilt is at a verified {from_extreme:.0%}. Moving toward the other extreme —")
        print("watch the camera feed and press Enter the INSTANT the view looks level")
        print("(room height, not floor or ceiling; bias toward eye-level detail over")
        print("plain flooring if the two don't quite coincide).")

        stop_event = threading.Event()
        heartbeat_error: list = []

        def heartbeat_loop():
            try:
                self._send_move(0.0, tilt_vel)
                while not stop_event.wait(timeout=self.heartbeat_interval):
                    self._send_move(0.0, tilt_vel)
            except Exception as e:
                heartbeat_error.append(e)
                stop_event.set()

        t_start = time.monotonic()
        hb = threading.Thread(target=heartbeat_loop, daemon=True)
        hb.start()

        input("")   # blocks until Enter
        elapsed = time.monotonic() - t_start

        stop_event.set()
        hb.join(timeout=self.heartbeat_interval + 1)

        if heartbeat_error:
            raise PTZConnectionError(
                f"Lost connection during find_level_tilt(): {heartbeat_error[0]}"
            ) from heartbeat_error[0]

        self.stop()

        # elapsed was measured at self.speed; convert back to a fraction of
        # full_tilt_time via the same calibration_speed scaling used everywhere else.
        fraction_moved = elapsed / (self.full_tilt_time * scale)
        level_tilt = from_extreme + sweep_dir * fraction_moved
        level_tilt = max(0.0, min(1.0, level_tilt))
        self.tilt_pos = level_tilt

        print(f"\nLevel tilt measured at {level_tilt:.3f} ({level_tilt:.0%}).")
        print("Copy this into your LEVEL_TILT config constant.\n")
        return level_tilt
