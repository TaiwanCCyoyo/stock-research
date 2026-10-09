## ADDED Requirements

### Requirement: Shutdown and heartbeat endpoints support dashboard lifecycle control

The API MUST expose `POST /shutdown` and `POST /heartbeat` so the frontend can stop the
local dashboard server explicitly or let it detect that the browser tab has closed. Both
endpoints MUST require the same `X-Requested-With` header already required by
`POST /backtests`, since no `CORSMiddleware` is configured and the API remains bound to
`127.0.0.1`.

#### Scenario: Reject shutdown/heartbeat requests without the CSRF header

- **WHEN** a client sends `POST /shutdown` or `POST /heartbeat` without the
  `X-Requested-With` header
- **THEN** the API MUST respond with 403 and MUST NOT act on the request.

#### Scenario: Heartbeat updates last-seen state

- **WHEN** a client sends `POST /heartbeat` with the required header
- **THEN** the API MUST record the current time as the most recent heartbeat.

#### Scenario: Shutdown signals the owning server process

- **WHEN** a client sends `POST /shutdown` with the required header and the API process was
  started by the production launcher (`research_api.__main__`)
- **THEN** the API MUST signal that owning server to stop gracefully
- **AND** it MUST still return a successful response when no owning server is attached
  (e.g. under a test client or the Vite-dev launcher), without raising an error.
