# FleetManager Agent API

The agent API is mounted under `/agent`.

1. An admin creates an enrollment token with `POST /agent/enrollment-tokens` using the normal user JWT. The raw token is returned once.
2. The Windows agent sends that token to `POST /agent/register`. Registration creates or attaches a host and returns an agent bearer token.
3. The agent uses the bearer token for `POST /agent/heartbeat`, `POST /agent/alerts`, and `POST /agent/offline`.
4. Admins and operators can inspect an agent with `GET /agent/status/{agent_id}`.

Enrollment tokens and agent bearer tokens are stored only as SHA-256 hashes. A heartbeat replaces the host's software inventory atomically and updates the host's online/last-seen fields. Unknown software sources are stored as `other`.

## Agent version and remote update

The installed agent version is kept in `hosts.agent_version` and shown in the host registry. It is filled from three sources, so old agents are covered too:

- `agent_version` in `POST /agent/register` and `POST /agent/heartbeat` — reported by agents built from the current source;
- the software inventory of the same heartbeat — Inno Setup registers an uninstall entry named `FleetManager Agent`, so the version is recovered even from agents that do not send the field;
- `POST /agent/version-scan` — reads `DisplayVersion` of that uninstall entry over SSH, which also works when the agent service is not running.

The available version is the GitHub release tag of the installer in `soft_share_dir`, written by `services/agent_installer_sync.py` into `FleetManagerAgent-Setup.exe.version`. Versions are compared numerically, so `2025.08.09.9 < 2025.08.09.10`.

| Endpoint | Role | Purpose |
| --- | --- | --- |
| `GET /agent/versions` | any authenticated user | available version + per-host installed version and status (`up_to_date` / `outdated` / `newer` / `unknown`) |
| `POST /agent/version-scan` | admin, operator | queue an SSH probe of the installed version; empty `host_ids` means every host with an agent |
| `POST /agent/update` | admin, operator | queue a remote update of the selected hosts |
| `GET /agent/installer` | agent bearer token | download the installer; used by hosts during the update |

`POST /agent/update` and `POST /agent/version-scan` create a `TaskRun` (`agent_update` / `agent_version_scan`) and return it, so progress is streamed through the usual `/tasks/{id}/stream`.

The update itself (`services/agent_update.py`) runs over the existing SSH/`ansible.builtin.raw` channel and deliberately makes the host pull the installer itself: the host reads `ServerUrl` and `AgentToken` from its own `C:\ProgramData\FleetManagerAgent\agent.json`, downloads `GET /api/agent/installer` with that token and runs the installer silently. No server-side secret is sent to the host, and the installer keeps the existing registration (see the upgrade mode in `installer/FleetManagerAgent.iss` of FleetManager-Agent), so no new enrollment token, agent token or SSH key is issued.
