/**
 * Kiosk page glue: mode switching (face <-> info-display) + the debug
 * panel that stands in for real STT/conversation triggers until those
 * exist. See app.py's comment above /api/speak and /api/rag-query for why
 * this simulation approach, not the face rendering itself, lives here.
 */
import { Face } from './face.js';

const canvas = document.getElementById('face-canvas');
const face = new Face(canvas);

const faceContainer = document.getElementById('face-container');
const infoFrame = document.getElementById('info-frame');
const logEl = document.getElementById('debug-log');

const IDLE_TIMEOUT_MS = 45000;
let idleTimer = null;
let mode = 'face'; // 'face' | 'info'

function logEvent(message) {
    const time = new Date().toLocaleTimeString();
    const line = document.createElement('div');
    line.textContent = `[${time}] ${message}`;
    logEl.prepend(line);
    while (logEl.children.length > 8) logEl.removeChild(logEl.lastChild);
}

function showInfoPage(url) {
    infoFrame.src = url;
    infoFrame.style.display = 'block';
    faceContainer.style.display = 'none';
    mode = 'info';
    resetIdleTimer();
    logEvent(`Info-display mode: ${url}`);
}

function returnToFace() {
    infoFrame.style.display = 'none';
    infoFrame.src = 'about:blank';
    faceContainer.style.display = 'block';
    mode = 'face';
    clearIdleTimer();
    logEvent('Back to face mode');
}

function resetIdleTimer() {
    clearIdleTimer();
    idleTimer = setTimeout(() => {
        logEvent(`${IDLE_TIMEOUT_MS / 1000}s idle in info-display mode — auto-returning to face mode`);
        returnToFace();
    }, IDLE_TIMEOUT_MS);
}

function clearIdleTimer() {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = null;
}

// Only info-display mode has an idle timeout — face mode is the idle
// state, there's nothing to time out from.
['keydown', 'mousemove', 'mousedown', 'touchstart'].forEach((eventName) => {
    window.addEventListener(eventName, () => {
        if (mode === 'info') resetIdleTimer();
    });
});

document.getElementById('back-to-face-btn').addEventListener('click', returnToFace);

document.querySelectorAll('[data-mood]').forEach((button) => {
    button.addEventListener('click', () => {
        face.setMood(button.dataset.mood);
        logEvent(`Mood -> ${button.dataset.mood}`);
    });
});

// Direct state buttons (idle, engaging) just set the state. "Person
// detected" is special: in the real BehaviorStateMachine it auto-advances
// to ENGAGING in the same call (see state_machine.py's person_detected()),
// but that transition is instant there only because _orient_toward_person
// is a stub with nothing to wait for. Here it's given a visible hold
// (roughly the real stop+turn-servo time it stands in for) so the alert
// color is actually seen before settling into listening.
document.querySelectorAll('[data-robot-state]').forEach((button) => {
    button.addEventListener('click', () => {
        face.setRobotState(button.dataset.robotState);
        logEvent(`Robot state -> ${button.dataset.robotState}`);
    });
});

document.getElementById('person-detected-btn').addEventListener('click', () => {
    face.setRobotState('person_detected');
    logEvent('Robot state -> person_detected');
    setTimeout(() => {
        face.setRobotState('engaging');
        logEvent('Robot state -> engaging (auto, after orient hold)');
    }, 1000);
});

// Head-turn reaction: stands in for the real Arduino servo signal. Once
// that exists (see face.js's headTurn() docstring), whatever decodes the
// serial bridge's S:angle command into a direction calls
// face.headTurn(direction, durationMs) directly — this button is the only
// thing that goes away, face.js doesn't change.
document.querySelectorAll('[data-head-turn]').forEach((button) => {
    button.addEventListener('click', () => {
        const direction = button.dataset.headTurn;
        const duration = parseInt(document.getElementById('head-turn-duration').value, 10) || 900;
        face.headTurn(direction, duration);
        logEvent(`Head turn -> ${direction} (~${duration}ms)`);
    });
});

// --- Speaking mode: real Piper audio -> Web Audio analyser -> mouth sync -

let audioCtx = null;

document.getElementById('say-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = document.getElementById('say-input');
    const text = input.value.trim();
    if (!text) return;

    logEvent(`Synthesizing: "${text}"`);
    let response;
    try {
        response = await fetch('/api/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        });
    } catch (err) {
        logEvent(`Speech request failed: ${err}`);
        return;
    }
    if (!response.ok) {
        logEvent(`Speech synthesis failed (HTTP ${response.status})`);
        return;
    }

    const audioBytes = await response.arrayBuffer();
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const audioBuffer = await audioCtx.decodeAudioData(audioBytes);

    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;

    const source = audioCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(analyser);
    analyser.connect(audioCtx.destination);

    face.startSpeaking(analyser);
    logEvent('Speaking...');
    source.start();
    source.onended = () => {
        face.stopSpeaking();
        logEvent('Done speaking');
    };
});

// --- Info-display trigger: simulated RAG-matched visitor question --------

document.getElementById('rag-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = document.getElementById('rag-input');
    const text = input.value.trim();
    if (!text) return;

    logEvent(`Simulated visitor question: "${text}"`);
    let response;
    try {
        response = await fetch('/api/rag-query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        });
    } catch (err) {
        logEvent(`RAG query failed: ${err}`);
        return;
    }
    const data = await response.json();
    if (data.matched) {
        logEvent(`RAG match: ${data.source} (similarity ${data.similarity.toFixed(2)}) -> ${data.page_url}`);
        // A real match implies a real conversation is happening — keep the
        // face's state consistent even though it's hidden behind the
        // iframe right now, so it's already 'engaging' when face mode
        // returns.
        face.setRobotState('engaging');
        showInfoPage(data.page_url);
    } else {
        logEvent('No RAG match — staying in face mode');
    }
});
