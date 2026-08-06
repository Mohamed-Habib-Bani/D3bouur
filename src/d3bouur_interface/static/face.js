/**
 * D3BOUUR's animated face — RoboEyes-style: simple geometric eyes + mouth
 * on a canvas, not a realistic face. Design principles carried through
 * every piece of this:
 *
 * 1. Everything animates toward a TARGET, never snaps to it. Each frame,
 *    current values lerp a fraction of the way toward their target
 *    (framerate-independent: `1 - exp(-speed * dt)`, not a fixed-per-frame
 *    step, so it looks the same at 30fps or 144fps). This one mechanism is
 *    what makes mood changes, look-around glances, and blinks all feel like
 *    fluid motion instead of a slideshow.
 * 2. Idle personality (blink / glance / wink / curious-widen / breathing)
 *    runs on its own randomized timers, entirely independent of whatever
 *    mood or speaking state is active — this is what makes the face read
 *    as "alive" even when nobody's talking to it.
 * 3. Color is not decoration — it's driven by `robotState`, using the same
 *    three string values as d3bouur_behavior's BehaviorStateMachine.State
 *    enum (moving_mapping / person_detected / engaging), so the mapping
 *    from "what the robot is actually doing" to "what color the face is"
 *    is a lookup table, not a guess. "Speaking" isn't a 4th manually-set
 *    state — it's derived from isSpeaking while engaging, because in the
 *    real system D3BOUUR can only talk while it's in that state. The
 *    background crossfades through the *same* per-state colors (just
 *    lightened — see BACKGROUND_LIGHTEN_AMOUNT), not a separate palette,
 *    so the whole screen shifts mood together, not just the eyes/mouth.
 *
 * Mouth animation is amplitude-only (see startSpeaking) — deliberately not
 * a phoneme/viseme system, per the brief.
 */

const MOODS = {
    neutral: { eyeWidthMul: 1, eyeHeightMul: 1, asymmetry: 0, gazeXBias: 0, gazeYBias: 0 },
    happy: { eyeWidthMul: 1, eyeHeightMul: 0.55, asymmetry: 0, gazeXBias: 0, gazeYBias: -0.05, arc: true },
    curious: { eyeWidthMul: 1.12, eyeHeightMul: 1.12, asymmetry: 0.18, gazeXBias: 0, gazeYBias: -0.08 },
    thinking: { eyeWidthMul: 0.92, eyeHeightMul: 0.85, asymmetry: 0, gazeXBias: 0.18, gazeYBias: -0.12 },
};

// Keyed by the same strings as BehaviorStateMachine.State.value in
// d3bouur_behavior/state_machine.py — deliberately not independent names.
const ROBOT_STATES = {
    moving_mapping: { color: '#5b9bff', label: 'idle / moving' },   // calm blue
    person_detected: { color: '#ffb648', label: 'person detected' }, // alert amber
    engaging: { color: '#4fe0b0', label: 'engaging / listening' },  // attentive teal-green
};
const SPEAKING_COLOR = '#ff6f9c'; // warm, energetic — overrides engaging's color while isSpeaking

const BREATH_PERIOD_S = 4.2;   // slow, calm — one full cycle
const BREATH_AMPLITUDE = 0.035; // ±3.5% size, subtle on purpose

// Head-turn reaction: eyes shift the same way an idle glance does (reuses
// GAZE_SPEED in _update — a head turn's eye redirection should read as the
// same kind of motion as a glance, not a different one), but the whole-
// face tilt gets its own duration-paced speed (see headTurn()) since real
// servo turns don't have a fixed speed the way idle glances do.
const HEAD_TURN_GAZE = {
    left: { x: -0.75, y: 0.05 },
    center: { x: 0, y: 0 },
    right: { x: 0.75, y: 0.05 },
};
const HEAD_TURN_TILT_RAD = {
    left: -0.35,  // ~-20° — was ~-5°, too subtle to read as a reaction at a glance
    center: 0,
    right: 0.35,  // ~+20°
};

// Background mirrors the same per-state color used for the eyes/mouth,
// just lightened — same hue, same lookup, different lightness so the eyes
// still stand out against their own state's color instead of disappearing
// into it.
const BACKGROUND_LIGHTEN_AMOUNT = 0.72;

function lerpTo(current, target, dt, speed) {
    const t = 1 - Math.exp(-speed * dt);
    return current + (target - current) * t;
}

function hexToRgb(hex) {
    const int = parseInt(hex.slice(1), 16);
    return { r: (int >> 16) & 255, g: (int >> 8) & 255, b: int & 255 };
}

function rgbToCss({ r, g, b }) {
    return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

function lightenRgb({ r, g, b }, amount) {
    return {
        r: r + (255 - r) * amount,
        g: g + (255 - g) * amount,
        b: b + (255 - b) * amount,
    };
}

export class Face {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');

        this.mood = 'neutral';
        this.robotState = 'moving_mapping';
        this._currentColor = hexToRgb(ROBOT_STATES.moving_mapping.color);
        this.color = ROBOT_STATES.moving_mapping.color; // recomputed every frame in _update()
        this._currentBgColor = lightenRgb(this._currentColor, BACKGROUND_LIGHTEN_AMOUNT);
        this.bgColor = rgbToCss(this._currentBgColor); // background follows the same state color, lightened

        this.state = { eyeWidthMul: 1, eyeHeightMul: 1, asymmetry: 0, gazeX: 0, gazeY: 0, openness: 1, mouthAmplitude: 0 };
        this.target = { eyeWidthMul: 1, eyeHeightMul: 1, asymmetry: 0, gazeX: 0, gazeY: 0, openness: 1, mouthAmplitude: 0 };
        this._glanceOffset = { x: 0, y: 0 };
        this._curiousBoost = 1; // temporary eye-widen multiplier, applied at render time (see _curiousMoment)

        this._headTurnDirection = 'center';
        this._headTurnGazeOffset = { x: 0, y: 0 }; // composed into target.gazeX/Y in _update
        this.tilt = 0;        // current rendered tilt, radians — lerps toward _tiltTarget
        this._tiltTarget = 0;
        this._tiltSpeed = 6;  // overridden per headTurn() call based on duration

        this._winkEye = null; // 'left' | 'right' | null — overrides one eye's openness
        this._winkOpenness = 1;

        this.isSpeaking = false;
        this.analyser = null;
        this._analyserBuffer = null;

        this._resize();
        window.addEventListener('resize', () => this._resize());

        this._scheduleBlink();
        this._scheduleGlance();
        this._scheduleWink();
        this._scheduleCuriousMoment();

        this._lastTime = performance.now();
        requestAnimationFrame((t) => this._tick(t));
    }

    setMood(mood) {
        if (MOODS[mood]) this.mood = mood;
    }

    /** state: 'moving_mapping' | 'person_detected' | 'engaging' — same
     * strings as BehaviorStateMachine.State.value. */
    setRobotState(state) {
        if (ROBOT_STATES[state]) this.robotState = state;
    }

    /**
     * Reacts to the physical head servo turning: eyes shift toward
     * `direction`, and the whole face tilts the same way, layered on top
     * of (not replacing) breathing/idle motion — see the ctx.save/rotate
     * block in _render(). Holds at that position until called again,
     * including with 'center' to return — a continuous-rotation servo has
     * no rest position of its own, so this doesn't invent one either.
     *
     * direction: 'left' | 'center' | 'right'
     * durationMs: rough estimate of how long the physical turn takes —
     * the servo is continuous-rotation with no position feedback (see
     * docs/D3BOUUR_Project_Handoff.md §13), so timing substitutes for a
     * precise angle on the real hardware too; this just paces the tilt
     * animation to roughly match instead of snapping instantly.
     *
     * Wiring point for real hardware: call this from wherever the Arduino
     * serial bridge's servo command (S:angle) gets received and decoded
     * into a direction — nothing else in this class needs to change, only
     * the caller (see kiosk.js's debug button for the trigger it replaces).
     */
    headTurn(direction, durationMs = 900) {
        if (!(direction in HEAD_TURN_GAZE)) return;
        this._headTurnDirection = direction;
        this._headTurnGazeOffset = HEAD_TURN_GAZE[direction];
        this._tiltTarget = HEAD_TURN_TILT_RAD[direction];
        const seconds = Math.max(0.15, durationMs / 1000);
        this._tiltSpeed = 3 / seconds; // ~95% of the way there by durationMs
    }

    /** analyserNode: a Web Audio AnalyserNode already connected to the
     * playing audio — read each frame to drive mouth amplitude. Also
     * forces robotState to 'engaging': in the real system, speaking only
     * happens while engaged, so this face can't be "speaking" from idle. */
    startSpeaking(analyserNode) {
        this.robotState = 'engaging';
        this.analyser = analyserNode;
        this._analyserBuffer = new Uint8Array(analyserNode.fftSize);
        this.isSpeaking = true;
    }

    stopSpeaking() {
        // Stays 'engaging' (still listening) — only the speaking color
        // override and mouth motion turn off, matching how the real
        // conversation stays in ENGAGING between a reply and the next turn.
        this.isSpeaking = false;
        this.analyser = null;
        this.target.mouthAmplitude = 0;
    }

    _resize() {
        const dpr = window.devicePixelRatio || 1;
        const rect = this.canvas.getBoundingClientRect();
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.width = rect.width;
        this.height = rect.height;
    }

    // --- Idle personality timers -----------------------------------------

    _scheduleBlink() {
        const delay = 2200 + Math.random() * 3800;
        setTimeout(() => { this._blink(); this._scheduleBlink(); }, delay);
    }

    _blink() {
        // rest=1 (open) -> extreme=0 (closed) -> back to 1. The squash-and-
        // stretch widen lives in _drawEye, driven directly off openness —
        // no separate state needed for it.
        this._pulse((v) => { this.target.openness = v; }, 300, 1, 0);
    }

    _scheduleGlance() {
        const delay = 3000 + Math.random() * 5000;
        setTimeout(() => {
            this._glanceOffset = { x: (Math.random() - 0.5) * 0.6, y: (Math.random() - 0.5) * 0.4 };
            setTimeout(() => { this._glanceOffset = { x: 0, y: 0 }; }, 700 + Math.random() * 600);
            this._scheduleGlance();
        }, delay);
    }

    _scheduleWink() {
        const delay = 14000 + Math.random() * 18000;
        setTimeout(() => { this._wink(); this._scheduleWink(); }, delay);
    }

    _wink() {
        this._winkEye = Math.random() < 0.5 ? 'left' : 'right';
        this._pulse((v) => { this._winkOpenness = v; }, 320, 1, 0, () => { this._winkEye = null; });
    }

    /** Bigger, rarer than a glance — eyes briefly widen (not just look
     * around), a distinct "oh?" moment rather than routine idle motion. */
    _scheduleCuriousMoment() {
        const delay = 25000 + Math.random() * 20000; // 25-45s
        setTimeout(() => { this._pulse((v) => { this._curiousBoost = v; }, 900, 1, 1.35); this._scheduleCuriousMoment(); }, delay);
    }

    /** Triangle-wave pulse from `restValue` to `extremeValue` and back
     * over `duration` ms. Shared by blink, wink, and the curious-widen
     * moment — same shape of motion, different range and target. */
    _pulse(setter, duration, restValue, extremeValue, onDone) {
        const start = performance.now();
        const animate = (now) => {
            const t = Math.min(1, (now - start) / duration);
            const amount = t < 0.5 ? t / 0.5 : (1 - t) / 0.5;
            setter(restValue + (extremeValue - restValue) * amount);
            if (t < 1) requestAnimationFrame(animate);
            else { setter(restValue); if (onDone) onDone(); }
        };
        requestAnimationFrame(animate);
    }

    // --- Animation loop -----------------------------------------------

    _tick(now) {
        const dt = Math.min(0.1, (now - this._lastTime) / 1000);
        this._lastTime = now;
        this._update(dt);
        this._render(now);
        requestAnimationFrame((t) => this._tick(t));
    }

    _update(dt) {
        const moodParams = MOODS[this.mood];
        this.target.eyeWidthMul = moodParams.eyeWidthMul;
        this.target.eyeHeightMul = moodParams.eyeHeightMul;
        this.target.asymmetry = moodParams.asymmetry;
        // Head-turn gaze composes with mood bias and idle glances — a
        // deliberate look direction (servo turning) plus small random
        // jitter (idle glance) on top of it, same as glances already
        // compose with mood bias.
        this.target.gazeX = moodParams.gazeXBias + this._glanceOffset.x + this._headTurnGazeOffset.x;
        this.target.gazeY = moodParams.gazeYBias + this._glanceOffset.y + this._headTurnGazeOffset.y;

        const SHAPE_SPEED = 6;   // mood transitions
        const GAZE_SPEED = 5;    // look-around (glances and head-turn eye redirection both use this)
        const BLINK_SPEED = 30;  // track the blink/wink pulse closely
        const MOUTH_SPEED = 14;  // amplitude smoothing
        const COLOR_SPEED = 4;   // state color transitions — deliberately slower/calmer than shape changes

        this.state.eyeWidthMul = lerpTo(this.state.eyeWidthMul, this.target.eyeWidthMul, dt, SHAPE_SPEED);
        this.state.eyeHeightMul = lerpTo(this.state.eyeHeightMul, this.target.eyeHeightMul, dt, SHAPE_SPEED);
        this.state.asymmetry = lerpTo(this.state.asymmetry, this.target.asymmetry, dt, SHAPE_SPEED);
        this.state.gazeX = lerpTo(this.state.gazeX, this.target.gazeX, dt, GAZE_SPEED);
        this.state.gazeY = lerpTo(this.state.gazeY, this.target.gazeY, dt, GAZE_SPEED);
        this.state.openness = lerpTo(this.state.openness, this.target.openness, dt, BLINK_SPEED);
        // Tilt uses its own duration-paced speed (set in headTurn()), not
        // the fixed GAZE_SPEED — a servo turn's pacing is a real input,
        // not a constant, unlike a glance's fixed-feeling look-around speed.
        this.tilt = lerpTo(this.tilt, this._tiltTarget, dt, this._tiltSpeed);

        if (this.isSpeaking && this.analyser) {
            this.analyser.getByteTimeDomainData(this._analyserBuffer);
            let sumSquares = 0;
            for (let i = 0; i < this._analyserBuffer.length; i++) {
                const v = (this._analyserBuffer[i] - 128) / 128;
                sumSquares += v * v;
            }
            const rms = Math.sqrt(sumSquares / this._analyserBuffer.length);
            this.target.mouthAmplitude = Math.min(1, rms * 4.5); // gain tuned by ear against Piper's output level
        }
        this.state.mouthAmplitude = lerpTo(this.state.mouthAmplitude, this.target.mouthAmplitude, dt, MOUTH_SPEED);

        const speaking = this.robotState === 'engaging' && this.isSpeaking;
        const targetRgb = hexToRgb(speaking ? SPEAKING_COLOR : ROBOT_STATES[this.robotState].color);
        this._currentColor = {
            r: lerpTo(this._currentColor.r, targetRgb.r, dt, COLOR_SPEED),
            g: lerpTo(this._currentColor.g, targetRgb.g, dt, COLOR_SPEED),
            b: lerpTo(this._currentColor.b, targetRgb.b, dt, COLOR_SPEED),
        };
        this.color = rgbToCss(this._currentColor);

        // Background chases a lightened version of the same target color,
        // at the same COLOR_SPEED — foreground and background crossfade
        // together, not one lagging the other.
        const targetBgRgb = lightenRgb(targetRgb, BACKGROUND_LIGHTEN_AMOUNT);
        this._currentBgColor = {
            r: lerpTo(this._currentBgColor.r, targetBgRgb.r, dt, COLOR_SPEED),
            g: lerpTo(this._currentBgColor.g, targetBgRgb.g, dt, COLOR_SPEED),
            b: lerpTo(this._currentBgColor.b, targetBgRgb.b, dt, COLOR_SPEED),
        };
        this.bgColor = rgbToCss(this._currentBgColor);
    }

    // --- Rendering -------------------------------------------------------

    _render(now) {
        const ctx = this.ctx;
        const w = this.width, h = this.height;

        ctx.fillStyle = this.bgColor;
        ctx.fillRect(0, 0, w, h);

        // Breathing: continuous, independent of every other animation —
        // never fully still, even mid-mood-transition or mid-blink.
        const breath = 1 + Math.sin((now * 0.001 * 2 * Math.PI) / BREATH_PERIOD_S) * BREATH_AMPLITUDE;

        const centerX = w / 2;
        const centerY = h / 2 - h * 0.05;
        const baseEyeSize = Math.min(w, h) * 0.22 * breath;
        const eyeSpacing = baseEyeSize * 1.7;

        const gazeOffsetX = this.state.gazeX * baseEyeSize * 0.35;
        const gazeOffsetY = this.state.gazeY * baseEyeSize * 0.35;

        const leftMul = (1 - this.state.asymmetry * 0.5) * this._curiousBoost;
        const rightMul = (1 + this.state.asymmetry * 0.5) * this._curiousBoost;

        const leftOpenness = this._winkEye === 'left' ? this._winkOpenness : this.state.openness;
        const rightOpenness = this._winkEye === 'right' ? this._winkOpenness : this.state.openness;

        // Eyes glow brighter in sync with voice amplitude while speaking —
        // reuses the same amplitude value driving the mouth, no extra cost.
        const speakingGlow = (this.robotState === 'engaging' && this.isSpeaking) ? this.state.mouthAmplitude * 16 : 0;

        // Whole-face tilt: rotate around the face's own center, layered on
        // top of breathing (which already happened above, via baseEyeSize)
        // rather than replacing it. The background fill above is drawn
        // outside this transform on purpose — the screen doesn't tilt,
        // just the face on it, like a head tilting within a fixed frame.
        ctx.save();
        ctx.translate(centerX, centerY);
        ctx.rotate(this.tilt);
        ctx.translate(-centerX, -centerY);

        this._drawEye(
            centerX - eyeSpacing / 2 + gazeOffsetX, centerY + gazeOffsetY,
            baseEyeSize * this.state.eyeWidthMul * leftMul, baseEyeSize * this.state.eyeHeightMul * leftMul,
            leftOpenness, speakingGlow
        );
        this._drawEye(
            centerX + eyeSpacing / 2 + gazeOffsetX, centerY + gazeOffsetY,
            baseEyeSize * this.state.eyeWidthMul * rightMul, baseEyeSize * this.state.eyeHeightMul * rightMul,
            rightOpenness, speakingGlow
        );

        this._drawMouth(centerX, centerY + baseEyeSize * 1.5, baseEyeSize * 1.6, speakingGlow);

        ctx.restore();
    }

    _drawEye(cx, cy, width, height, openness, extraGlow = 0) {
        const ctx = this.ctx;
        const eyeHeight = Math.max(2, height * Math.max(0.04, openness));
        // Squash-and-stretch: as the eye compresses toward a blink, it
        // bulges wider — cheap cartoon-physics cue that a straight height
        // tween doesn't give you.
        const stretchMul = 1 + (1 - openness) * 0.25;
        const eyeWidth = width * stretchMul;

        ctx.fillStyle = this.color;
        ctx.shadowColor = this.color;
        ctx.shadowBlur = 18 + extraGlow;

        if (this.mood === 'happy' && openness > 0.5) {
            // A distinct upward-arced "smiling eye" shape, not just a
            // squint — the classic simple-robot-face happy cue.
            const halfWidth = eyeWidth / 2;
            ctx.beginPath();
            ctx.moveTo(cx - halfWidth, cy + eyeHeight / 2);
            ctx.quadraticCurveTo(cx, cy + eyeHeight / 2 - eyeHeight * 1.6, cx + halfWidth, cy + eyeHeight / 2);
            ctx.quadraticCurveTo(cx, cy + eyeHeight / 2 - eyeHeight * 0.6, cx - halfWidth, cy + eyeHeight / 2);
            ctx.closePath();
            ctx.fill();
        } else {
            this._roundRectPath(cx - eyeWidth / 2, cy - eyeHeight / 2, eyeWidth, eyeHeight, Math.min(eyeWidth, eyeHeight) / 2);
            ctx.fill();
        }
        ctx.shadowBlur = 0;
    }

    _drawMouth(cx, cy, maxWidth, extraGlow = 0) {
        const ctx = this.ctx;
        const restHeight = maxWidth * 0.06;
        const maxHeight = maxWidth * 0.32;
        const height = restHeight + (maxHeight - restHeight) * this.state.mouthAmplitude;
        const width = maxWidth * (0.55 + 0.1 * this.state.mouthAmplitude);

        ctx.fillStyle = this.color;
        ctx.shadowColor = this.color;
        ctx.shadowBlur = 12 + extraGlow;
        this._roundRectPath(cx - width / 2, cy - height / 2, width, height, height / 2);
        ctx.fill();
        ctx.shadowBlur = 0;
    }

    /** Manual rounded-rect path (rather than the native ctx.roundRect,
     * which isn't available on every WebView/older Chromium the Pi's
     * kiosk browser might end up using) — builds the path only, caller
     * fills/strokes it. */
    _roundRectPath(x, y, w, h, r) {
        const ctx = this.ctx;
        r = Math.max(0, Math.min(r, w / 2, h / 2));
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
        ctx.closePath();
    }
}
