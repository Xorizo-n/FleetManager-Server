"""Generate a Windows self-extracting .exe installer with baked-in credentials.

Requires:
  - nsis (makensis) installed in the container
  - /mnt/soft-share/agent-dist/ containing:
      FleetManager.Agent.Service.exe
      install.ps1
  - Optionally: OpenSSH-Win64.msi (bundled for offline OpenSSH installation)
"""

import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from config import settings

_AGENT_DIST = Path(settings.soft_share_dir) / "agent-dist"

_NSIS_TEMPLATE = """\
Unicode True
SetCompressor /SOLID lzma
!include "LogicLib.nsh"

Name "FleetManager Agent"
OutFile "{output}"
InstallDir "$TEMP\\fm-agent-{uid}"
RequestExecutionLevel admin
ShowInstDetails show

Section "Install"
  SetOutPath "$INSTDIR"
  File "{agent_exe}"
  File "{install_ps1}"
  File "{bootstrap_ps1}"{openssh_msi_line}

  ; Use SysNative so a 32-bit NSIS process launches 64-bit PowerShell (avoids WOW64 System32 redirection)
  nsExec::ExecToLog '$WINDIR\\SysNative\\WindowsPowerShell\\v1.0\\powershell.exe -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\\bootstrap.ps1"'
  Pop $0

  ; Always clean up temp directory
  RMDir /r "$INSTDIR"

  ; Show error dialog AFTER cleanup so user sees what went wrong
  ${{If}} $0 != 0
    MessageBox MB_ICONSTOP|MB_OK "Установка завершилась с ошибкой (код $0).$\\n$\\nПодробности: C:\\ProgramData\\FleetManagerAgent-install.log$\\n$\\nОткройте файл лога для диагностики."
    Abort "Installation failed (exit code $0)"
  ${{EndIf}}
SectionEnd
"""


def agent_dist_ready() -> bool:
    return (
        (_AGENT_DIST / "FleetManager.Agent.Service.exe").is_file()
        and (_AGENT_DIST / "install.ps1").is_file()
    )


def build_installer_exe(server_url: str, enrollment_token: str) -> bytes:
    if not agent_dist_ready():
        raise RuntimeError(
            f"Agent distribution files missing in {_AGENT_DIST}. "
            "Copy FleetManager.Agent.Service.exe and install.ps1 there."
        )

    openssh_msi = _AGENT_DIST / "OpenSSH-Win64.msi"
    openssh_msi_line = f'\n  File "{openssh_msi}"' if openssh_msi.is_file() else ""

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        bootstrap = tmpdir / "bootstrap.ps1"
        bootstrap.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            "$log = [System.IO.Path]::Combine($env:ALLUSERSPROFILE, 'FleetManagerAgent-install.log')\n"
            "function Write-Log([string]$msg) {\n"
            "    $line = \"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg\"\n"
            "    Write-Host $line\n"
            "    [System.IO.File]::AppendAllText($log, $line + \"`r`n\", [System.Text.Encoding]::UTF8)\n"
            "}\n"
            "try {\n"
            f"    & \"$PSScriptRoot\\install.ps1\""
            f" -ServerUrl '{server_url}'"
            f" -EnrollmentToken '{enrollment_token}'"
            f" -PackageRoot \"$PSScriptRoot\""
            f" *>&1 | Tee-Object -FilePath $log -Append\n"
            "    Write-Log 'INSTALLATION COMPLETED SUCCESSFULLY'\n"
            "} catch {\n"
            "    Write-Log \"ERROR: $($_.Exception.Message)\"\n"
            "    Write-Log $_.ScriptStackTrace\n"
            "    exit 1\n"
            "}\n",
            encoding="utf-8",
        )

        output_exe = tmpdir / "installer.exe"
        nsi_path = tmpdir / "installer.nsi"
        nsi_path.write_text(
            _NSIS_TEMPLATE.format(
                output=str(output_exe),
                uid=uuid.uuid4().hex[:12],
                agent_exe=str(_AGENT_DIST / "FleetManager.Agent.Service.exe"),
                install_ps1=str(_AGENT_DIST / "install.ps1"),
                bootstrap_ps1=str(bootstrap),
                openssh_msi_line=openssh_msi_line,
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            ["makensis", "-V2", str(nsi_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"makensis failed (exit {result.returncode}):\n"
                f"{result.stdout}\n{result.stderr}"
            )

        return output_exe.read_bytes()


def safe_filename(name: str) -> str:
    ascii_name = name.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^\w\-]", "_", ascii_name).strip("_")
    return f"FleetManagerAgent-{safe or 'Setup'}.exe"
