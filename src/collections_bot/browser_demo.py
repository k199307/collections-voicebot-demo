BROWSER_DEMO_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mumbai Bank Collections Voicebot Demo</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif; color: #182230; background: #f4f7fb; }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 0; min-height: 100vh; background: #fff; }
    main { max-width: none; margin: 0 auto; }
    #testPanel { min-height: 100vh; display:flex; flex-direction:column; padding:28px clamp(20px, 4vw, 56px) 34px; color:#18181b; }
    .test-header { display:flex; align-items:center; justify-content:space-between; gap:16px; }
    .test-title { margin:0; font-size:30px; font-weight:520; letter-spacing:-.04em; }
    #showUnderHood, #backToTest { color:#27272a; background:#f3f3f4; border-radius:999px; padding:11px 17px; font-size:14px; font-weight:600; }
    #showUnderHood:hover, #backToTest:hover { background:#e8e8ea; }
    .test-center { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; padding:48px 0 28px; }
    #voiceVisualizer { height:190px; width:min(310px, 78vw); display:flex; align-items:center; justify-content:center; gap:5px; margin-bottom:26px; }
    #voiceVisualizer span { display:block; width:6px; height:var(--bar-height); max-height:100%; border-radius:999px; opacity:.86; background:linear-gradient(180deg,#f19ab3,#c82e62 55%,#e88eab); transform:scaleY(.82); transform-origin:center; }
    #voiceVisualizer.active span { animation:voicePulse .8s ease-in-out infinite alternate; animation-delay:var(--delay); }
    @keyframes voicePulse { from { transform:scaleY(.55); opacity:.62; } to { transform:scaleY(1); opacity:1; } }
    #stageHeading { margin:0; color:#52525b; font-size:clamp(22px,3vw,30px); font-weight:500; letter-spacing:-.025em; }
    #stageStatus { min-height:24px; margin:12px 0 0; color:#71717a; font-size:14px; }
    .stage-controls { display:flex; align-items:center; justify-content:center; flex-wrap:wrap; gap:12px; margin-top:34px; }
    .stage-call { min-width:220px; padding:18px 28px; display:inline-flex; align-items:center; justify-content:center; gap:12px; border-radius:999px; background:#f1f1f2; color:#18181b; font-size:21px; font-weight:520; }
    .stage-call:hover { background:#e5e5e7; }
    .stage-call.end-call { background:#fff0f1; color:#a11b3f; }
    .stage-call.end-call:hover { background:#ffe1e6; }
    .stage-call svg { width:23px; height:23px; }
    .stage-mute { min-height:58px; padding:14px 20px; display:inline-flex; align-items:center; justify-content:center; gap:9px; border:1px solid #e4e4e7; border-radius:999px; background:#fff; color:#27272a; font-size:16px; font-weight:550; }
    .stage-mute:hover { background:#f4f4f5; }
    .stage-mute[aria-pressed="true"] { background:#fff0f1; border-color:#f3c4cf; color:#a11b3f; }
    .stage-mute svg { width:20px; height:20px; }
    .test-footer { text-align:center; color:#a1a1aa; font-size:12px; }
    [hidden] { display:none !important; }
    #underHoodPanel { max-width:1100px; margin:26px auto; width:calc(100% - 32px); }
    .card { background: white; border: 1px solid #dce4ed; border-radius: 16px; padding: 24px; box-shadow: 0 8px 26px #24354b0a; }
    h1 { font-size: 24px; margin: 0 0 8px; }
    .sub, .hint { color: #5e6b7b; line-height: 1.5; }
    .bar { display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
    button { border: 0; border-radius: 9px; padding: 11px 15px; color: white; background: #174ea6; font-weight: 650; cursor: pointer; }
    button.secondary { background: #536273; }
    button.danger { background: #a52a2a; }
    button:disabled { opacity: .45; cursor: not-allowed; }
    #status { padding: 10px 12px; border-radius: 8px; background: #edf3fa; margin: 14px 0; }
    #status.error { color: #8d2020; background: #fff0ef; }
    #metrics { margin: 18px 0; }
    .metrics-head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:10px; }
    .metrics-head h2 { font-size:16px; margin:0; }
    #metricStatus { color:#5e6b7b; font-size:12px; }
    .metric-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:9px; }
    .metric { padding:12px; border:1px solid #e1e7ef; border-radius:10px; background:#fbfcfe; }
    .metric label { display:block; color:#5e6b7b; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
    .metric strong { display:block; margin-top:5px; font-size:20px; font-variant-numeric:tabular-nums; }
    .metric small { color:#6b7787; font-size:11px; }
    #metricsSummary, #classificationComparison, #classifierBreakdown { margin-top:10px; color:#5e6b7b; font-size:12px; line-height:1.5; }
    #transcript { border: 1px solid #e1e7ef; background: #fbfcfe; border-radius: 10px; min-height: 145px; max-height: 420px; overflow: auto; padding: 14px; }
    .turn { padding: 9px 0; border-bottom: 1px solid #edf0f4; white-space: pre-wrap; line-height: 1.5; }
    .mic-diagnostic { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin-top:7px; }
    .mic-diagnostic button { padding:7px 10px; font-size:11px; }
    .turn:last-child { border-bottom: 0; }
    .speaker { font-weight: 700; margin-right: 7px; }
    .session-marker { margin: 10px 0 4px; padding: 8px 0; border-top: 1px solid #dce4ed; color:#5e6b7b; font-size:12px; font-weight:700; }
    #otpBox { padding: 16px; margin: 14px 0; border:1px solid #d9e2ef; border-radius: 12px; background: #f8fafc; }
    #otpBox[aria-disabled="true"] { background:#f5f6f8; }
    .otp-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
    .otp-badge { padding:4px 8px; border-radius:999px; background:#e8edf4; color:#4c5c70; font-size:11px; font-weight:700; }
    #otpStatus { margin:7px 0 10px; color:#5e6b7b; font-size:13px; }
    .otp-controls { display:flex; align-items:center; flex-wrap:wrap; gap:9px; }
    #otp { width:180px; letter-spacing:.15em; }
    input { font-size: 16px; padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px; width: 160px; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; background: #f4f6f9; border-radius: 8px; padding: 12px; }
    .fine { font-size: 12px; }
    .trace { margin-top:16px; border:1px solid #dce4ed; border-radius:12px; background:#f8fafc; overflow:hidden; }
    .trace summary { cursor:pointer; list-style:none; display:flex; justify-content:space-between; gap:12px; padding:14px 16px; font-weight:700; }
    .trace summary::-webkit-details-marker { display:none; }
    .trace-intro { margin:0; padding:0 16px 12px; color:#5e6b7b; font-size:12px; line-height:1.5; }
    #traceLog { max-height:680px; overflow:auto; padding:0 12px 12px; }
    .trace-turn { margin-top:10px; padding:12px; border:1px solid #e1e7ef; border-radius:10px; background:white; }
    .trace-turn-heading { display:flex; align-items:center; justify-content:space-between; gap:10px; margin:0 0 8px; font-size:13px; }
    .prompt-version-flag { display:inline-flex; align-items:center; border:1px solid #c9d9eb; border-radius:999px; padding:3px 8px; background:#edf5fc; color:#284d70; font-size:10px; font-weight:700; line-height:1.3; }
    .trace-section-title { margin:9px 0 4px; color:#5e6b7b; font-size:10px; font-weight:750; text-transform:uppercase; letter-spacing:.05em; }
    .trace-list { margin:0; padding-left:18px; font-size:12px; line-height:1.55; }
    .trace-list li { padding:2px 0; }
    .trace-status { color:#385778; font-weight:650; }
    .llm-stage { margin:8px 0; border:1px solid #e1e7ef; border-radius:8px; background:#fbfcfe; }
    .llm-stage > summary { padding:9px 10px; font-size:12px; }
    .llm-payload { padding:0 10px 10px; }
    .llm-payload details { margin:6px 0; border-top:1px solid #e8edf3; }
    .llm-payload details > summary { padding:7px 0; font-size:11px; font-weight:650; }
    .llm-payload pre { max-height:340px; overflow:auto; margin:0; }
    @media (max-width:600px) {
      #testPanel { padding:22px 18px 24px; }
      .test-title { font-size:25px; }
      #voiceVisualizer { height:160px; }
      .stage-controls { flex-direction:column; width:100%; }
      .stage-call, .stage-mute { width:min(100%, 290px); }
      .stage-call { min-width:205px; padding:16px 24px; font-size:19px; }
      #underHoodPanel .card { padding:18px; }
    }
  </style>
</head>
<body>
<main>
  <section id="testPanel" aria-label="Test agent">
    <header class="test-header">
      <h1 class="test-title">Test Agent</h1>
      <button id="showUnderHood" type="button" aria-expanded="false">Under the hood</button>
    </header>
    <div class="test-center">
      <div id="voiceVisualizer" aria-hidden="true"></div>
      <h2 id="stageHeading">Start a call to test the agent</h2>
      <p id="stageStatus" role="status">Your browser microphone and speakers will be used for this demo.</p>
      <div class="stage-controls">
        <button id="callAgent" class="stage-call" type="button">
          <svg id="callIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.9.34 1.78.65 2.62a2 2 0 0 1-.45 2.11L8.04 9.73a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.84.31 1.72.53 2.62.65A2 2 0 0 1 22 16.92z"/></svg>
          <span id="callLabel">Call agent</span>
        </button>
        <button id="muteMain" class="stage-mute" type="button" aria-pressed="false" disabled>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/></svg>
          <span id="muteMainLabel">Mute microphone</span>
        </button>
      </div>
    </div>
    <section id="otpBox" aria-disabled="true" aria-labelledby="otpTitle" hidden>
      <div class="otp-head"><strong id="otpTitle">OTP verification</strong><span class="otp-badge">Demo module</span></div>
      <p id="otpStatus" role="status">If verification is needed, enter the six-digit code here. Never say an OTP aloud.</p>
      <div class="otp-controls">
        <input id="otp" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code" aria-label="Six-digit one-time password" placeholder="Enter 6-digit OTP" disabled>
        <button id="showCode" class="secondary" disabled>Show demo code</button>
        <button id="verifyOtp" disabled>Verify OTP</button>
      </div>
      <p class="hint fine">The demo code is available only in this local browser demo. The code entered here is not sent to speech recognition.</p>
    </section>
    <footer class="test-footer">Local browser demo · no phone call is placed</footer>
  </section>

  <section id="underHoodPanel" class="card" hidden>
    <div class="bar" style="margin-top:0;justify-content:space-between;align-items:center">
      <div><h1 style="margin:0">Under the hood</h1><p class="sub" style="margin:5px 0 0">Conversation transcript, performance, outcomes, and backend decisions.</p></div>
      <button id="backToTest" type="button">Back to Test Agent</button>
    </div>
    <h1>Collections voicebot</h1>
    <p class="sub">Local browser demo using your microphone and speakers. It creates synthetic test data; it does not place a phone call.</p>
    <div id="status">Ready. Start a conversation to begin.</div>
    <section id="metrics" aria-label="Live performance dashboard">
      <div class="metrics-head"><h2>Live performance</h2><span id="metricStatus">No turns yet</span></div>
      <div class="metric-grid">
        <div class="metric"><label>Speech to first audio</label><strong id="mResponse">—</strong><small>Customer stops → bot starts</small></div>
        <div class="metric"><label>Extra STT wait</label><strong id="mStt">—</strong><small>Zero when the live transcript is reused</small></div>
        <div class="metric"><label>Intent / LLM</label><strong id="mLlm">—</strong><small>Policy stays application-controlled</small></div>
        <div class="metric"><label>Voice first audio</label><strong id="mTtsFirst">—</strong><small>Time to first audio chunk</small></div>
        <div class="metric"><label>Voice complete</label><strong id="mTtsTotal">—</strong><small>Full response synthesis</small></div>
        <div class="metric"><label>Server API</label><strong id="mApi">—</strong><small>Server-side request time</small></div>
      </div>
      <div id="classificationComparison" class="metrics-summary">Identity-versus-other timing: waiting for labeled turn samples.</div>
      <div id="classifierBreakdown" class="metrics-summary">LLM classifier phases: waiting for model-call samples.</div>
      <div id="metricsSummary">Completed turns: 0 · Mic interruptions: 0 · Errors: 0 · Rolling average (last 10 turns): waiting for data.</div>
    </section>
    <div class="bar">
      <button id="start">Start new conversation</button>
      <button id="mute" class="secondary" disabled>Mute microphone</button>
      <button id="finish" class="secondary" disabled>End conversation</button>
      <button id="downloadAudio" class="secondary" disabled>Download call audio</button>
    </div>
    <div id="transcript" aria-live="polite"><div class="hint empty-transcript">Conversation transcript will appear here.</div></div>
    <details id="backendTrace" class="trace" open>
      <summary><span>Backend execution trace</span><span id="traceCount" class="hint fine">No turns yet</span></summary>
      <p class="trace-intro">Rule evaluations and triggers, plus the structured inputs and outputs for each LLM stage. LLM payloads can contain customer transcripts and masked account context; keep this local diagnostic view private.</p>
      <div id="traceLog" aria-live="polite"><div class="hint fine">Backend rules and LLM activity will appear here after a turn.</div></div>
    </details>
    <p class="hint fine">The microphone stays on during the conversation. Pauses are detected automatically. To interrupt the bot, speak clearly for a moment; brief background noise is filtered. Use Mute microphone or End conversation when needed.</p>
    <p class="hint fine">Live audio is streamed to the configured speech provider for transcription. A mixed recording of the customer and bot is kept in this browser for the current conversation; use Download call audio to save it. Each customer turn also gets a mic-only WAV download of its 16 kHz audio capture for STT diagnosis. When the STT connection is active, this is the same audio sent for recognition. These recordings stay in this browser and are not uploaded to the application server.</p>
    <details style="margin-top:16px">
      <summary>Latest structured outcome</summary>
      <pre id="outcome">No outcome yet.</pre>
    </details>
    <p class="hint fine">Audio is sent to the configured speech provider for transcription. When configured, the language model uses recent turns to understand the conversation and shape natural replies. The application retains control of identity, opt-outs, verification, and recorded outcomes.</p>
  </section>
</main>
<script>
let sessionId = null;
let mediaStream = null;
let recorder = null;
let chunks = [];
let ended = true;
let muted = false;
let processing = false;
let speaking = false;
let audioContext = null;
let analyser = null;
let callRecordingDestination = null;
let callAudioRecorder = null;
let callAudioChunks = [];
let callAudioBlob = null;
let liveSttSocket = null;
let liveSttProcessor = null;
let liveSttSilentGain = null;
let liveCustomerRow = null;
let liveFinalText = '';
let livePartialText = '';
let liveSttConfidences = [];
let liveSttFinalResolver = null;
let utterancePcmChunks = [];
let preRollPcmChunks = [];
const PRE_ROLL_CHUNK_COUNT = 4;
let utterancePcmStartedAt = null;
let voiceProvider = 'deepgram';
let sttSpeechStarted = false;
let vadFrame = null;
let speechFrames = 0;
let speechStartedAt = null;
let silenceStartedAt = null;
let identityPauseTimer = null;
const VOICE_ACTIVITY_RMS_THRESHOLD = 0.025;
const VOICE_ACTIVITY_START_FRAMES = 4;
const BARGE_IN_RMS_THRESHOLD = 0.065;
const BARGE_IN_START_FRAMES = 15;
const UTTERANCE_END_SILENCE_MS = 800;
const IDENTITY_REMINDER_PAUSE_MS = 3000;
let ambientNoiseRms = 0.01;
let activeTtsSocket = null;
let activeSources = new Set();
let activeMediaElement = null;
let activeMediaUrl = null;
let activeMediaSourceNode = null;
let latencySamples = [];
let latestTimings = {};
let turnCount = 0;
let interruptionCount = 0;
let errorCount = 0;
let utteranceEndedAt = null;
let queuedUtterances = [];
let traceTurnCount = 0;
let otpPausedMic = false;
let otpWasMuted = false;
let openingPending = false;
let openingTimer = null;
let openingText = '';
let identityPromptDelivered = false;
let identityDeliveryPromise = null;
let botAudioInterrupted = false;
let llmConfigured = false;
const $ = (id) => document.getElementById(id);

function syncMuteControls() {
  const disabled = ended || otpPausedMic || !mediaStream;
  const label = muted ? 'Unmute microphone' : 'Mute microphone';
  for (const id of ['mute', 'muteMain']) {
    const button = $(id);
    if (!button) continue;
    button.disabled = disabled;
    if (id === 'muteMain') $('muteMainLabel').textContent = label;
    else button.textContent = label;
    button.setAttribute('aria-pressed', String(muted));
  }
}

function setOtpModule(active, message = null) {
  if (active && !otpPausedMic) {
    otpPausedMic = true;
    otpWasMuted = muted;
    muted = true;
    if (mediaStream) mediaStream.getAudioTracks().forEach(track => { track.enabled = false; });
    if (recorder) stopUtterance();
    queuedUtterances = [];
  } else if (!active && otpPausedMic) {
    otpPausedMic = false;
    muted = otpWasMuted;
    if (mediaStream) mediaStream.getAudioTracks().forEach(track => { track.enabled = !muted; });
  }
  syncMuteControls();
  $('otpBox').hidden = !active;
  $('otpBox').setAttribute('aria-disabled', String(!active));
  $('otpStatus').textContent = message || (active
    ? 'Verification is required. Enter the six-digit code here; do not say it aloud.'
    : 'If verification is needed, enter the six-digit code here. Never say an OTP aloud.');
  $('otp').disabled = !active;
  $('showCode').disabled = !active;
  $('verifyOtp').disabled = !active || $('otp').value.length !== 6;
  if (!active) $('otp').value = '';
}

function status(message, error = false) {
  $('status').textContent = message;
  $('status').className = error ? 'error' : '';
  if ($('stageStatus')) {
    $('stageStatus').textContent = message;
    $('stageStatus').style.color = error ? '#a11b3f' : '';
    syncTestPanel();
  }
}
function syncTestPanel() {
  const active = !ended;
  $('stageHeading').textContent = active ? (speaking ? 'Your agent is speaking' : 'Call in progress') : 'Start a call to test the agent';
  $('callLabel').textContent = active ? 'End call' : 'Call agent';
  $('callAgent').classList.toggle('end-call', active);
  syncMuteControls();
  $('voiceVisualizer').classList.toggle('active', active);
  $('callIcon').innerHTML = active
    ? '<rect x="6" y="6" width="12" height="12" rx="2"/>'
    : '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.9.34 1.78.65 2.62a2 2 0 0 1-.45 2.11L8.04 9.73a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.84.31 1.72.53 2.62.65A2 2 0 0 1 22 16.92z"/>';
}
for (let i = 0; i < 31; i++) {
  const bar = document.createElement('span');
  const height = 25 + Math.round((Math.sin(i * 1.7) + 1) * 31) + (i % 4) * 5;
  bar.style.setProperty('--bar-height', `${Math.min(100, height)}%`);
  bar.style.setProperty('--delay', `${(i % 9) * -0.11}s`);
  $('voiceVisualizer').append(bar);
}
syncTestPanel();
function addTurn(who, text, extra = '') {
  const row = document.createElement('div');
  row.className = 'turn';
  const label = document.createElement('span');
  label.className = 'speaker';
  label.textContent = who + ':';
  const body = document.createElement('span');
  body.className = 'turn-text';
  body.textContent = text;
  row.append(label, body);
  if (extra) {
    const detail = document.createElement('div');
    detail.className = 'hint fine';
    detail.textContent = extra;
    row.append(detail);
  }
  if ($('transcript').querySelector('.empty-transcript')) $('transcript').replaceChildren();
  $('transcript').append(row);
  $('transcript').scrollTop = $('transcript').scrollHeight;
  return row;
}
function updateTurnText(row, text) {
  if (!row) return;
  const body = row.querySelector('.turn-text');
  if (body) body.textContent = text || 'Listening…';
  $('transcript').scrollTop = $('transcript').scrollHeight;
}
function appendTracePayload(parent, label, value) {
  const details = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = label;
  const pre = document.createElement('pre');
  pre.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  details.append(summary, pre);
  parent.append(details);
}
function appendLlmStage(parent, stageName, stage) {
  const details = document.createElement('details');
  details.className = 'llm-stage';
  const summary = document.createElement('summary');
  const status = stage && stage.status ? stage.status : 'not reported';
  const model = stage && stage.model ? ` · ${stage.model}` : '';
  const version = stage && stage.prompt_version ? ` · ${stage.prompt_version}` : '';
  summary.textContent = `${stageName}: ${status}${model}${version}`;
  details.append(summary);
  const payload = document.createElement('div');
  payload.className = 'llm-payload';
  if (stage && stage.reason) {
    const reason = document.createElement('p');
    reason.className = 'hint fine';
    reason.textContent = `Reason: ${stage.reason}`;
    payload.append(reason);
  }
  if (stage && stage.error_type) {
    const error = document.createElement('p');
    error.className = 'hint fine';
    error.textContent = `Error: ${stage.error_type}${stage.error_detail ? ` — ${stage.error_detail}` : ''}`;
    payload.append(error);
  }
  if (stage && stage.local_interpretation) appendTracePayload(payload, 'Local interpretation (LLM skipped)', stage.local_interpretation);
  if (stage && stage.instructions) appendTracePayload(payload, 'System instructions', stage.instructions);
  if (stage && stage.input !== undefined) appendTracePayload(payload, 'Input payload', stage.input);
  if (stage && stage.response_format) appendTracePayload(payload, 'Output schema', stage.response_format);
  if (stage && stage.output_raw !== undefined) appendTracePayload(payload, 'Raw LLM output', stage.output_raw);
  if (stage && stage.output_parsed !== undefined) appendTracePayload(payload, 'Parsed LLM output', stage.output_parsed);
  details.append(payload);
  parent.append(details);
}
function addBackendTrace(result) {
  const metadata = result.metadata || {};
  const log = $('traceLog');
  if (log.querySelector('.hint')) log.replaceChildren();
  traceTurnCount++;
  $('traceCount').textContent = `${traceTurnCount} ${traceTurnCount === 1 ? 'turn' : 'turns'}`;

  const entry = document.createElement('article');
  entry.className = 'trace-turn';
  const heading = document.createElement('h3');
  heading.className = 'trace-turn-heading';
  heading.textContent = `Turn ${traceTurnCount}`;
  const promptFlag = document.createElement('span');
  promptFlag.className = 'prompt-version-flag';
  const intentStage = (metadata.llm_trace || {}).intent_classifier || {};
  const promptVersion = intentStage.prompt_version || metadata.prompt_version || 'not reported';
  const promptStatus = intentStage.status === 'skipped'
    ? 'not sent this turn'
    : intentStage.status === 'error' ? 'request failed' : 'used';
  promptFlag.textContent = `Prompt ${promptVersion} · ${promptStatus}`;
  heading.append(promptFlag);
  entry.append(heading);
  const trace = Array.isArray(metadata.decision_trace) ? metadata.decision_trace : [];
  const rulesTitle = document.createElement('div');
  rulesTitle.className = 'trace-section-title';
  rulesTitle.textContent = 'Backend rules evaluated and triggered';
  entry.append(rulesTitle);
  if (trace.length) {
    const rulesList = document.createElement('ul');
    rulesList.className = 'trace-list';
    for (const rule of trace) {
      const item = document.createElement('li');
      const label = document.createElement('span');
      label.className = 'trace-status';
      label.textContent = `${rule.rule} — ${rule.status}: `;
      const explanation = document.createElement('span');
      explanation.textContent = rule.explanation;
      item.append(label, explanation);
      rulesList.append(item);
    }
    entry.append(rulesList);
  } else {
    const none = document.createElement('p');
    none.className = 'hint fine';
    none.textContent = 'No explicit policy rule was recorded for this turn.';
    entry.append(none);
  }

  const llmTitle = document.createElement('div');
  llmTitle.className = 'trace-section-title';
  llmTitle.textContent = 'LLM request and response';
  entry.append(llmTitle);
  const llmTrace = metadata.llm_trace || {};
  appendLlmStage(entry, 'Intent interpreter', llmTrace.intent_classifier);
  appendLlmStage(entry, 'Response generator', llmTrace.response_generator);

  log.append(entry);
  log.scrollTop = log.scrollHeight;
}
function markConversationStart() {
  const transcript = $('transcript');
  if (!transcript.querySelector('.empty-transcript')) {
    const marker = document.createElement('div');
    marker.className = 'session-marker';
    marker.textContent = `New conversation · ${new Date().toLocaleString()}`;
    transcript.append(marker);
  }
  const traceLog = $('traceLog');
  if (traceTurnCount > 0) {
    const marker = document.createElement('div');
    marker.className = 'session-marker';
    marker.textContent = `New conversation · ${new Date().toLocaleString()}`;
    traceLog.append(marker);
  }
}
function receiveLiveTranscript(message) {
  // Only render live STT events while a customer turn is actively being
  // recorded. This drops late results and any speaker echo between turns.
  if (!recorder || !liveCustomerRow) return;
  let event;
  try { event = JSON.parse(message.data); } catch (_) { return; }
  const transcript = event.channel?.alternatives?.[0]?.transcript?.trim();
  if (!transcript) return;
  // Streaming STT may notice the caller before the local VAD crosses its
  // threshold. Treat that as speech too, so the silence timer cannot win a race.
  if (openingPending) {
    clearTimeout(openingTimer);
    openingTimer = setTimeout(() => { playCallOpening().catch(error => status(error.message, true)); }, 2500);
  }
  if (event.is_final) {
    liveFinalText = [liveFinalText, transcript].filter(Boolean).join(' ');
    const confidence = event.channel?.alternatives?.[0]?.confidence;
    if (Number.isFinite(confidence)) liveSttConfidences.push(confidence);
    livePartialText = '';
    if (liveSttFinalResolver) {
      const resolveFinal = liveSttFinalResolver;
      liveSttFinalResolver = null;
      resolveFinal();
    }
  } else {
    livePartialText = transcript;
  }
  updateTurnText(liveCustomerRow, [liveFinalText, livePartialText].filter(Boolean).join(' ') || 'Listening…');
}
function isPickupAcknowledgment(transcript) {
  const text = (transcript || '').toLowerCase().replace(/[^a-z0-9\u0900-\u097f' ]/g, ' ').replace(/\s+/g, ' ').trim();
  if (!text) return false;
  return /^(?:hi|hello|hey|namaste|good morning|good afternoon|good evening|yes|yeah|yep|yup|okay|ok|all right|alright|right|haan|han|हाँ|हां|जी)(?:\s+(?:there|hello|hi|so|yes|yeah|okay|ok|ji|sir|madam|जी))*$/.test(text);
}
async function playCallOpening() {
  if (!openingPending || ended) return;
  // The silence timer can race with the microphone activity detector. Never
  // start the opening over an utterance that is already being recorded.
  if ((recorder && recorder.state !== 'inactive') || speechFrames > 0) {
    clearTimeout(openingTimer);
    openingTimer = setTimeout(() => { playCallOpening().catch(error => status(error.message, true)); }, 300);
    return;
  }
  openingPending = false;
  clearTimeout(openingTimer);
  openingTimer = null;
  const opening = openingText;
  addTurn('Bot', opening, llmConfigured ? 'Call opening · identity confirmation required before account details' : 'Call opening · deterministic conversation flow');
  botAudioInterrupted = false;
  await playStreamAudio(opening);
  // A barge-in can make playStreamAudio resolve even though the customer did
  // not hear the complete identity question. Do not activate confirmation.
  if (botAudioInterrupted || ended) return;
  // The caller has heard the complete identity question. Mark this locally
  // before waiting on the network so a response in this small gap is not
  // mislabeled as speech from before the opening.
  identityPromptDelivered = true;
  identityDeliveryPromise = fetch(`/demo/session/${sessionId}/opening-delivered`, {method: 'POST'});
  const delivered = await identityDeliveryPromise;
  if (!delivered.ok) await handleApiError(delivered);
  if (!ended) status('Listening continuously. Please confirm whether you are the person named.');
}
function downsampleToPcm16(input, inputRate) {
  const ratio = inputRate / 16000;
  const outputLength = Math.floor(input.length / ratio);
  const buffer = new ArrayBuffer(outputLength * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < outputLength; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), input.length);
    let total = 0;
    for (let j = start; j < end; j++) total += input[j];
    const sample = Math.max(-1, Math.min(1, total / Math.max(1, end - start)));
    view.setInt16(i * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
  }
  return buffer;
}
function makePcm16Wav(chunks, sampleRate = 16000) {
  const byteLength = chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
  const wav = new ArrayBuffer(44 + byteLength);
  const view = new DataView(wav);
  const writeText = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  writeText(0, 'RIFF'); view.setUint32(4, 36 + byteLength, true); writeText(8, 'WAVE');
  writeText(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); writeText(36, 'data'); view.setUint32(40, byteLength, true);
  const output = new Uint8Array(wav, 44);
  let offset = 0;
  for (const chunk of chunks) { output.set(new Uint8Array(chunk), offset); offset += chunk.byteLength; }
  return new Blob([wav], {type: 'audio/wav'});
}
function attachMicDiagnostic(row, chunks, startedAt, endedAt) {
  if (!row || !chunks || !chunks.length) return;
  const bytes = chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
  const durationSeconds = bytes / (16000 * 2);
  const tools = document.createElement('div');
  tools.className = 'mic-diagnostic';
  const note = document.createElement('span');
  note.className = 'hint fine';
  note.textContent = `Mic audio capture · 16 kHz mono · ${durationSeconds.toFixed(2)} s · VAD capture ${(Math.max(0, endedAt - startedAt) / 1000).toFixed(2)} s`;
  const button = document.createElement('button');
  button.className = 'secondary';
  button.textContent = 'Download mic-only STT audio';
  button.onclick = () => {
    const url = URL.createObjectURL(makePcm16Wav(chunks));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `mic-stt-utterance-${new Date().toISOString().replace(/[:.]/g, '-')}.wav`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  tools.append(note, button);
  row.append(tools);
}
function showOutcome(response) {
  if (response && response.outcome) $('outcome').textContent = JSON.stringify(response.outcome, null, 2);
}
const metricRows = () => latencySamples;
const fmt = (value) => typeof value !== 'number' ? '—' : value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(2)} s`;
function average(key) {
  const values = metricRows().map(sample => sample[key]).filter(value => typeof value === 'number');
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}
function renderMetrics() {
  $('mResponse').textContent = fmt(latestTimings.customer_to_first_audio_ms);
  $('mStt').textContent = fmt(latestTimings.stt);
  $('mLlm').textContent = fmt(latestTimings.llm);
  $('mTtsFirst').textContent = fmt(latestTimings.tts_first_audio_ms);
  $('mTtsTotal').textContent = fmt(latestTimings.tts_total_ms);
  $('mApi').textContent = fmt(latestTimings.api);
  const n = latencySamples.length;
  $('metricStatus').textContent = n ? `Latest turn · ${n} in rolling window` : 'No customer turns yet';
  const identitySamples = latencySamples.filter(sample => sample.conversation_state === 'identity_confirmation');
  const otherSamples = latencySamples.filter(sample => sample.conversation_state && sample.conversation_state !== 'identity_confirmation');
  const groupAverage = (samples, key) => {
    const values = samples.map(sample => sample[key]).filter(value => typeof value === 'number');
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  };
  const identityLabel = identitySamples.length
    ? `Identity turns (${identitySamples.length}): classifier ${fmt(groupAverage(identitySamples, 'llm'))}, server ${fmt(groupAverage(identitySamples, 'api'))}, first audio ${fmt(groupAverage(identitySamples, 'customer_to_first_audio_ms'))}`
    : 'Identity turns: no sample yet';
  const otherLabel = otherSamples.length
    ? `Other turns (${otherSamples.length}): classifier ${fmt(groupAverage(otherSamples, 'llm'))}, server ${fmt(groupAverage(otherSamples, 'api'))}, first audio ${fmt(groupAverage(otherSamples, 'customer_to_first_audio_ms'))}`
    : 'Other turns: no sample yet';
  const identityLlm = groupAverage(identitySamples, 'llm');
  const otherLlm = groupAverage(otherSamples, 'llm');
  const comparison = identityLlm != null && otherLlm != null
    ? `Identity classifier difference: ${fmt(identityLlm - otherLlm)} ${identityLlm >= otherLlm ? 'slower' : 'faster'} than other turns.`
    : 'Collect at least one identity turn and one other turn to compare.';
  $('classificationComparison').textContent = `${identityLabel} · ${otherLabel} · ${comparison}`;
  const modelSamples = latencySamples.filter(sample => typeof sample.classifier_model_request_ms === 'number');
  const timeoutCount = modelSamples.filter(sample => sample.classifier_error_type === 'APITimeoutError').length;
  const inputTokens = groupAverage(modelSamples, 'classifier_input_tokens');
  const outputTokens = groupAverage(modelSamples, 'classifier_output_tokens');
  const cachedTokens = groupAverage(modelSamples, 'classifier_cached_input_tokens');
  const tokenLabel = inputTokens == null || outputTokens == null
    ? 'token usage unavailable'
    : `avg tokens in/out ${Math.round(inputTokens)}/${Math.round(outputTokens)}${cachedTokens == null ? '' : `; cached input ${Math.round(cachedTokens)}`}`;
  $('classifierBreakdown').textContent = modelSamples.length
    ? `LLM classifier phases (${modelSamples.length} calls): prompt/context prep ${fmt(groupAverage(modelSamples, 'classifier_prompt_ms'))}, model request ${fmt(groupAverage(modelSamples, 'classifier_model_request_ms'))}, response parse ${fmt(groupAverage(modelSamples, 'classifier_parse_ms'))}, total ${fmt(groupAverage(modelSamples, 'classifier_total_ms'))}; ${tokenLabel}; timeouts ${timeoutCount}. Model request includes network transit and provider processing.`
    : 'LLM classifier phases: waiting for model-call samples.';
  $('metricsSummary').textContent = `Completed turns: ${turnCount} · Mic interruptions: ${interruptionCount} · Errors: ${errorCount} · Last ${n} turn average — customer speech end to first received audio ${fmt(average('customer_to_first_audio_ms'))}, STT ${fmt(average('stt'))}, LLM ${fmt(average('llm'))}, TTS first chunk ${fmt(average('tts_first_audio_ms'))}, server API ${fmt(average('api'))}, browser request round trip ${fmt(average('client_api'))}.`;
}
function recordTurnMetrics(timings, requestMs, responseStartedAt, metadata = {}) {
  const classifier = metadata.classifier_timings_ms || {};
  latestTimings = {
    ...timings,
    client_api: requestMs,
    _responseStartedAt: responseStartedAt,
    intent: metadata.intent || 'unclear',
    conversation_state: metadata.conversation_state || 'unknown',
    intent_source: metadata.intent_source || 'unknown',
    classifier_prompt_ms: classifier.prompt_build_ms,
    classifier_model_request_ms: classifier.model_request_ms,
    classifier_parse_ms: classifier.response_parse_ms,
    classifier_total_ms: classifier.total_ms,
    classifier_input_tokens: classifier.input_tokens,
    classifier_output_tokens: classifier.output_tokens,
    classifier_cached_input_tokens: classifier.cached_input_tokens,
    classifier_error_type: metadata.llm_error_type || null
  };
  latencySamples.push(latestTimings);
  latencySamples = latencySamples.slice(-10);
  turnCount++;
  renderMetrics();
}
function updateTtsTiming(event) {
  if (event.tts_first_audio_ms != null) latestTimings.tts_first_audio_ms = event.tts_first_audio_ms;
  if (event.tts_total_ms != null) latestTimings.tts_total_ms = event.tts_total_ms;
  if (event.browser_first_audio_ms != null && latestTimings.customer_to_first_audio_ms == null) latestTimings.customer_to_first_audio_ms = event.browser_first_audio_ms;
  if (latencySamples.length) Object.assign(latencySamples[latencySamples.length - 1], latestTimings);
  renderMetrics();
}
function stopBotAudio() {
  if (activeTtsSocket) {
    try { activeTtsSocket.close(1000, 'customer_barge_in'); } catch (_) {}
    activeTtsSocket = null;
  }
  for (const source of activeSources) {
    try { source.stop(); } catch (_) {}
  }
  activeSources.clear();
  if (activeMediaElement) {
    activeMediaElement.pause();
    activeMediaElement.removeAttribute('src');
    activeMediaElement.load();
    activeMediaElement = null;
  }
  if (activeMediaSourceNode) {
    try { activeMediaSourceNode.disconnect(); } catch (_) {}
    activeMediaSourceNode = null;
  }
  if (activeMediaUrl) {
    URL.revokeObjectURL(activeMediaUrl);
    activeMediaUrl = null;
  }
  speaking = false;
  syncTestPanel();
}
async function playStreamAudio(text) {
  if (!text || ended) return;
  if (!audioContext) audioContext = new AudioContext();
  await audioContext.resume();
  const socketScheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${socketScheme}//${location.host}/demo/tts`);
  socket.binaryType = 'arraybuffer';
  activeTtsSocket = socket;
  speaking = true;
  syncTestPanel();
  speechFrames = 0;
  silenceStartedAt = null;
  status('Bot speaking. You can interrupt at any time.');
  return new Promise((resolve, reject) => {
    let pendingAudio = 0;
    let synthesisComplete = false;
    let settled = false;
    let audioMimeType = '';
    let mediaSource = null;
    let mediaSourceBuffer = null;
    let mediaElement = null;
    let mediaQueue = [];
    let mediaStreamComplete = false;
    let playbackClock = audioContext.currentTime + 0.04;
    const responseStartedAt = latestTimings._responseStartedAt || performance.now();
    const finish = () => {
      if (settled) return;
      settled = true;
      if (activeTtsSocket === socket) activeTtsSocket = null;
      if (activeMediaElement === mediaElement) activeMediaElement = null;
      if (activeMediaSourceNode) {
        try { activeMediaSourceNode.disconnect(); } catch (_) {}
        activeMediaSourceNode = null;
      }
      if (activeMediaUrl) {
        URL.revokeObjectURL(activeMediaUrl);
        activeMediaUrl = null;
      }
      speaking = false;
      syncTestPanel();
      resolve();
    };
    const maybeFinish = () => { if (synthesisComplete && pendingAudio === 0) finish(); };
    const endMediaStreamIfReady = () => {
      if (!mediaStreamComplete || !mediaSourceBuffer || mediaSourceBuffer.updating || mediaQueue.length) return;
      if (mediaSource?.readyState === 'open') {
        try { mediaSource.endOfStream(); } catch (_) {}
      }
    };
    const drainMediaQueue = () => {
      if (!mediaSourceBuffer || mediaSourceBuffer.updating || !mediaQueue.length) {
        endMediaStreamIfReady();
        return;
      }
      mediaSourceBuffer.appendBuffer(mediaQueue.shift());
    };
    const beginCompressedAudio = (mimeType) => {
      audioMimeType = mimeType || 'audio/mpeg';
      if (!window.MediaSource || !MediaSource.isTypeSupported(audioMimeType)) {
        reject(new Error(`This browser cannot play Sarvam audio format ${audioMimeType}.`));
        return;
      }
      mediaSource = new MediaSource();
      mediaElement = new Audio();
      activeMediaElement = mediaElement;
      activeMediaUrl = URL.createObjectURL(mediaSource);
      mediaElement.src = activeMediaUrl;
      activeMediaSourceNode = audioContext.createMediaElementSource(mediaElement);
      activeMediaSourceNode.connect(audioContext.destination);
      if (callRecordingDestination) activeMediaSourceNode.connect(callRecordingDestination);
      mediaElement.onended = finish;
      mediaElement.onerror = () => { if (!settled) reject(new Error('Sarvam audio playback failed.')); };
      mediaSource.addEventListener('sourceopen', () => {
        try {
          mediaSourceBuffer = mediaSource.addSourceBuffer(audioMimeType);
          mediaSourceBuffer.addEventListener('updateend', drainMediaQueue);
          drainMediaQueue();
        } catch (_) {
          reject(new Error(`Could not start playback for ${audioMimeType}.`));
        }
      }, {once: true});
    };
    socket.onopen = () => socket.send(JSON.stringify({text}));
    socket.onmessage = (message) => {
      if (typeof message.data === 'string') {
        const event = JSON.parse(message.data);
        if (event.type === 'error') { if (activeTtsSocket === socket) activeTtsSocket = null; speaking = false; reject(new Error(event.message || 'TTS unavailable')); socket.close(); return; }
        if (event.type === 'audio_format') { beginCompressedAudio(event.mime_type); return; }
        if (event.type === 'timing') {
          updateTtsTiming(event);
        }
        if (event.tts_total_ms != null) {
          synthesisComplete = true;
          if (mediaElement) {
            mediaStreamComplete = true;
            endMediaStreamIfReady();
          } else maybeFinish();
        }
        return;
      }
      if (!speaking || settled) return;
      if (latestTimings.customer_to_first_audio_ms == null && responseStartedAt) {
        updateTtsTiming({browser_first_audio_ms: performance.now() - responseStartedAt});
      }
      if (audioMimeType) {
        mediaQueue.push(message.data);
        drainMediaQueue();
        if (mediaElement && mediaElement.paused) mediaElement.play().catch(() => {});
        return;
      }
      const bytes = new Int16Array(message.data);
      const buffer = audioContext.createBuffer(1, bytes.length, 24000);
      const samples = buffer.getChannelData(0);
      for (let i = 0; i < bytes.length; i++) samples[i] = bytes[i] / 32768;
      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(audioContext.destination);
      if (callRecordingDestination) source.connect(callRecordingDestination);
      activeSources.add(source);
      pendingAudio++;
      source.onended = () => { pendingAudio--; activeSources.delete(source); maybeFinish(); };
      source.start(Math.max(playbackClock, audioContext.currentTime));
      playbackClock = Math.max(playbackClock, audioContext.currentTime) + buffer.duration;
    };
    socket.onerror = () => { if (!settled) { speaking = false; reject(new Error('Could not connect to the streaming voice service.')); } };
  socket.onclose = (event) => {
      if (activeTtsSocket === socket) activeTtsSocket = null;
      if (!speaking || event.code === 1000) {
        synthesisComplete = true;
        if (mediaElement) {
          mediaStreamComplete = true;
          endMediaStreamIfReady();
        } else maybeFinish();
      }
      else if (!synthesisComplete && !settled) { speaking = false; reject(new Error('Streaming voice connection ended unexpectedly.')); }
    };
  });
}
function resetCallRecording() {
  if (callRecordingDestination) {
    for (const track of callRecordingDestination.stream.getTracks()) track.stop();
  }
  callAudioRecorder = null;
  callAudioChunks = [];
  callAudioBlob = null;
  callRecordingDestination = audioContext.createMediaStreamDestination();
  $('downloadAudio').disabled = true;
}
function startCallRecording() {
  if (!callRecordingDestination || typeof MediaRecorder === 'undefined') return;
  const options = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? {mimeType: 'audio/webm;codecs=opus'} : {};
  const recorderForCall = new MediaRecorder(callRecordingDestination.stream, options);
  const chunksForCall = callAudioChunks;
  callAudioRecorder = recorderForCall;
  recorderForCall.ondataavailable = (event) => { if (event.data.size) chunksForCall.push(event.data); };
  recorderForCall.onstop = () => {
    if (callAudioRecorder !== recorderForCall) return;
    const type = recorderForCall.mimeType || 'audio/webm';
    callAudioBlob = new Blob(chunksForCall, {type});
    $('downloadAudio').disabled = !callAudioBlob.size;
    if (callRecordingDestination) {
      for (const track of callRecordingDestination.stream.getTracks()) track.stop();
    }
  };
  recorderForCall.start(1000);
}
function stopCallRecording() {
  if (callAudioRecorder && callAudioRecorder.state !== 'inactive') callAudioRecorder.stop();
}
function downloadCallAudio() {
  if (!callAudioBlob) return;
  const url = URL.createObjectURL(callAudioBlob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `collections-call-${new Date().toISOString().replace(/[:.]/g, '-')}.webm`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function handleApiError(response) {
  let message = `Request failed (${response.status})`;
  try {
    const result = await response.json();
    message = typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail || result);
  } catch (_) {}
  throw new Error(message);
}
function startUtterance() {
  if (!mediaStream || muted || ended || recorder) return;
  clearTimeout(identityPauseTimer);
  identityPauseTimer = null;
  // The opening is not delivered until its complete audio has played. A caller
  // speaking during the bot's opening must not be treated as a later answer.
  const startedBeforeOpening = !identityPromptDelivered;
  if (speaking) {
    botAudioInterrupted = true;
    interruptionCount++;
    stopBotAudio();
    renderMetrics();
    status('You interrupted. Listening to your response…');
  } else {
    status('Listening… pause naturally when you finish speaking.');
  }
  liveFinalText = '';
  livePartialText = '';
  liveSttConfidences = [];
  // Include recent mic frames so VAD startup latency does not clip the first
  // phoneme of a customer's utterance.
  const preRollChunks = preRollPcmChunks.map(chunk => chunk.slice(0));
  utterancePcmChunks = preRollChunks.slice();
  preRollPcmChunks = [];
  utterancePcmStartedAt = performance.now();
  liveCustomerRow = addTurn('You', 'Listening…', 'Live transcription');
  chunks = [];
  const options = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? {mimeType: 'audio/webm;codecs=opus'} : {};
  recorder = new MediaRecorder(mediaStream, options);
  recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
  recorder.onstop = async () => {
      if (liveSttSocket?.readyState === WebSocket.OPEN) {
        let finalTranscriptWait = null;
        if (voiceProvider === 'sarvam') {
          finalTranscriptWait = new Promise(resolve => {
            const timeout = setTimeout(() => {
              if (liveSttFinalResolver) liveSttFinalResolver = null;
              resolve();
            }, 1200);
            liveSttFinalResolver = () => { clearTimeout(timeout); resolve(); };
          });
        }
        liveSttSocket.send(JSON.stringify({type: 'Finalize'}));
        if (finalTranscriptWait) await finalTranscriptWait;
      }
      sttSpeechStarted = false;
    const webmBlob = new Blob(chunks, {type: recorder.mimeType || 'audio/webm'});
    const customerRow = liveCustomerRow;
    const finalTranscript = liveFinalText.trim();
    const sttConfidence = liveSttConfidences.length
      ? liveSttConfidences.reduce((sum, value) => sum + value, 0) / liveSttConfidences.length
      : null;
    const micPcmChunks = utterancePcmChunks;
    const micPcmStartedAt = speechStartedAt || utterancePcmStartedAt || performance.now();
    const micPcmEndedAt = utteranceEndedAt || performance.now();
    const customerSpeechEndedAt = micPcmEndedAt;
    utterancePcmChunks = [];
    utterancePcmStartedAt = null;
    speechStartedAt = null;
    utteranceEndedAt = null;
    const firstUtteranceText = [finalTranscript, livePartialText].filter(Boolean).join(' ').trim();
    recorder = null;
    liveCustomerRow = null;
    liveFinalText = '';
    livePartialText = '';
    liveSttConfidences = [];
    const pcmWav = micPcmChunks.length ? makePcm16Wav(micPcmChunks) : null;
    const sttBlob = pcmWav || webmBlob;
    if (sttBlob.size > 0) {
        attachMicDiagnostic(customerRow, micPcmChunks, micPcmStartedAt, micPcmEndedAt);
        const utterance = {blob: sttBlob, endedAt: customerSpeechEndedAt, customerRow, transcript: finalTranscript, sttConfidence};
      if (startedBeforeOpening) {
        if (openingPending) {
          clearTimeout(openingTimer);
          openingTimer = null;
        }
        if (!identityPromptDelivered) openingPending = true;
        const pickupAcknowledgment = isPickupAcknowledgment(firstUtteranceText);
        // A greeting or bare pickup acknowledgment (including “yes” or “okay”)
        // starts the conversation; it cannot answer an identity question that
        // the caller has not heard. Play the named opening, then wait for the
        // next utterance before sending anything to identity classification.
        const openingPlayback = !identityPromptDelivered ? playCallOpening() : Promise.resolve();
          openingPlayback.catch(error => status(error.message, true)).then(() => {
          if (!pickupAcknowledgment && !ended) sendTurn(utterance.blob, utterance.endedAt, utterance.customerRow, true, utterance.transcript, utterance.sttConfidence);
        }).catch(error => status(error.message, true));
      }
      else if (processing || queuedUtterances.length) {
        queuedUtterances.push(utterance);
        if (!processing) sendNextQueuedUtterance();
      }
      else sendTurn(utterance.blob, utterance.endedAt, utterance.customerRow, false, utterance.transcript, utterance.sttConfidence);
    }
    else {
      if (customerRow) customerRow.remove();
      if (openingPending) playCallOpening().catch(error => status(error.message, true));
      else status('Listening… speak whenever you are ready.');
    }
  };
  recorder.start(100);
  if (voiceProvider === 'sarvam') signalSarvamSpeechStart();
  if (liveSttSocket?.readyState === WebSocket.OPEN) {
    for (const pcm of preRollChunks) liveSttSocket.send(pcm);
  }
}
function signalSarvamSpeechStart() {
  if (voiceProvider !== 'sarvam' || sttSpeechStarted || !recorder || recorder.state !== 'recording') return;
  if (liveSttSocket?.readyState === WebSocket.OPEN) {
    liveSttSocket.send(JSON.stringify({type: 'SpeechStart'}));
    sttSpeechStarted = true;
  }
}
function stopUtterance() {
  if (recorder && recorder.state !== 'inactive') {
    utteranceEndedAt = performance.now();
    recorder.stop();
  }
}
function monitorMicrophone() {
  if (!analyser || ended) return;
  const samples = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(samples);
  let sum = 0;
  for (const sample of samples) { const value = (sample - 128) / 128; sum += value * value; }
  const rms = Math.sqrt(sum / samples.length);
  const now = performance.now();
  // Learn the quiet-room mic floor only between turns. A barge-in must be
  // clearly louder than that floor and remain present long enough to reject
  // keyboard taps, room noise, and brief speaker echo.
  if (!speaking && !recorder && !muted && rms < 0.065) {
    ambientNoiseRms = ambientNoiseRms * 0.985 + rms * 0.015;
  }
  const bargeInThreshold = Math.max(BARGE_IN_RMS_THRESHOLD, ambientNoiseRms * 2.4);
  const active = !muted && !ended && rms > (speaking ? bargeInThreshold : VOICE_ACTIVITY_RMS_THRESHOLD);
  {
    if (active) {
      clearTimeout(identityPauseTimer);
      identityPauseTimer = null;
      silenceStartedAt = null;
      speechFrames++;
      if (openingPending) { clearTimeout(openingTimer); openingTimer = null; }
      const requiredFrames = speaking ? BARGE_IN_START_FRAMES : VOICE_ACTIVITY_START_FRAMES;
      if (!recorder && speechFrames >= requiredFrames) { speechStartedAt = now; startUtterance(); }
    } else {
      speechFrames = 0;
      if (recorder) {
        silenceStartedAt ??= now;
        if (now - silenceStartedAt > UTTERANCE_END_SILENCE_MS) stopUtterance();
      }
    }
  }
  vadFrame = requestAnimationFrame(monitorMicrophone);
}
async function enableMicrophone() {
  preRollPcmChunks = [];
  mediaStream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
  if (!audioContext) audioContext = new AudioContext();
  await audioContext.resume();
  const source = audioContext.createMediaStreamSource(mediaStream);
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  if (callRecordingDestination) source.connect(callRecordingDestination);
  const socketScheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  liveSttSocket = new WebSocket(`${socketScheme}//${location.host}/demo/stt`);
  liveSttSocket.binaryType = 'arraybuffer';
  liveSttSocket.onmessage = receiveLiveTranscript;
  liveSttSocket.onopen = signalSarvamSpeechStart;
  liveSttSocket.onerror = () => status('Live transcript connection failed; final transcription will still be attempted.', true);
  liveSttProcessor = audioContext.createScriptProcessor(4096, 1, 1);
  liveSttSilentGain = audioContext.createGain();
  liveSttSilentGain.gain.value = 0;
  liveSttProcessor.onaudioprocess = (event) => {
    if (muted || ended) return;
    const pcm = downsampleToPcm16(event.inputBuffer.getChannelData(0), audioContext.sampleRate);
    if (!pcm.byteLength) return;
    if (!recorder || recorder.state !== 'recording') {
      preRollPcmChunks.push(pcm.slice(0));
      while (preRollPcmChunks.length > PRE_ROLL_CHUNK_COUNT) preRollPcmChunks.shift();
      return;
    }
    utterancePcmChunks.push(pcm.slice(0));
    if (liveSttSocket?.readyState === WebSocket.OPEN) liveSttSocket.send(pcm);
  };
  source.connect(liveSttProcessor);
  liveSttProcessor.connect(liveSttSilentGain);
  liveSttSilentGain.connect(audioContext.destination);
  const keepLiveStt = () => {
    if (liveSttSocket?.readyState === WebSocket.OPEN) liveSttSocket.send(JSON.stringify({type: 'KeepAlive'}));
  };
  clearInterval(window.liveSttKeepAlive);
  window.liveSttKeepAlive = setInterval(keepLiveStt, 5000);
  syncMuteControls();
  monitorMicrophone();
}
function resetMetrics() {
  latencySamples = []; latestTimings = {}; turnCount = 0; interruptionCount = 0; errorCount = 0;
  renderMetrics();
}
$('start').onclick = async () => {
  $('start').disabled = true;
  try {
    ended = true;
    processing = false;
    stopBotAudio();
    stopCallRecording();
    stopConversationMic();
    if (!audioContext) audioContext = new AudioContext();
    await audioContext.resume();
    const response = await fetch('/demo/session', {method: 'POST'});
    if (!response.ok) await handleApiError(response);
    const data = await response.json();
    resetMetrics();
    sessionId = data.session_id;
    openingText = data.opening;
    llmConfigured = data.llm_configured;
    voiceProvider = data.voice_provider || 'deepgram';
    sttSpeechStarted = false;
    resetCallRecording();
    startCallRecording();
    openingPending = true;
    identityPromptDelivered = false;
    identityDeliveryPromise = null;
    botAudioInterrupted = false;
    clearTimeout(openingTimer);
    ended = false;
    syncTestPanel();
    otpPausedMic = false;
    otpWasMuted = false;
    muted = false;
    queuedUtterances = [];
    await enableMicrophone();
    $('outcome').textContent = 'No outcome yet.';
    setOtpModule(false, 'Start a conversation to use OTP verification if needed.');
    syncMuteControls();
    $('finish').disabled = false;
    markConversationStart();
    status('Call connected. Speak whenever you are ready; the assistant will introduce itself after your greeting or a brief pause.');
    openingTimer = setTimeout(() => { playCallOpening().catch(error => status(error.message, true)); }, 2500);
  } catch (error) {
    errorCount++; renderMetrics();
    status(error.message, true);
    if (mediaStream) mediaStream.getTracks().forEach(track => track.stop());
  } finally {
    $('start').disabled = false;
    $('callAgent').disabled = false;
    syncTestPanel();
  }
};
$('mute').onclick = $('muteMain').onclick = () => {
  muted = !muted;
  if (muted) preRollPcmChunks = [];
  if (mediaStream) mediaStream.getAudioTracks().forEach(track => { track.enabled = !muted; });
  syncMuteControls();
  if (muted && recorder) stopUtterance();
  if (!muted) status('Microphone on. Listening continuously.');
  else status('Microphone muted.');
};
async function sendTurn(blob, responseStartedAt, customerRow, heardBeforeOpening = false, liveTranscript = '', sttConfidence = null) {
  if (processing || ended) return;
  processing = true;
  const requestStarted = performance.now();
  try {
    if (identityDeliveryPromise) {
      const delivered = await identityDeliveryPromise;
      if (!delivered.ok) await handleApiError(delivered);
    }
    const form = new FormData();
    const audioFilename = blob.type === 'audio/wav' ? 'customer-turn.wav' : 'customer-turn.webm';
    form.append('audio', blob, audioFilename);
    form.append('heard_before_opening', heardBeforeOpening ? 'true' : 'false');
    form.append('live_transcript', liveTranscript);
    if (Number.isFinite(sttConfidence)) form.append('stt_confidence', String(sttConfidence));
    status('Heard you. Working on a response…');
    const response = await fetch(`/demo/session/${sessionId}/turn`, {method: 'POST', body: form});
    if (!response.ok) await handleApiError(response);
    const data = await response.json();
    const result = data.response;
    const intent = result.metadata && result.metadata.intent && result.metadata.intent !== 'unclear' ? `intent: ${result.metadata.intent}` : '';
    const dialogueAct = result.metadata && result.metadata.dialogue_act;
    const understandingLabels = {
      answers_pending: 'understood: answered current question',
      cannot_provide: 'understood: cannot provide requested detail',
      asks_question: 'understood: customer asked a question',
      corrects_previous: 'understood: correcting previous answer',
      new_request: 'understood: new request'
    };
    const understanding = understandingLabels[dialogueAct] || '';
    const source = result.metadata && result.metadata.intent_source;
    const llmError = result.metadata && result.metadata.llm_error_type;
    const llmErrorDetail = result.metadata && result.metadata.llm_error_detail;
    const interpreter = llmError ? `LLM intent unavailable (${llmError}${llmErrorDetail ? `: ${llmErrorDetail}` : ''}); policy classified the turn` : source === 'local_fast_path' ? 'local fast path' : source === 'llm' ? 'LLM interpreted this turn' : 'rule fallback used';
    const replySource = result.metadata && result.metadata.reply_source;
    const replyLabel = replySource === 'llm_acknowledgment' ? 'LLM acknowledgment checked; policy response preserved' : replySource === 'policy_validator_fallback' ? 'Policy reply used; acknowledgment failed checks' : 'Policy reply';
    const identityPauseCheck = result.metadata && result.metadata.identity_pause_check === true;
    updateTurnText(customerRow, data.transcript);
    if (result.bot_text) addTurn('Bot', result.bot_text, [intent, understanding, interpreter, replyLabel].filter(Boolean).join(' · '));
    addBackendTrace(result);
    showOutcome(result);
    recordTurnMetrics(data.timings_ms || {}, performance.now() - requestStarted, responseStartedAt, result.metadata || {});
    setOtpModule(data.pending === 'otp_code');
    if (result.terminal && data.completion) $('outcome').textContent = JSON.stringify({outcome: result.outcome, delivery_status: data.completion.delivery_status}, null, 2);
    if (recorder && !result.terminal) {
      processing = false;
      status('I hear you. Go ahead; I’ll respond when you pause.');
      return;
    }
    botAudioInterrupted = false;
    if (result.bot_text) await playStreamAudio(result.bot_text);
    if (!identityPauseCheck && !botAudioInterrupted && !ended && data.pending === 'identity_confirmation') {
      identityPromptDelivered = true;
      identityDeliveryPromise = fetch(`/demo/session/${sessionId}/opening-delivered`, {method: 'POST'});
      const delivered = await identityDeliveryPromise;
      if (!delivered.ok) await handleApiError(delivered);
    }
    processing = false;
    if (queuedUtterances.length && !result.terminal) {
      sendNextQueuedUtterance();
      return;
    }
    if (identityPauseCheck && !result.terminal && !ended) {
      status('Listening. I’ll check again if there is a prolonged pause.');
      scheduleIdentityPauseCheck();
    }
    if (result.terminal) {
      ended = true;
      syncTestPanel();
      stopCallRecording();
      stopConversationMic();
      $('finish').disabled = true;
      status('Conversation complete. The structured outcome was saved.');
    } else if (!ended) {
      status(data.pending === 'otp_code'
        ? 'Microphone paused for verification. Enter the six-digit code on screen.'
        : 'Listening continuously. Speak whenever you are ready.');
    }
  } catch (error) {
    processing = false;
    errorCount++; renderMetrics();
    status(error.message, true);
  }
}
function sendNextQueuedUtterance() {
  if (processing || ended || !queuedUtterances.length) return;
  const next = queuedUtterances.shift();
  sendTurn(next.blob, next.endedAt, next.customerRow, false, next.transcript || '', next.sttConfidence ?? null);
}
function scheduleIdentityPauseCheck() {
  clearTimeout(identityPauseTimer);
  identityPauseTimer = setTimeout(async () => {
    identityPauseTimer = null;
    if (ended || muted || recorder || speaking || processing) return;
    processing = true;
    try {
      const response = await fetch(`/demo/session/${sessionId}/identity-pause-check`, {method: 'POST'});
      if (!response.ok) await handleApiError(response);
      const data = await response.json();
      if (!data.prompt || ended) return;
      addTurn('Bot', data.prompt, 'Identity check · repeated after a 3-second pause');
      botAudioInterrupted = false;
      await playStreamAudio(data.prompt);
      if (!botAudioInterrupted && !ended) {
        identityPromptDelivered = true;
        identityDeliveryPromise = fetch(`/demo/session/${sessionId}/opening-delivered`, {method: 'POST'});
        const delivered = await identityDeliveryPromise;
        if (!delivered.ok) await handleApiError(delivered);
      }
    } catch (error) {
      status(error.message, true);
    } finally {
      processing = false;
      if (!ended) status('Listening continuously. Speak whenever you are ready.');
    }
  }, IDENTITY_REMINDER_PAUSE_MS);
}
function stopConversationMic() {
  clearTimeout(openingTimer);
  clearTimeout(identityPauseTimer);
  identityPauseTimer = null;
  openingTimer = null;
  openingPending = false;
  if (vadFrame) cancelAnimationFrame(vadFrame);
  vadFrame = null;
  clearInterval(window.liveSttKeepAlive);
  if (liveSttProcessor) {
    liveSttProcessor.onaudioprocess = null;
    try { liveSttProcessor.disconnect(); } catch (_) {}
  }
  if (liveSttSilentGain) { try { liveSttSilentGain.disconnect(); } catch (_) {} }
  liveSttProcessor = null;
  liveSttSilentGain = null;
  if (liveSttSocket) { try { liveSttSocket.close(1000, 'conversation_finished'); } catch (_) {} }
  liveSttSocket = null;
  if (mediaStream) mediaStream.getTracks().forEach(track => track.stop());
  mediaStream = null;
  syncMuteControls();
}
$('downloadAudio').onclick = downloadCallAudio;
$('otp').addEventListener('input', () => {
  $('otp').value = $('otp').value.replace(/\D/g, '').slice(0, 6);
  $('verifyOtp').disabled = $('otp').disabled || $('otp').value.length !== 6;
});
$('showCode').onclick = async () => {
  try {
    const response = await fetch(`/demo/session/${sessionId}/otp-code`);
    if (!response.ok) await handleApiError(response);
    const data = await response.json();
    $('otp').value = data.code;
    $('otp').dispatchEvent(new Event('input'));
  } catch (error) { errorCount++; renderMetrics(); status(error.message, true); }
};
$('verifyOtp').onclick = async () => {
  try {
    const response = await fetch(`/demo/session/${sessionId}/otp`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code: $('otp').value})
    });
    if (!response.ok) await handleApiError(response);
    const data = await response.json();
    addTurn('Bot', data.response.bot_text, 'OTP submitted through the keypad field; it was not sent to speech recognition.');
    await playStreamAudio(data.response.bot_text);
    if (data.response.terminal && data.completion) {
      $('outcome').textContent = JSON.stringify({outcome: data.response.outcome, delivery_status: data.completion.delivery_status}, null, 2);
    } else {
      showOutcome(data.response);
    }
    setOtpModule(data.pending === 'otp_code', data.pending === 'otp_code' ? 'That code could not be verified. Check it and try again.' : 'Verification complete.');
    if (data.response.terminal) {
      ended = true;
      syncTestPanel();
      stopCallRecording();
      stopConversationMic();
      $('finish').disabled = true;
      status('Conversation complete. The structured outcome was saved.');
    } else if (data.pending !== 'otp_code') {
      status(muted ? 'Verification complete. The microphone remains muted.' : 'Verification complete. You can continue speaking.');
    }
  } catch (error) { errorCount++; renderMetrics(); status(error.message, true); }
};
$('finish').onclick = async () => {
  $('callAgent').disabled = true;
  try {
    ended = true;
    syncTestPanel();
    setOtpModule(false, 'Verification closed.');
    stopBotAudio();
    stopCallRecording();
    stopConversationMic();
    processing = false;
    const response = await fetch(`/demo/session/${sessionId}/finish`, {method: 'POST'});
    if (!response.ok) await handleApiError(response);
    const result = await response.json();
    $('finish').disabled = true;
    setOtpModule(false, 'Conversation ended.');
    $('outcome').textContent = JSON.stringify({outcome: result.outcome, delivery_status: result.delivery_status}, null, 2);
    status('Conversation ended and its outcome was saved.');
  } catch (error) { errorCount++; renderMetrics(); status(error.message, true); }
  finally { $('callAgent').disabled = false; syncTestPanel(); }
};
$('callAgent').onclick = () => {
  $('callAgent').disabled = true;
  if (ended) $('start').click();
  else $('finish').click();
};
$('showUnderHood').onclick = () => {
  $('testPanel').hidden = true;
  $('underHoodPanel').hidden = false;
  $('showUnderHood').setAttribute('aria-expanded', 'true');
  window.scrollTo(0, 0);
};
$('backToTest').onclick = () => {
  $('underHoodPanel').hidden = true;
  $('testPanel').hidden = false;
  $('showUnderHood').setAttribute('aria-expanded', 'false');
  window.scrollTo(0, 0);
};
</script>
</body>
</html>'''
