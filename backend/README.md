# FleetManager Agent API

The agent API is mounted under `/agent`.

1. An admin creates an enrollment token with `POST /agent/enrollment-tokens` using the normal user JWT. The raw token is returned once.
2. The Windows agent sends that token to `POST /agent/register`. Registration creates or attaches a host and returns an agent bearer token.
3. The agent uses the bearer token for `POST /agent/heartbeat`, `POST /agent/alerts`, and `POST /agent/offline`.
4. Admins and operators can inspect an agent with `GET /agent/status/{agent_id}`.

Enrollment tokens and agent bearer tokens are stored only as SHA-256 hashes. A heartbeat replaces the host's software inventory atomically and updates the host's online/last-seen fields. Unknown software sources are stored as `other`.
