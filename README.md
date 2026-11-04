# Collections Voicebot

End-to-end assignment prototype for a Mumbai Bank credit-card collections voicebot. It runs in a local browser with microphone and speaker access, using separate speech recognition, language-model, and speech synthesis providers. It includes bank-service mocks for OTP verification, payment reconciliation, human follow-up/transfer routing, and contact opt-outs. It does not place telephone-network calls and has no Twilio dependency.

## End-to-end call flow

1. The local browser demo creates synthetic customer/account data and starts one account-level conversation. The authenticated service API accepts trusted eligibility/contact-policy decisions and DPD at `POST /v1/calls`.
2. The service checks the bank mock's contact preference and the configurable, versioned frequency rules before reserving an attempt.
3. The browser streams microphone PCM to the configured speech provider and displays interim transcripts. Select Deepgram (`VOICE_PROVIDER=deepgram`) or Sarvam (`VOICE_PROVIDER=sarvam`) for STT and TTS. Sarvam uses Saaras v4 realtime transcription and Bulbul v4 Flash streaming speech by default; Deepgram uses Nova-3 and Flux Naveen. A local fast path handles simple, high-confidence turns; otherwise OpenAI Responses classifies the utterance with a constrained intent/field schema and dialog state. Deterministic policy chooses the response and outcome. Switching speech providers does not change the LLM, policy, mock bank flows, or stored outcomes.
4. If balance details are requested, the bot issues a mock OTP. Enter the six-digit code in the browser keypad field; the OTP is never sent to speech recognition or the LLM. A short-lived, single-account, single-use OTP grant is required for the mock balance API.
6. A customer-reported payment is checked against the mock ledger by account/date/mode. Confirmed, pending, and unmatched states stay distinguishable in the outcome.
7. Hardship, abuse, disputes, waiver requests, and callback requests create a human-agent task. Urgent distress/abuse also creates a mock human-transfer request in the agent queue. Customer opt-out is recorded against the voice contact point and blocks subsequent attempts.
8. Final attempt dispositions and customer outcomes are saved and sent to the CRM webhook.

## Browser audio capture and turn timing

The browser captures microphone audio locally with echo cancellation, noise suppression, and automatic gain control enabled. Voice activity detection starts a turn after four active frames at the configured RMS threshold. To avoid losing the first syllable while the recorder starts, the browser continuously keeps four recent 16 kHz mono PCM frames (about 340–370 ms) and prepends them when a turn begins. This is a rolling capture buffer, not an extra wait before recording. The resulting WAV is streamed to live STT and is also used for the upload fallback when live transcription is unavailable.

After speech becomes quiet, the browser waits 800 ms before finalizing the turn. Pauses shorter than that stay within the same utterance; the pre-roll does not change first-audio latency. The transcript includes a per-turn mic-only WAV download for STT diagnosis and a separate full-call audio download. Both are assembled in the browser and are not stored on the application server.

## Structured call outcomes and webhook

Every completed call gets a persisted outcome event. Promise-to-Pay outcomes carry the confirmed date and an optional customer-provided amount in INR; after date confirmation, the bot asks for the amount and offers OTP verification to retrieve the bank-recorded minimum due. The customer can skip the amount, in which case the date is still recorded and the amount is `null`. Already-Paid outcomes carry the reported date and mode plus reconciliation status. Callback outcomes preserve the requested time, and dispute/human-review outcomes include a reason and follow-up task reference. Opt-out, waiver, and unresolved calls also receive explicit outcome types.

Set `COLLECTIONS_WEBHOOK_URL` in `.env` to send each final event to a CRM receiver. For an assignment demo, a unique webhook.site URL is sufficient. The service records delivery status and retries failed requests; with the template value left blank, the event is saved locally and reports `not_configured` rather than being sent. See [the outcome event contract](docs/system_architecture_and_business_rule_engine.md#call-outcome-and-crm-event) for fields and setup details.

## GCP deployment preparation

The repository includes a Cloud Run `Dockerfile` and a deployment checklist at [docs/gcp_cloud_run_deployment.md](docs/gcp_cloud_run_deployment.md). A live deployment is not created by this repo update: the demo requires billable Cloud SQL PostgreSQL, configured provider secrets, and a confirmed GCP region. Review the deployment guide and billing estimate before provisioning.

## Business rules and architecture

The call policy data is centralized in `src/collections_bot/business_rules.json` and loaded through `collections_bot.business_rules`. The active ruleset includes approved financial facts, payment and call thresholds, calling-frequency values, phrase cues, matching patterns, and pending-answer contracts. Set `COLLECTIONS_BUSINESS_RULES_PATH` to load a different JSON ruleset at service startup; calling-frequency environment variables can override the corresponding fields. Rule decisions include the ruleset version in their decision trace. See [the architecture and rule-engine guide](docs/system_architecture_and_business_rule_engine.md) for the complete component diagram, turn sequence, configuration keys, and safety boundaries.

## Run locally

Requires Python 3.11+. Copy `.env.example` to `.env`, set distinct service/admin tokens, then install and run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
uvicorn collections_bot.api:app --reload --app-dir src
```

For local development the default SQLite file is `./data/collections.db`. Every internal `/v1` route and mock-bank API (except health) requires a bearer token. Use `Authorization: Bearer $COLLECTIONS_API_TOKEN` for the service role and `Authorization: Bearer $MOCK_BANK_ADMIN_TOKEN` for admin-only operations. The two tokens must be different. The dev OTP-code endpoint is admin-only and returns 404 unless `APP_ENV=development`.

For Deepgram, configure `DEEPGRAM_API_KEY`; for Sarvam, set `VOICE_PROVIDER=sarvam` and configure `SARVAM_API_KEY`. The classifier supports OpenAI and Gemini behind `LLM_PROVIDER` (`openai` by default). OpenAI uses `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-6-luna`, `OPENAI_REASONING_EFFORT=none`, and `OPENAI_SERVICE_TIER=default`; `OPENAI_SERVICE_TIER=fast` selects OpenAI's premium Fast tier. To try Gemini, set `LLM_PROVIDER=gemini`, configure `GEMINI_API_KEY`, and optionally change `GEMINI_MODEL` (default `gemini-3.5-flash-lite`, a low-latency structured-output model). Both providers return the same structured intent contract; deterministic policy still selects the allowed response and enforces identity, opt-out, distress, dispute, and escalation handling. Gemini uses Google's structured JSON output mode. A live latency/quality comparison requires a Gemini API key; do not compare across different test utterances. Optional Sarvam settings are `SARVAM_STT_MODEL`, `SARVAM_STT_LANGUAGE`, `SARVAM_STT_MODE`, `SARVAM_STT_STREAM_TYPE`, `SARVAM_STT_KEYTERMS`, `SARVAM_TTS_MODEL`, and `SARVAM_TTS_SPEAKER`. The Sarvam defaults translate Hindi and other supported Indic-language speech into English text for the existing English-oriented intent classifier (`translate`, auto-detected language), use balanced streaming and v4 keyterm hints for more accurate live transcription, and use Bulbul v4 Flash persona `shubh_enhi_banking` for spoken replies. The `enhi` voice tag indicates an English–Hindi code-mixed persona, while bot replies remain in English; Hindi input recognition remains handled by Saaras STT. Provider credentials stay on the server and are not sent to the browser. The local browser demo is loopback-only; the hosted assignment demo is enabled only in `APP_ENV=demo` and requires its private-link cookie for both HTTP and WebSocket routes. Without the selected LLM provider's key the deterministic fallback remains available; without the selected speech provider's key, audio transcription and speech output are unavailable. The browser demo shows the latest and rolling-average STT, LLM, TTS first-audio, TTS completion, server API, and browser request times. Server responses include `X-Response-Time-Ms` and `Server-Timing` headers; API timing records are written to the application log without transcripts or credentials.

## Private hosted demo (Render)

`render.yaml` defines a link-gated assignment demo on Render in Singapore. It uses a synthetic mock bank and PostgreSQL, keeps the browser demo behind a high-entropy private link, and stores OpenAI and Sarvam keys as server-side secrets. The regular service URL shows only an access screen. The private access token is exchanged for a 24-hour secure, HTTP-only browser cookie; the token is removed from the address bar after access is granted. Anyone who receives the full private link can use the demo, so share it only with intended reviewers.

To deploy, upload `project-source.zip`, `render.yaml`, `.python-version`, `.gitignore`, and `README.md` to the root of a private GitHub repository, connect that repository to Render, and create a Blueprint from `render.yaml`. The build extracts the source bundle before installing the app. Render will ask for `OPENAI_API_KEY` and `SARVAM_API_KEY`; enter them in Render's secret prompt, not in this file or GitHub. After the service is live, copy the generated `DEMO_ACCESS_TOKEN` from the Render service's environment settings and share this URL format with reviewers: `https://<your-render-service>.onrender.com/#<DEMO_ACCESS_TOKEN>`. Keep the token private. Do not use real customer data or real bank credentials in this assignment demo.

This blueprint uses Render's free web service and free PostgreSQL plan to avoid provisioning charges. The web service may sleep after inactivity and take about a minute to wake; the free database expires after 30 days, so this is suitable for a temporary assignment demo rather than a production launch. Review Render's [free instance limits](https://render.com/docs/free) before relying on it for a presentation.

## Mock bank APIs

All API routes are under `/mock-bank/v1`.

| Need | Mock endpoints | Control |
|---|---|---|
| OTP and verified balance | `POST /otp/challenges`, `POST /otp/challenges/{id}/verify`, `GET /accounts/{account_id}/balance` | 5-minute challenge, five attempts, 10-minute single-use grant; balance requires `X-OTP-Verification-Token` |
| Inspect mock OTP delivery | `GET /otp/challenges/{id}/dev-code` | Development only; admin token only |
| Payment reconciliation | `POST /payments/reconcile` | Compares account, date, and payment mode with seeded mock ledger rows |
| Prepare ledger scenarios | `POST /payments` | Admin only; can seed `confirmed`, `pending`, or `reversed` payments |
| Human follow-up queue | `POST /agent-tasks`, `GET /agent-tasks`, `PATCH /agent-tasks/{id}` | Bot creates idempotent tasks; admin assigns and closes them |
| Human transfer queue | `POST /human-transfers`, `GET /human-transfers`, `PATCH /human-transfers/{id}` | Mock statuses: queued, accepted, connected, callback-required, completed, failed |
| Contact preferences / opt-out | `GET /contact-preferences/{customer_id}/{contact_point_id}`, `PUT` same path | Service may record an opt-out; only admin can revoke it |
| Audit trail | `GET /audit-events` | Admin only; records privileged reads and writes without logging OTP digits |

The seeded synthetic account is `acct-demo-001` / `cust-demo-001`. Use `contact-demo-001` as its contact-point id in the call request. Admins can seed a payment row to exercise each reconciliation state. Browser demo sessions get their own synthetic account so you can run repeated scenarios without reaching real customers. OTP values are randomly generated; the loopback-only browser demo has a development-only button to reveal the mock code. Enter it in the keypad field; it is not transcribed.

Example local OTP and balance flow (replace tokens with different random values):

```sh
curl -X POST http://localhost:8000/mock-bank/v1/otp/challenges \
  -H "Authorization: Bearer $COLLECTIONS_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"customer_id":"cust-demo-001","account_id":"acct-demo-001","contact_point_id":"contact-demo-001"}'
curl http://localhost:8000/mock-bank/v1/otp/challenges/CHALLENGE_ID/dev-code \
  -H "Authorization: Bearer $MOCK_BANK_ADMIN_TOKEN"
curl -X POST http://localhost:8000/mock-bank/v1/otp/challenges/CHALLENGE_ID/verify \
  -H "Authorization: Bearer $COLLECTIONS_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"code":"123456"}'
curl http://localhost:8000/mock-bank/v1/accounts/acct-demo-001/balance \
  -H "Authorization: Bearer $COLLECTIONS_API_TOKEN" -H 'X-OTP-Verification-Token: VERIFICATION_TOKEN'
```

The code above illustrates the flow; use the actual challenge ID and code returned by the mock endpoints. A verification token is account-bound, expires after ten minutes, and is consumed by the balance read.

The mock transfer endpoint queues a human request and tracks agent-side status; it does not bridge to a real agent. A real bank deployment must replace it with the bank's contact-center/agent-desktop transfer API.

## Local storage and production controls

- Set `COLLECTIONS_DATABASE_URL` to a PostgreSQL connection string to use the pooled PostgreSQL storage adapter. PostgreSQL URLs default to `sslmode=verify-full`; the pool is bounded and closed at service shutdown. SQLite remains the local development default.
- PostgreSQL customer-level advisory transaction locks serialize call-frequency reservations across app workers and replicas; local SQLite uses a write transaction for the same purpose.
- `APP_ENV=production` refuses SQLite and refuses static bearer tokens. Configure `AUTH_MODE=oidc`, `OIDC_ISSUER`, `OIDC_AUDIENCE`, and `OIDC_JWKS_URL`. JWT signature, issuer, audience, expiry, issued-at, and subject are validated. The token's `roles` claim must include `collections-service` or `mock-bank-admin`.
- SQL statements use bound parameters. The browser demo is available locally only from loopback in development; the `APP_ENV=demo` deployment requires the private access link for both HTTP and WebSocket demo routes. Uploaded audio is forwarded to the selected speech provider for transcription and is not persisted by this application. Provider credentials remain on the server.
- Mock operations write audit events. OTP digits are stored as a salted-by-challenge hash; the plaintext test delivery is retained only in the mock delivery sink and is readable only in development with admin access. OTP values are never stored in call sessions or sent to STT/LLM.
- The production DB service must enforce encrypted storage/backups, network allow-lists, least-privilege DB credentials, backup retention, and disaster recovery. This prototype creates tables on startup; production schema changes should move to reviewed, versioned migrations before launch, with the runtime DB identity granted only the access it needs.

Static bearer tokens are for the assignment/local demo. Production OIDC roles still need to be mapped to the bank's workload identity and agent identity provider. The mock-bank data itself must not be used for real customers.

## Assignment call example

Use the synthetic account above. `eligibility_confirmed` and `contact_allowed` are inputs from trusted bank systems, not decisions made by the bot.

```json
{
  "case_id": "case-demo-001",
  "episode_id": "dpd-episode-demo-001",
  "customer_id": "cust-demo-001",
  "account_id": "acct-demo-001",
  "contact_point_id": "contact-demo-001",
  "timezone": "Asia/Kolkata",
  "first_name": "Asha",
  "days_past_due": 8,
  "masked_account_reference": "****1234",
  "eligibility_confirmed": true,
  "contact_allowed": true,
  "contact_policy_version": "bank-approved-version"
}
```

Submit text turns to `POST /v1/calls/{session_id}/turn`; the endpoint uses the LLM for constrained intent and field extraction before applying deterministic policy. Verify an OTP at `POST /v1/calls/{session_id}/otp`, close the interaction at `/complete`, and inspect attempts/outcomes at `GET /v1/cases/{case_id}/history`. For speech, use the local browser demo at `/`.

## Scope still needing real bank/provider adapters

- Real SMS/OTP delivery, bank account/billing APIs, ledger reconciliation, and payment status feed.
- Actual phone-network calling, contact-center bridging, an agent desktop, and agent SLA/work-allocation behavior. The assignment asks for the transfer outcome, not a live transfer bridge.
- Contact preference propagation across all campaigns/channels, local rules, and bank legal/compliance sign-off.
- Production database migrations, retention/deletion workflows, operational monitoring, and security/load review.
- Voicemail detection, DTMF-based identity flows beyond OTP, localized Hindi responses, and sentiment monitoring. Sentiment remains non-authoritative and is not used to change contact frequency.
- Reduce LLM classification latency further: `gpt-6-luna` with reasoning effort `none` averaged 1.73 seconds over 25 synthetic text turns. Validate p95 latency and accuracy on real browser audio/transcripts, then benchmark safe deterministic fast paths and provider/network timing.

Calling windows, frequency limits, scripts, recording/retention, and escalation procedures must be approved by bank compliance/legal teams. The sample policy values are development settings, not a compliance determination.
