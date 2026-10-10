// Мок API для локальной разработки интерфейса: `npm run dev:mock`.
// Повторяет контракт backend (FastAPI) на ~1000 сгенерированных хостах.
// Состояние хранится в памяти и сбрасывается при перезапуске dev-сервера.
// Вход: любой пароль; роль задаёт имя пользователя — admin, operator или viewer.
import type { Plugin } from "vite";
import type { IncomingMessage, ServerResponse } from "node:http";

// ---------- детерминированный генератор ----------
let seed = 20261010;
function rnd() {
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
const pick = <T,>(items: T[]) => items[Math.floor(rnd() * items.length)];
const chance = (p: number) => rnd() < p;
let uuidCounter = 0;
function uuid() {
  uuidCounter += 1;
  const hex = (uuidCounter.toString(16) + Math.floor(rnd() * 0xffffffff).toString(16)).padStart(32, "0").slice(-32);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}
const now = () => new Date();
const minutesAgo = (m: number) => new Date(Date.now() - m * 60000).toISOString();

// ---------- данные ----------
interface Group { id: string; name: string; description: string | null; credential_id: string | null; parent_id: string | null; is_auto: boolean }
interface Host {
  id: string; ip_address: string | null; hostname: string | null; group_id: string | null; os: string; status: string;
  last_checked_at: string | null; comment: string | null; credential_id: string | null; has_agent: boolean;
  agent_version: string | null; agent_version_checked_at: string | null; last_seen_at: string | null;
  hw_manufacturer: string | null; hw_model: string | null; hw_serial_number: string | null; hw_os_caption: string | null;
  hw_processor: string | null; hw_total_memory_bytes: number | null; created_at: string; updated_at: string;
}
interface Credential { id: string; name: string; type: string; login: string | null; created_at: string; is_agent_managed: boolean }
interface Software { id: string; host_id: string; name: string; version: string | null; install_method: string; status: string; detected_at: string }
interface Task {
  id: string; task_type: string; playbook_name: string | null; host_ids: string[]; status: string; created_at: string;
  started_at: string | null; finished_at: string | null; created_by: string | null; log_output: string | null;
  extra_vars: Record<string, unknown> | null; _plan?: string[]; _fail?: boolean;
}
interface Schedule {
  id: string; repo_id: string; playbook_name: string; host_group_id: string | null; host_group_ids: string[];
  host_ids: string[]; extra_vars: Record<string, unknown>; cron_expression: string; enabled: boolean; created_at: string;
}

const AVAILABLE_AGENT = "2026.10.10.9";
const users = [
  { id: uuid(), username: "admin", email: "admin@urfu.ru", role: "admin", totp_enabled: true, is_active: true },
  { id: uuid(), username: "operator", email: "operator@urfu.ru", role: "operator", totp_enabled: true, is_active: true },
  { id: uuid(), username: "viewer", email: "viewer@urfu.ru", role: "viewer", totp_enabled: false, is_active: true },
];

const groups: Group[] = [];
const hosts: Host[] = [];
const credentials: Credential[] = [];
const software: Software[] = [];
const tasks: Task[] = [];
const schedules: Schedule[] = [];
const alerts: any[] = [];
const history: any[] = [];

const manualCreds = [
  { name: "Локальный админ (лаборатории)", type: "password", login: "labadmin" },
  { name: "Доменный сервисный аккаунт", type: "password", login: "AT\\svc-fleet" },
  { name: "Deploy key GitLab", type: "ssh_key", login: "git" },
  { name: "Токен GitHub (releases)", type: "token", login: null },
];
for (const c of manualCreds) credentials.push({ id: uuid(), ...c, created_at: minutesAgo(60 * 24 * 90), is_agent_managed: false });

function addGroup(name: string, parent: string | null, isAuto = true, description: string | null = null) {
  const g: Group = { id: uuid(), name, description, credential_id: null, parent_id: parent, is_auto: isAuto };
  groups.push(g);
  return g;
}

const HW = [
  { m: "Micro-Star International Co., Ltd.", model: "Modern ADL-P AM272 (MS-AF82)", cpu: "12th Gen Intel(R) Core(TM) i7-1260P", ram: 16 },
  { m: "ASRock", model: "B760 Pro RS/D4", cpu: "12th Gen Intel(R) Core(TM) i7-12700F", ram: 32 },
  { m: "Micro-Star International Co., Ltd.", model: "MS-7D98", cpu: "Intel(R) Core(TM) i7-14700F", ram: 32 },
  { m: "Lenovo", model: "ThinkCentre M70q Gen 3", cpu: "12th Gen Intel(R) Core(TM) i5-12400T", ram: 16 },
  { m: "HP", model: "ProDesk 400 G7 SFF", cpu: "Intel(R) Core(TM) i5-10500", ram: 8 },
];

const SOFTWARE_POOL: [string, string[], number][] = [
  ["7-Zip 24.07 (x64)", ["24.07"], 0.95], ["Yandex Browser", ["25.8.1.842", "25.6.0.2370"], 0.97], ["Python 3.12.6 Core Interpreter (64-bit)", ["3.12.6150.0"], 0.8],
  ["Python Launcher", ["3.12.6150.0"], 0.9], ["Adobe Acrobat Reader DC", ["25.001.20756", "24.005.20320"], 0.85], ["Google Chrome", ["141.0.7390.55", "140.0.7339.128"], 0.6],
  ["Mozilla Firefox (x64 ru)", ["143.0.4"], 0.4], ["Visual Studio Code", ["1.104.3", "1.103.2"], 0.55], ["Git", ["2.51.0"], 0.5], ["Notepad++ (64-bit x64)", ["8.8.5"], 0.6],
  ["OpenSSH", ["9.8.3.0"], 0.95], ["WinDjView 2.1", ["2.1"], 0.9], ["Zoom Workplace", ["6.5.12"], 0.3], ["VLC media player", ["3.0.21"], 0.5],
  ["JetBrains PyCharm Community Edition", ["2025.2.1"], 0.25], ["IntelliJ IDEA Community Edition", ["2025.2.1"], 0.2], ["MATLAB Runtime R2021a", ["9.10"], 0.1],
  ["KOMPAS-3D v23", ["23.0.0.7"], 0.15], ["Docker Desktop", ["4.46.0"], 0.12], ["Oracle VirtualBox", ["7.2.2"], 0.18], ["Wireshark 4.4.9 x64", ["4.4.9"], 0.2],
  ["GIMP 3.0.4", ["3.0.4"], 0.2], ["Inkscape", ["1.4.2"], 0.15], ["Microsoft Visual C++ 2015-2022 Redistributable (x64)", ["14.44.35211.0"], 0.99],
  ["Microsoft Edge", ["141.0.3537.57"], 0.99], ["Microsoft .NET Runtime - 8.0.20 (x64)", ["8.0.20"], 0.9], ["Windows PC Health Check", ["3.6.2204.08001"], 0.7],
  ["Microsoft.VCLibs.140.00", ["14.0.33519.0"], 0.99], ["Microsoft.UI.Xaml.2.8", ["8.2501.31001.0"], 0.99], ["1527c705-839a-4832-9118-54d4bd6a0c89", ["10.0.19640.1000"], 0.9],
  ["Update for Windows 10 for x64-based Systems (KB5001716)", ["8.94.0.0"], 0.6], ["Termidesk Client", ["5.1.2"], 0.35], ["FleetManager Agent", [AVAILABLE_AGENT], 0],
  ["Veyon", ["4.9.7"], 0.4], ["Safe Exam Browser", ["3.10.0"], 0.12], ["1C:Enterprise 8 (thin client)", ["8.3.25.1445"], 0.1], ["PuTTY release 0.83 (64-bit)", ["0.83"], 0.3],
];

const BUILDINGS: [string, number[]][] = [["MR32", [0, 1, 2, 3, 4, 5]], ["SU5", [1, 2, 3]], ["GUK", [1, 2, 3, 4]], ["RTF", [1, 2, 3]]];
let ipCounter = 0;
function makeHost(hostname: string, groupId: string | null): Host {
  ipCounter += 1;
  const hw = pick(HW);
  const hasAgent = chance(0.92);
  const status = chance(0.42) ? "online" : chance(0.92) ? "offline" : "unknown";
  const versionRoll = rnd();
  const agentVersion = !hasAgent ? null : versionRoll < 0.55 ? AVAILABLE_AGENT : versionRoll < 0.75 ? "2026.08.14.5" : versionRoll < 0.8 ? "2026.09.30.2" : null;
  const created = minutesAgo(60 * 24 * (20 + Math.floor(rnd() * 200)));
  const host: Host = {
    id: uuid(), hostname, ip_address: `10.40.${100 + Math.floor(ipCounter / 250)}.${(ipCounter % 250) + 1}`, group_id: groupId,
    os: chance(0.6) ? "windows_11" : "windows_10", status, last_checked_at: chance(0.03) ? null : minutesAgo(Math.floor(rnd() * (chance(0.05) ? 60 * 24 * 12 : 90))),
    comment: chance(0.04) ? pick(["Преподавательский ПК", "Проектор подключён по HDMI", "Не выключать — стенд"]) : null,
    credential_id: null, has_agent: hasAgent, agent_version: agentVersion, agent_version_checked_at: hasAgent ? minutesAgo(Math.floor(rnd() * 600)) : null,
    last_seen_at: hasAgent ? minutesAgo(status === "online" ? Math.floor(rnd() * 5) : 60 * Math.floor(1 + rnd() * 200)) : null,
    hw_manufacturer: hasAgent ? hw.m : null, hw_model: hasAgent ? hw.model : null,
    hw_serial_number: hasAgent ? (chance(0.3) ? "To Be Filled By O.E.M." : `SN${Math.floor(rnd() * 1e10)}`) : null,
    hw_os_caption: hasAgent ? (chance(0.6) ? "Microsoft Windows 11 Enterprise" : "Майкрософт Windows 10 Корпоративная") : null,
    hw_processor: hasAgent ? hw.cpu : null, hw_total_memory_bytes: hasAgent ? hw.ram * 1024 ** 3 : null,
    created_at: created, updated_at: created,
  };
  if (hasAgent) {
    const cred: Credential = { id: uuid(), name: `Agent SSH — ${hostname}`, type: "ssh_key", login: "fleetagent", created_at: created, is_agent_managed: true };
    credentials.push(cred);
    host.credential_id = cred.id;
    for (const [name, versions, p] of SOFTWARE_POOL) {
      if (name === "FleetManager Agent" ? !agentVersion : !chance(p)) continue;
      software.push({ id: uuid(), host_id: host.id, name, version: name === "FleetManager Agent" ? agentVersion : pick(versions), install_method: pick(["msi", "msi", "winget", "other"]), status: "installed", detected_at: minutesAgo(Math.floor(rnd() * 60 * 24 * 5)) });
    }
  }
  hosts.push(host);
  return host;
}

for (const [building, floors] of BUILDINGS) {
  const b = addGroup(building, null);
  for (const floor of floors) {
    const f = addGroup(`${floor} этаж`, b.id);
    const rooms = 2 + Math.floor(rnd() * 5);
    for (let r = 0; r < rooms; r++) {
      const room = `${floor}${String(r * 3 + 1 + Math.floor(rnd() * 3)).padStart(2, "0")}`;
      if (groups.some((g) => g.name === `${building}-${room}`)) continue;
      const roomGroup = addGroup(`${building}-${room}`, f.id);
      const pcs = 8 + Math.floor(rnd() * 22);
      for (let n = 1; n <= pcs; n++) makeHost(`${building}-${room}-${String(n).padStart(2, "0")}`, roomGroup.id);
    }
  }
}
const teachers = addGroup("Преподаватели", null, false, "ПК преподавателей, собраны вручную");
hosts.filter((h) => h.hostname?.endsWith("-01")).slice(0, 12).forEach((h) => (h.group_id = teachers.id));
for (let i = 0; i < 14; i++) makeHost(chance(0.5) ? `DESKTOP-${Math.floor(rnd() * 1e7).toString(36).toUpperCase()}` : `WIN10-VDI${String(i).padStart(3, "0")}`, null);
// Ключи агентов, оставшиеся после перерегистрации ПК: ни к чему не привязаны
for (let i = 0; i < 18; i++) credentials.push({ id: uuid(), name: `Agent SSH — ${pick(hosts).hostname}`, type: "ssh_key", login: "fleetagent", created_at: minutesAgo(60 * 24 * 60), is_agent_managed: true });
groups.find((g) => g.name === "MR32")!.credential_id = credentials[0].id;

for (let i = 0; i < 25; i++) {
  const h = pick(hosts.filter((x) => x.has_agent));
  alerts.push({ id: uuid(), host_id: h.id, alert_type: "hardware_changed", message: "Изменилась конфигурация оборудования: объём памяти 16 ГБ → 8 ГБ", previous_fingerprint: "a1", current_fingerprint: "b2", created_at: minutesAgo(Math.floor(rnd() * 60 * 24 * 10)) });
}
for (let i = 0; i < 30; i++) {
  const s = pick(software);
  history.push({ id: uuid(), host_id: s.host_id, name: s.name, old_version: "1.0", new_version: s.version, change_type: pick(["installed", "updated", "removed"]), changed_at: minutesAgo(i * 47) });
}

const repo = { id: uuid(), name: "Playbooks", git_url: "git@github.com:kozlov174/RTF_OOD_AnsiblePlaybooks.git", credential_id: credentials[2].id, branch: "main", created_at: minutesAgo(60 * 24 * 100) };
const repos = [repo];
const INSTALL = ["7zip", "chrome", "firefox", "vscode", "git", "python", "putty", "vlc", "zoom", "gimp", "inkscape", "docker_desktop", "virtualbox", "wireshark", "pycharm", "idea", "kompas3d", "matlab_runtime_2021a", "termidesk_client", "veyon", "seb", "1c_edu", "notepadpp", "nodejs", "obs", "anaconda", "blender", "qgis", "rstudio", "android_studio"];
const playbookFiles = [
  { name: "install_all_software.yml", path: "playbooks/install_all_software.yml", display_name: "Установка базового набора ПО" },
  { name: "check_disk_space.yml", path: "playbooks/check_disk_space.yml", display_name: "Свободное место на дисках" },
  { name: "shutdown_hosts.yml", path: "playbooks/shutdown_hosts.yml", display_name: "Выключение хостов" },
  { name: "site.yml", path: "playbooks/site.yml", display_name: null },
  { name: "check_software.yml", path: "playbooks/check/check_software.yml", display_name: "Check installed software" },
  { name: "ping_ad3_playbook.yaml", path: "playbooks/diagnose/ping_ad3_playbook.yaml", display_name: "Ping host 10.40.240.3" },
  { name: "delete_readerDC.yaml", path: "playbooks/remove/delete_readerDC.yaml", display_name: "Uninstall Adobe Acrobat DC" },
  ...INSTALL.map((n) => ({ name: `install_${n}.yml`, path: `playbooks/install/install_${n}.yml`, display_name: `Install ${n.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}` })),
];

const installers = [
  { name: "FleetManagerAgent-Setup.exe", size: 18_400_000, mtime: minutesAgo(300) },
  { name: "FleetManagerAgent-Setup.exe.version", size: 12, mtime: minutesAgo(300) },
  ...["7z2407-x64.exe", "ChromeSetup.exe", "VSCodeSetup-x64-1.104.3.exe", "Git-2.51.0-64-bit.exe", "python-3.13.7-amd64.exe", "vlc-3.0.21-win64.exe", "kompas3d-v23.exe", "termidesk-5.1.2.msi", "veyon-4.9.7-win64-setup.exe", "MATLAB_Runtime_R2021a_Update_8_win64.zip"].map((name, i) => ({ name, size: Math.floor(5e6 + rnd() * 2e9), mtime: minutesAgo(60 * 24 * (i + 3)) })),
];
const tokens = [
  { id: uuid(), name: "NVK-SU5", expires_at: null, is_active: true, created_at: minutesAgo(60 * 24 * 40), installer_available: true },
  { id: uuid(), name: "P-411-autoinstall", expires_at: null, is_active: true, created_at: minutesAgo(60 * 24 * 20), installer_available: true },
  ...Array.from({ length: 12 }, (_, i) => ({ id: uuid(), name: `Testing${i + 1}`, expires_at: null, is_active: false, created_at: minutesAgo(60 * 24 * (50 + i)), installer_available: false })),
];

schedules.push({ id: uuid(), repo_id: repo.id, playbook_name: "playbooks/check_disk_space.yml", host_group_id: null, host_group_ids: [groups[0].id], host_ids: [], extra_vars: {}, cron_expression: "0 3 * * 1", enabled: true, created_at: minutesAgo(60 * 24 * 7) });
schedules.push({ id: uuid(), repo_id: repo.id, playbook_name: "playbooks/shutdown_hosts.yml", host_group_id: null, host_group_ids: [groups.find((g) => g.name === "SU5")!.id], host_ids: [], extra_vars: { delay: "60" }, cron_expression: "30 21 * * *", enabled: false, created_at: minutesAgo(60 * 24 * 3) });

// История задач
const TYPES = ["playbook", "playbook", "playbook", "host_diagnostic", "host_diagnostic", "software_scan", "agent_update", "agent_version_scan"];
for (let i = 0; i < 260; i++) {
  const type = pick(TYPES);
  const created = minutesAgo(i * 37 + Math.floor(rnd() * 30));
  const targets = type === "host_diagnostic" ? [pick(hosts).id] : hosts.filter(() => chance(0.03)).map((h) => h.id);
  const failed = chance(0.2);
  tasks.push({
    id: uuid(), task_type: type, playbook_name: type === "playbook" ? pick(playbookFiles).path : null, host_ids: targets, status: failed ? "failed" : "success",
    created_at: created, started_at: created, finished_at: new Date(new Date(created).getTime() + 1000 * (20 + rnd() * 600)).toISOString(),
    created_by: chance(0.15) ? null : pick(users.slice(0, 2)).id, log_output: `PLAY [all] ****\n\nTASK [Gathering Facts] ****\nok: [${targets.length} host(s)]\n\nPLAY RECAP ****\n${failed ? "failed=1" : "ok=3 changed=1"}\n`, extra_vars: {},
  });
}

// ---------- помощники ----------
const hostById = (id: string) => hosts.find((h) => h.id === id);
function descendants(ids: string[]) {
  const result = new Set<string>();
  const stack = [...ids];
  while (stack.length) {
    const id = stack.pop()!;
    if (result.has(id)) continue;
    result.add(id);
    groups.filter((g) => g.parent_id === id).forEach((g) => stack.push(g.id));
  }
  return result;
}
function resolveTargets(hostIds: string[] = [], groupIds: string[] = []) {
  const set = descendants(groupIds);
  return [...new Set([...hostIds, ...hosts.filter((h) => h.group_id && set.has(h.group_id)).map((h) => h.id)])];
}
function versionStatus(h: Host) {
  if (!h.has_agent) return "no_agent";
  if (!h.agent_version) return "unknown";
  if (h.agent_version === AVAILABLE_AGENT) return "up_to_date";
  return h.agent_version < AVAILABLE_AGENT ? "outdated" : "newer";
}
const SYSTEM = [/^microsoft[ .]/i, /^windows[ .]/i, /^update for /i, /^kb/i, /^[0-9a-f]{8}-[0-9a-f]{4}-/i, /visual c\+\+/i, /^\.net/i];
const isSystem = (name: string) => SYSTEM.some((r) => r.test(name));

function startTask(type: string, hostIds: string[], userId: string | null, extra: Partial<Task> = {}) {
  const fail = chance(0.25);
  const names = hostIds.slice(0, 40).map((id) => hostById(id)?.hostname ?? id);
  const plan = [
    `PLAY [${extra.playbook_name ?? type}] *****************************************************\n\n`,
    "TASK [Gathering Facts] *******************************************************\n",
    ...names.map((n) => (hostById(hosts.find((h) => h.hostname === n)?.id ?? "")?.status === "online" ? `ok: [${n}]\n` : `fatal: [${n}]: UNREACHABLE! => {"msg": "Failed to connect to the host via ssh"}\n`)),
    "\nTASK [Выполнение] ***********************************************************\n",
    ...names.map((n) => `changed: [${n}]\n`),
    `\nPLAY RECAP *******************************************************************\n${fail ? "есть ошибки: failed=1\n" : "ok\n"}`,
  ];
  const task: Task = {
    id: uuid(), task_type: type, playbook_name: null, host_ids: hostIds, status: "queued", created_at: now().toISOString(), started_at: null,
    finished_at: null, created_by: userId, log_output: "", extra_vars: {}, _plan: plan, _fail: fail, ...extra,
  };
  tasks.unshift(task);
  let step = 0;
  const timer = setInterval(() => {
    if (task.status === "queued") { task.status = "running"; task.started_at = now().toISOString(); return; }
    if (step < plan.length) { task.log_output += plan[step]; step += 1; return; }
    task.status = fail ? "failed" : "success";
    task.finished_at = now().toISOString();
    if (type === "agent_update" && !fail) hostIds.forEach((id) => { const h = hostById(id); if (h) h.agent_version = AVAILABLE_AGENT; });
    clearInterval(timer);
  }, 450);
  return task;
}
function taskOut(t: Task) {
  const { _plan, _fail, log_output, extra_vars, ...rest } = t;
  return { ...rest, created_by_name: users.find((u) => u.id === t.created_by)?.username ?? null };
}
function scheduleOut(s: Schedule) {
  const next = new Date(Date.now() + 3600_000 * (2 + Math.floor(rnd() * 20)));
  next.setMinutes(0, 0, 0);
  return { ...s, next_run_at: s.enabled ? next.toISOString() : null };
}
function credentialOut(c: Credential) {
  return {
    ...c,
    host_count: hosts.filter((h) => h.credential_id === c.id).length,
    group_count: groups.filter((g) => g.credential_id === c.id).length,
    repo_count: repos.filter((r) => r.credential_id === c.id).length,
  };
}

// ---------- HTTP ----------
class HttpError extends Error { constructor(public status: number, message: string) { super(message); } }
type Ctx = { method: string; path: string; query: URLSearchParams; body: any; user: (typeof users)[number] | null; res: ServerResponse };
type Handler = (ctx: Ctx, params: Record<string, string>) => unknown;
const routes: { method: string; pattern: RegExp; keys: string[]; handler: Handler; auth: boolean }[] = [];
function route(method: string, path: string, handler: Handler, auth = true) {
  const keys: string[] = [];
  const pattern = new RegExp("^" + path.replace(/\{(\w+)\}/g, (_, k) => { keys.push(k); return "([^/]+)"; }) + "$");
  routes.push({ method, pattern, keys, handler, auth });
}
const editor = (ctx: Ctx) => { if (!ctx.user || ctx.user.role === "viewer") throw new HttpError(403, "insufficient permissions"); };
const admin = (ctx: Ctx) => { if (ctx.user?.role !== "admin") throw new HttpError(403, "insufficient permissions"); };
const find = <T extends { id: string }>(items: T[], id: string, what = "Объект") => { const item = items.find((i) => i.id === id); if (!item) throw new HttpError(404, `${what} не найден`); return item; };

// auth
route("POST", "/auth/login", ({ body }) => {
  const user = users.find((u) => u.username === body.username) ?? users[0];
  return { status: "ok", access_token: `mock-${user.username}`, refresh_token: `mock-${user.username}`, token_type: "bearer" };
}, false);
route("POST", "/auth/refresh", ({ body }) => ({ access_token: body.refresh_token, refresh_token: body.refresh_token, token_type: "bearer" }), false);
route("GET", "/auth/me", ({ user }) => user);
route("POST", "/auth/totp/reset/{id}", (ctx, p) => { admin(ctx); const u = find(users, p.id, "Пользователь"); u.totp_enabled = false; return { detail: "TOTP сброшен" }; });
route("GET", "/users", (ctx) => { admin(ctx); return users; });
route("PATCH", "/users/{id}/role", (ctx, p) => { admin(ctx); const u = find(users, p.id, "Пользователь"); u.role = ctx.body.role; return u; });

// hosts
route("GET", "/hosts", () => hosts);
route("GET", "/hosts/groups", () => groups);
route("GET", "/hosts/inventory", () => hosts.map((h) => `${h.hostname} ansible_host=${h.ip_address}`).join("\n"));
route("POST", "/hosts/groups", (ctx) => { editor(ctx); return addGroup(ctx.body.name, ctx.body.parent_id ?? null, false, ctx.body.description ?? null); });
route("PATCH", "/hosts/groups/{id}", (ctx, p) => {
  editor(ctx);
  const g = find(groups, p.id, "Группа");
  if ("name" in ctx.body && g.is_auto) throw new HttpError(400, "Автоматическую группу переименовать нельзя: имя задаёт схема имён ПК");
  Object.assign(g, ctx.body);
  return g;
});
route("DELETE", "/hosts/groups/{id}", (ctx, p) => {
  editor(ctx);
  const g = find(groups, p.id, "Группа");
  if (g.is_auto) throw new HttpError(400, "Автоматическую группу удалить нельзя");
  hosts.forEach((h) => { if (h.group_id === g.id) h.group_id = null; });
  groups.forEach((c) => { if (c.parent_id === g.id) c.parent_id = null; });
  groups.splice(groups.indexOf(g), 1);
  return null;
});
route("POST", "/hosts/groups/assign", (ctx) => {
  editor(ctx);
  const g = ctx.body.group_id ? find(groups, ctx.body.group_id, "Группа") : groups.find((x) => x.name === ctx.body.group_name) ?? addGroup(ctx.body.group_name, null, false);
  ctx.body.host_ids.forEach((id: string) => { const h = hostById(id); if (h) h.group_id = g.id; });
  return g;
});
route("POST", "/hosts/groups/unassign", (ctx) => { editor(ctx); ctx.body.host_ids.forEach((id: string) => { const h = hostById(id); if (h) h.group_id = null; }); return { unassigned: ctx.body.host_ids.length }; });
route("POST", "/hosts", (ctx) => { editor(ctx); const h = makeHost(ctx.body.hostname || ctx.body.ip_address, ctx.body.group_id); Object.assign(h, { ...ctx.body, has_agent: false, status: "unknown", agent_version: null }); return h; });
route("PATCH", "/hosts/{id}", (ctx, p) => { editor(ctx); const h = find(hosts, p.id, "Хост"); Object.assign(h, ctx.body, { updated_at: now().toISOString() }); return h; });
route("DELETE", "/hosts/{id}", (ctx, p) => { editor(ctx); hosts.splice(hosts.indexOf(find(hosts, p.id, "Хост")), 1); return null; });
route("POST", "/hosts/delete", (ctx) => { editor(ctx); const ids = new Set(ctx.body.host_ids); const before = hosts.length; for (let i = hosts.length - 1; i >= 0; i--) if (ids.has(hosts[i].id)) hosts.splice(i, 1); return { deleted: before - hosts.length }; });
route("POST", "/hosts/import-csv", (ctx) => { editor(ctx); return { created: 0, skipped: 0, errors: ["Импорт CSV в мок-режиме не поддерживается"] }; });
route("POST", "/hosts/{id}/diagnostics", (ctx, p) => { editor(ctx); find(hosts, p.id, "Хост"); return taskOut(startTask("host_diagnostic", [p.id], ctx.user!.id)); });

// agent
route("GET", "/agent/versions", () => {
  const list = hosts.map((h) => ({ host_id: h.id, hostname: h.hostname, ip_address: h.ip_address, has_agent: h.has_agent, agent_version: h.agent_version, version_status: versionStatus(h), agent_version_checked_at: h.agent_version_checked_at, last_seen_at: h.last_seen_at, status: h.status }));
  const withAgent = list.filter((h) => h.has_agent);
  return { available_version: AVAILABLE_AGENT, installer_present: true, total_agents: withAgent.length, up_to_date: withAgent.filter((h) => h.version_status === "up_to_date").length, outdated: withAgent.filter((h) => h.version_status === "outdated").length, unknown: withAgent.filter((h) => h.version_status === "unknown").length, hosts: list };
});
route("POST", "/agent/version-scan", (ctx) => { editor(ctx); const ids = ctx.body.host_ids?.length ? ctx.body.host_ids : hosts.filter((h) => h.has_agent).map((h) => h.id); return taskOut(startTask("agent_version_scan", ids, ctx.user!.id)); });
route("POST", "/agent/update", (ctx) => { editor(ctx); return taskOut(startTask("agent_update", ctx.body.host_ids, ctx.user!.id)); });
route("GET", "/agent/alerts", ({ query }) => alerts.filter((a) => !query.get("host_id") || a.host_id === query.get("host_id")).sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, Number(query.get("limit") ?? 100)));
route("GET", "/agent/enrollment-tokens", (ctx) => { admin(ctx); return tokens; });
route("POST", "/agent/enrollment-tokens", (ctx) => { admin(ctx); const t = { id: uuid(), name: ctx.body.name, expires_at: ctx.body.expires_at, is_active: true, created_at: now().toISOString(), installer_available: true }; tokens.unshift(t); return { ...t, raw_token: `fm_enroll_${Math.floor(rnd() * 1e16).toString(36)}${Math.floor(rnd() * 1e16).toString(36)}` }; });
route("DELETE", "/agent/enrollment-tokens/{id}", (ctx, p) => { admin(ctx); find(tokens, p.id, "Токен").is_active = false; return null; });
route("GET", "/agent/enrollment-tokens/{id}/installer", (ctx) => { admin(ctx); return "MZ-mock-installer"; });

// credentials
route("GET", "/credentials", (ctx) => { editor(ctx); return [...credentials].sort((a, b) => a.name.localeCompare(b.name)).map(credentialOut); });
route("POST", "/credentials", (ctx) => { admin(ctx); const c: Credential = { id: uuid(), name: ctx.body.name, type: ctx.body.type, login: ctx.body.login || null, created_at: now().toISOString(), is_agent_managed: false }; credentials.push(c); return credentialOut(c); });
route("DELETE", "/credentials/{id}", (ctx, p) => { admin(ctx); const c = find(credentials, p.id, "Credential"); credentials.splice(credentials.indexOf(c), 1); hosts.forEach((h) => { if (h.credential_id === c.id) h.credential_id = null; }); return null; });

// dashboard
route("GET", "/dashboard/hosts-summary", () => ({ total: hosts.length, online: hosts.filter((h) => h.status === "online").length, offline: hosts.filter((h) => h.status === "offline").length, unknown: hosts.filter((h) => h.status === "unknown").length }));
route("GET", "/dashboard/recent-tasks", ({ query }) => tasks.slice(0, Number(query.get("limit") ?? 10)).map(taskOut));
route("GET", "/dashboard/top-software", ({ query }) => {
  const counts = new Map<string, Set<string>>();
  software.filter((s) => !isSystem(s.name)).forEach((s) => { if (!counts.has(s.name)) counts.set(s.name, new Set()); counts.get(s.name)!.add(s.host_id); });
  return [...counts].map(([name, set]) => ({ name, version: null, host_count: set.size })).sort((a, b) => b.host_count - a.host_count).slice(0, Number(query.get("limit") ?? 10));
});
route("GET", "/dashboard/stale-hosts", () => hosts.filter((h) => !h.last_checked_at || Date.now() - new Date(h.last_checked_at).getTime() > 7 * 86400_000).map((h) => h.hostname));
route("GET", "/dashboard/recent-software-changes", ({ query }) => history.slice(0, Number(query.get("limit") ?? 10)));
route("GET", "/dashboard/online-timeline", () => Array.from({ length: 25 }, (_, i) => {
  const d = new Date(Date.now() - (24 - i) * 3600_000);
  const hour = d.getHours();
  const base = hour >= 8 && hour <= 20 ? 0.55 : 0.08;
  return { hour: `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")} ${String(hour).padStart(2, "0")}:00`, online: Math.round(hosts.length * (base + rnd() * 0.08)) };
}));
route("GET", "/dashboard/weekly-run-stats", () => Array.from({ length: 7 }, (_, i) => {
  const d = new Date(Date.now() - (6 - i) * 86400_000);
  return { day: `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`, success: Math.floor(rnd() * 25), failed: Math.floor(rnd() * 6) };
}));

// hardware
route("GET", "/hardware", () => hosts.map((h) => ({ id: h.id, hostname: h.hostname, ip_address: h.ip_address, status: h.status, hw_manufacturer: h.hw_manufacturer, hw_model: h.hw_model, hw_serial_number: h.hw_serial_number, hw_os_caption: h.hw_os_caption, hw_processor: h.hw_processor, hw_total_memory_bytes: h.hw_total_memory_bytes })));

// installers
route("GET", "/installers", () => installers);
route("POST", "/installers", (ctx) => { editor(ctx); const f = { name: `uploaded-${installers.length}.exe`, size: 1_000_000, mtime: now().toISOString() }; installers.push(f); return { name: f.name, size: f.size, replaced: false }; });
route("DELETE", "/installers/{name}", (ctx, p) => { editor(ctx); const i = installers.findIndex((f) => f.name === decodeURIComponent(p.name)); if (i >= 0) installers.splice(i, 1); return null; });
route("GET", "/installers/{name}/download", () => "mock-file");
route("POST", "/installers/agent/sync", (ctx) => { editor(ctx); return { updated: false, version: AVAILABLE_AGENT, reason: `Установлена последняя версия ${AVAILABLE_AGENT}` }; });

// playbooks
route("GET", "/playbooks/repos", (ctx) => { editor(ctx); return repos; });
route("POST", "/playbooks/repos", (ctx) => { editor(ctx); const r = { id: uuid(), name: ctx.body.name, git_url: ctx.body.git_url, credential_id: ctx.body.credential_id, branch: ctx.body.branch || "main", created_at: now().toISOString() }; repos.push(r); return r; });
route("POST", "/playbooks/repos/{id}/sync", (ctx, p) => { editor(ctx); return find(repos, p.id, "Репозиторий"); });
route("GET", "/playbooks/repos/{id}/files", (ctx, p) => { editor(ctx); return p.id === repo.id ? playbookFiles : playbookFiles.slice(0, 5); });
route("POST", "/playbooks/run", (ctx) => {
  editor(ctx);
  const ids = resolveTargets(ctx.body.host_ids, [...(ctx.body.host_group_ids ?? []), ...(ctx.body.host_group_id ? [ctx.body.host_group_id] : [])]);
  if (!ids.length) throw new HttpError(400, "Не выбраны хосты");
  const t = startTask("playbook", ids, ctx.user!.id, { playbook_name: ctx.body.playbook_name, extra_vars: ctx.body.extra_vars });
  return { task_run_id: t.id };
});
route("GET", "/playbooks/schedules", (ctx) => { editor(ctx); return schedules.map(scheduleOut); });
route("POST", "/playbooks/schedules", (ctx) => {
  editor(ctx);
  if (!/^\S+ \S+ \S+ \S+ \S+$/.test(ctx.body.cron_expression.trim())) throw new HttpError(422, "Некорректное cron-выражение");
  if (!ctx.body.host_ids?.length && !ctx.body.host_group_ids?.length) throw new HttpError(400, "Не выбраны хосты");
  const s: Schedule = { id: uuid(), repo_id: ctx.body.repo_id, playbook_name: ctx.body.playbook_name, host_group_id: null, host_group_ids: ctx.body.host_group_ids ?? [], host_ids: ctx.body.host_ids ?? [], extra_vars: ctx.body.extra_vars ?? {}, cron_expression: ctx.body.cron_expression.trim(), enabled: ctx.body.enabled ?? true, created_at: now().toISOString() };
  schedules.unshift(s);
  return scheduleOut(s);
});
route("PATCH", "/playbooks/schedules/{id}", (ctx, p) => {
  editor(ctx);
  const s = find(schedules, p.id, "Расписание");
  if (ctx.body.cron_expression && !/^\S+ \S+ \S+ \S+ \S+$/.test(ctx.body.cron_expression.trim())) throw new HttpError(422, "Некорректное cron-выражение");
  Object.assign(s, ctx.body);
  return scheduleOut(s);
});
route("DELETE", "/playbooks/schedules/{id}", (ctx, p) => { editor(ctx); schedules.splice(schedules.indexOf(find(schedules, p.id, "Расписание")), 1); return null; });

// software
route("GET", "/software", ({ query }) => software.filter((s) =>
  (!query.get("host_id") || s.host_id === query.get("host_id")) &&
  (!query.get("name") || s.name.toLowerCase().includes(query.get("name")!.toLowerCase())) &&
  (query.get("exclude_system") !== "true" || !isSystem(s.name))));
route("GET", "/software/packages", ({ query }) => {
  const name = query.get("name")?.toLowerCase();
  const excludeSystem = query.get("exclude_system") !== "false";
  const map = new Map<string, { hosts: Set<string>; versions: Map<string | null, Set<string>> }>();
  for (const s of software) {
    if (s.status !== "installed" || (excludeSystem && isSystem(s.name)) || (name && !s.name.toLowerCase().includes(name))) continue;
    if (!map.has(s.name)) map.set(s.name, { hosts: new Set(), versions: new Map() });
    const entry = map.get(s.name)!;
    entry.hosts.add(s.host_id);
    if (!entry.versions.has(s.version)) entry.versions.set(s.version, new Set());
    entry.versions.get(s.version)!.add(s.host_id);
  }
  return [...map].map(([n, e]) => ({ name: n, host_count: e.hosts.size, versions: [...e.versions].map(([version, set]) => ({ version, host_count: set.size })).sort((a, b) => b.host_count - a.host_count) }))
    .sort((a, b) => b.host_count - a.host_count || a.name.localeCompare(b.name));
});
route("GET", "/software/package-hosts", ({ query }) => software.filter((s) => s.name === query.get("name") && s.status === "installed"));
route("GET", "/software/summary", () => []);
route("GET", "/software/history", ({ query }) => history.filter((h) => !query.get("host_id") || h.host_id === query.get("host_id")));
route("POST", "/software/scan", (ctx) => { editor(ctx); return { task_run_id: startTask("software_scan", ctx.body.host_ids, ctx.user!.id).id }; });
route("GET", "/software/export.csv", () => "name,version\n");
route("GET", "/software/export.pdf", () => "%PDF-mock");

// tasks
route("GET", "/tasks", ({ query, user }) => {
  const limit = Number(query.get("limit") ?? 200);
  const offset = Number(query.get("offset") ?? 0);
  return tasks.filter((t) =>
    (user?.role !== "viewer" || t.task_type !== "host_diagnostic") &&
    (!query.get("task_type") || t.task_type === query.get("task_type")) &&
    (!query.get("status_filter") || t.status === query.get("status_filter")) &&
    (!query.get("host_id") || t.host_ids.includes(query.get("host_id")!)))
    .slice(offset, offset + limit).map(taskOut);
});
route("GET", "/tasks/{id}", (_, p) => { const t = find(tasks, p.id, "Задача"); return { ...taskOut(t), log_output: t.log_output, extra_vars: t.extra_vars }; });
route("GET", "/tasks/{id}/stream", ({ res }, p) => {
  const t = find(tasks, p.id, "Задача");
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
  let sent = 0;
  const send = (event: string, data: string) => res.write(`event: ${event}\r\n${data.split("\n").map((line) => `data: ${line}`).join("\r\n")}\r\n\r\n`);
  const timer = setInterval(() => {
    const log = t.log_output ?? "";
    if (log.length > sent) { send("log", log.slice(sent)); sent = log.length; }
    if (t.status === "success" || t.status === "failed") { send("done", t.status); clearInterval(timer); res.end(); }
  }, 300);
  res.on("close", () => clearInterval(timer));
  return STREAMING;
});
const STREAMING = Symbol("streaming");

// ---------- плагин ----------
function readBody(req: IncomingMessage): Promise<any> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if (!raw || !(req.headers["content-type"] ?? "").includes("json")) return resolve({});
      try { resolve(JSON.parse(raw)); } catch { resolve({}); }
    });
  });
}

export function mockApi(): Plugin {
  return {
    name: "fleet-mock-api",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (!req.url?.startsWith("/api/")) return next();
        const url = new URL(req.url.slice(4), "http://mock");
        const method = req.method ?? "GET";
        const match = routes.find((r) => r.method === method && r.pattern.test(url.pathname));
        const json = (status: number, payload: unknown) => {
          res.statusCode = status;
          res.setHeader("Content-Type", typeof payload === "string" ? "text/plain; charset=utf-8" : "application/json");
          res.end(typeof payload === "string" ? payload : JSON.stringify(payload));
        };
        if (!match) return json(404, { detail: `mock: нет обработчика ${method} ${url.pathname}` });
        const token = (req.headers.authorization ?? "").replace("Bearer ", "");
        const user = users.find((u) => `mock-${u.username}` === token) ?? null;
        if (match.auth && !user) return json(401, { detail: "Not authenticated" });
        const params: Record<string, string> = {};
        url.pathname.match(match.pattern)!.slice(1).forEach((v, i) => (params[match.keys[i]] = decodeURIComponent(v)));
        try {
          const body = await readBody(req);
          // небольшая задержка, чтобы были видны состояния загрузки
          await new Promise((r) => setTimeout(r, 120 + Math.random() * 200));
          const result = match.handler({ method, path: url.pathname, query: url.searchParams, body, user, res }, params);
          if (result === STREAMING) return;
          if (result === null) { res.statusCode = 204; return res.end(); }
          json(method === "POST" && /\/(update|version-scan|diagnostics)$/.test(url.pathname) ? 202 : 200, result);
        } catch (err) {
          if (err instanceof HttpError) return json(err.status, { detail: err.message });
          console.error(err);
          json(500, { detail: String(err) });
        }
      });
    },
  };
}
