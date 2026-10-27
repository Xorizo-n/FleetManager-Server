"""fm_fetch — win_copy установщика из шары, но ПК скачивает файл сам с точки раздачи.

Те же параметры, что у ansible.windows.win_copy. Если src — файл шары (/mnt/soft-share),
который уже лежит на точке раздачи (services/distribution.py, манифест), ПК скачивает его
по подписанной ссылке curl.exe и сверяет SHA-256. Иначе — и при любой ошибке скачивания —
обычный win_copy по SSH, поэтому плейбук работает и без точки раздачи.

Плагин работает внутри ansible-playbook, а не в приложении: настройки берёт из окружения
воркера (.env), те же переменные, что и config.py.
"""
from __future__ import annotations

import base64
import hashlib
import json
import ntpath
import os
import re
import time
from urllib.parse import quote

from ansible.plugins.action import ActionBase
from ansible.utils.display import Display

display = Display()

SHARE = os.environ.get("SOFT_SHARE_DIR", "/mnt/soft-share")
MANIFEST = os.environ.get("DIST_MANIFEST_PATH", "/app/ansible_data/dist-manifest.json")
TTL = int(os.environ.get("DIST_LINK_TTL_SECONDS", str(12 * 3600)))

# Скрипт уходит через -EncodedCommand (UTF-16 + base64): держим его коротким.
SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$url = '__URL__'; $sha = '__SHA__'; $dest = '__DEST__'; $name = '__NAME__'
function Out-Result($o) { 'FMFETCH=' + ($o | ConvertTo-Json -Compress) }
try {
  if (Test-Path -LiteralPath $dest -PathType Container) { $dest = Join-Path $dest $name }
  if ((Test-Path -LiteralPath $dest -PathType Leaf) -and (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -eq $sha) {
    Out-Result @{ status = 'same'; dest = $dest }; exit 0
  }
  $dir = Split-Path -Parent $dest
  if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  $part = $dest + '.' + $sha.Substring(0, 12) + '.fmpart'
  $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
  $t0 = Get-Date
  if (Test-Path -LiteralPath $curl) {
    $err = & $curl -sS -f -C - --retry 5 --retry-delay 3 --connect-timeout 15 -o $part $url 2>&1
    if ($LASTEXITCODE -ne 0) { throw "curl $LASTEXITCODE $err" }
  } else {
    (New-Object Net.WebClient).DownloadFile($url, $part)
  }
  $seconds = ((Get-Date) - $t0).TotalSeconds
  if ((Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash -ne $sha) {
    Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
    throw 'SHA-256 mismatch'
  }
  Move-Item -LiteralPath $part -Destination $dest -Force
  Out-Result @{ status = 'downloaded'; dest = $dest; seconds = [math]::Round($seconds, 1); bytes = (Get-Item -LiteralPath $dest).Length }
} catch {
  Out-Result @{ status = 'error'; error = [string]$_ }
}
"""


def _ps(value: str) -> str:
    return value.replace("'", "''")


def _sign(rel: str) -> str:
    expires = int(time.time()) + TTL
    uri = "/" + rel
    digest = hashlib.md5(f"{expires}{uri} {os.environ['DIST_SECRET']}".encode()).digest()
    md5 = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return f"{os.environ['DIST_URL'].rstrip('/')}{quote(uri)}?md5={md5}&expires={expires}"


def distribution_entry(src) -> tuple[str, str] | None:
    """(rel, sha256), если src — файл шары, и на точке раздачи лежит именно эта его версия."""
    if not (os.environ.get("DIST_URL") and os.environ.get("DIST_SECRET")) or not isinstance(src, str):
        return None
    root = os.path.realpath(SHARE)
    real = os.path.realpath(src)
    if not real.startswith(root + os.sep) or not os.path.isfile(real):
        return None
    rel = os.path.relpath(real, root).replace(os.sep, "/")
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            entry = (json.load(f).get("files") or {}).get(rel)
        stat = os.stat(real)
    except (OSError, ValueError):
        return None
    if not entry or [stat.st_size, stat.st_mtime_ns] != entry[:2]:
        return None
    return rel, entry[2]


class ActionModule(ActionBase):
    TRANSFERS_FILES = False

    def _win_copy(self, task_vars, warning=None):
        action = self._shared_loader_obj.action_loader.get(
            "ansible.windows.win_copy", task=self._task.copy(), connection=self._connection,
            play_context=self._play_context, loader=self._loader, templar=self._templar,
            shared_loader_obj=self._shared_loader_obj)
        result = action.run(task_vars=task_vars)
        if warning:
            result.setdefault("warnings", []).append(warning)
        return result

    def run(self, tmp=None, task_vars=None):
        args = self._task.args
        src, dest = args.get("src"), args.get("dest")
        simple = (dest and not args.get("content") and not args.get("remote_src")
                  and str(args.get("force", True)).lower() not in ("false", "no", "0")
                  and not self._play_context.check_mode)
        entry = distribution_entry(src) if simple else None
        if entry is None:
            return self._win_copy(task_vars)

        rel, sha = entry
        name = os.path.basename(rel)
        dest = str(dest)
        if dest.endswith(("\\", "/")):
            dest = ntpath.join(dest, name)
        script = (SCRIPT.replace("__URL__", _ps(_sign(rel))).replace("__SHA__", sha.upper())
                  .replace("__DEST__", _ps(dest)).replace("__NAME__", _ps(name)))
        try:
            res = self._low_level_execute_command(script, executable=False)  # как raw: без /bin/sh -c
            match = re.search(r"FMFETCH=(\{.*\})", (res.get("stdout") or "").replace("\r", "").replace("\n", ""))
            outcome = json.loads(match.group(1)) if match else {"status": "error", "error": (res.get("stderr") or "")[-300:]}
        except Exception as exc:  # noqa: BLE001
            outcome = {"status": "error", "error": str(exc)}

        if outcome.get("status") == "error":
            return self._win_copy(task_vars, f"Точка раздачи: {outcome.get('error') or 'нет ответа'} — файл скопирован по SSH")
        result = {"changed": outcome["status"] == "downloaded", "dest": outcome.get("dest", dest), "src": src,
                  "sha256": sha, "fm_source": "distribution"}
        if outcome["status"] == "downloaded":
            size = outcome.get("bytes") or 0
            seconds = outcome.get("seconds") or 0
            speed = f", {size * 8 / 1e6 / seconds:.0f} Мбит/с" if seconds else ""
            result["msg"] = f"{name}: {size / 1e6:.0f} МБ с точки раздачи за {seconds} с{speed}"
            display.display(f"  {task_vars.get('inventory_hostname') or ''} {result['msg']}".rstrip())
        return result
