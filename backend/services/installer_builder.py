"""Установщик агента с вшитыми адресом сервера и токеном регистрации.

Это тонкая NSIS-обёртка вокруг актуального Inno-установщика
`FleetManagerAgent-Setup.exe`, который сервер сам синхронизирует с GitHub
Releases (services/agent_installer_sync.py). Обёртка ничего не устанавливает
сама: она распаковывает Inno-установщик во временную папку NSIS ($PLUGINSDIR) и
запускает его молча с параметрами /ServerUrl и /EnrollmentToken (см.
installer/FleetManagerAgent.iss в FleetManager-Agent). Поэтому ПК получает ту же
установку, что и при ручном запуске или удалённом обновлении: службу, трей,
панель управления, OpenSSH, RDP, Wake-on-LAN, запись в «Программах».

Токен на диске остаётся только в agent.json агента: обёртка не пишет его в
файлы, а $PLUGINSDIR NSIS удаляет при выходе. Inno Setup записывает в свой
журнал командную строку вместе с токеном, поэтому журнал создаётся во временной
папке, а в C:\\ProgramData\\FleetManagerAgent\\logs\\setup.log попадает копия
с замаскированным токеном.

Требуется makensis (пакет nsis в образе backend).
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path

from services.agent_version import available_agent_version, installer_path

# Журналы на ПК: setup.log — копия журнала Inno без токена, install.log пишет
# PowerShell-часть установщика агента.
LOG_DIR = r"$APPDATA\FleetManagerAgent\logs"  # $APPDATA = C:\ProgramData при SetShellVarContext all
SETUP_LOG = LOG_DIR + r"\setup.log"
INSTALL_LOG = LOG_DIR + r"\install.log"

# Значения попадают в командную строку и в строки NSIS без экранирования, поэтому
# допускаем только безопасные символы. Токены выдаёт secrets.token_urlsafe.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SERVER_URL_RE = re.compile(r"^https?://[A-Za-z0-9.\-_~:/\[\]%]+$")

# Маскирует токен в копии журнала Inno. Файл читается и пишется побайтово
# (Latin-1), чтобы не испортить кодировку остальных строк журнала.
MASK_LOG_PS1 = """\
param([string]$Source, [string]$Destination)
if (-not (Test-Path -LiteralPath $Source)) { exit 0 }
$latin1 = [Text.Encoding]::GetEncoding(28591)
$text = $latin1.GetString([IO.File]::ReadAllBytes($Source))
$text = [regex]::Replace($text, '(?i)(/EnrollmentToken=)("[^"]*"|\\S+)', '$1***')
[IO.File]::WriteAllBytes($Destination, $latin1.GetBytes($text))
"""

# Коды выхода Inno Setup (https://jrsoftware.org/ishelp/topic_setupexitcodes.htm).
INNO_EXIT_CODES = {
    1: "установка не запустилась (например, не передан адрес сервера или токен)",
    2: "установка отменена до начала",
    3: "критическая ошибка при подготовке к установке",
    4: "критическая ошибка во время установки",
    5: "установка отменена во время копирования файлов",
    6: "процесс установщика был принудительно завершён",
    7: "подготовка к установке не может продолжиться (например, файлы агента заняты)",
    8: "нужна перезагрузка: перезагрузите ПК и запустите установщик снова",
}

_NSIS_TEMPLATE = """\
Unicode True
ManifestDPIAware true
; Inno-установщик уже сжат: повторное сжатие только тратит время сервера.
SetCompress off
RequestExecutionLevel admin
!include "LogicLib.nsh"

Name "FleetManager Agent{version_suffix}"
Caption "Установка FleetManager Agent{version_suffix}"
BrandingText "Fleet Manager"
OutFile "{output}"
ShowInstDetails show
Page instfiles

Function ExitCodeText
  Exch $0
{exit_code_cases}
  ${{Else}}
    StrCpy $0 "неизвестная ошибка"
  ${{EndIf}}
  Exch $0
FunctionEnd

Section "Install"
  SetShellVarContext all
  InitPluginsDir
  File "/oname=$PLUGINSDIR\\FleetManagerAgent-Setup.exe" "{setup_exe}"
  File "/oname=$PLUGINSDIR\\mask-log.ps1" "{mask_ps1}"

  DetailPrint "Устанавливается FleetManager Agent{version_suffix}, это займёт несколько минут..."
  ClearErrors
  ExecWait '"$PLUGINSDIR\\FleetManagerAgent-Setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG="$PLUGINSDIR\\setup.log" /ServerUrl={server_url} /EnrollmentToken={token}' $0
  ${{If}} ${{Errors}}
    StrCpy $0 -1
  ${{EndIf}}

  ; Журнал Inno содержит командную строку с токеном: сохраняем только копию с маской.
  CreateDirectory "{log_dir}"
  nsExec::Exec '"$SYSDIR\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\\mask-log.ps1" "$PLUGINSDIR\\setup.log" "{setup_log}"'
  Pop $1
  Delete "$PLUGINSDIR\\setup.log"
  Delete "$PLUGINSDIR\\FleetManagerAgent-Setup.exe"

  ${{If}} $0 == -1
    StrCpy $2 "не удалось запустить установщик агента"
  ${{Else}}
    Push $0
    Call ExitCodeText
    Pop $2
  ${{EndIf}}

  ${{If}} $0 != 0
    DetailPrint "Ошибка установки (код $0): $2"
    DetailPrint "Журнал установщика: {setup_log}"
    DetailPrint "Журнал шагов установки: {install_log}"
    MessageBox MB_ICONSTOP|MB_OK "Установка FleetManager Agent завершилась с ошибкой (код $0):$\\n$2.$\\n$\\nЖурнал установщика:$\\n{setup_log}$\\n$\\nЖурнал шагов установки:$\\n{install_log}" /SD IDOK
    SetErrorLevel $0
    Abort "Установка завершилась с ошибкой (код $0)"
  ${{EndIf}}

  DetailPrint "FleetManager Agent установлен. ПК появится в реестре Fleet Manager после первой связи с сервером, обычно в течение минуты."
SectionEnd
"""


def _exit_code_cases() -> str:
    lines = []
    for index, (code, text) in enumerate(sorted(INNO_EXIT_CODES.items())):
        keyword = "${If}" if index == 0 else "${ElseIf}"
        lines.append(f"  {keyword} $0 == {code}\n    StrCpy $0 \"{text}\"")
    return "\n".join(lines)


def render_nsi(
    *,
    server_url: str,
    enrollment_token: str,
    setup_exe: str,
    mask_ps1: str,
    output: str,
    version: str | None = None,
) -> str:
    """Текст .nsi обёртки. Значения проверяются: в NSIS и командную строку они идут как есть."""
    if not _SERVER_URL_RE.match(server_url):
        raise ValueError(f"Недопустимый адрес сервера для установщика: {server_url!r}")
    if not _TOKEN_RE.match(enrollment_token):
        raise ValueError("Недопустимые символы в токене регистрации")
    version_suffix = f" {version}" if version and re.fullmatch(r"[0-9A-Za-z.\-]+", version) else ""
    return _NSIS_TEMPLATE.format(
        output=output,
        setup_exe=setup_exe,
        mask_ps1=mask_ps1,
        server_url=server_url,
        token=enrollment_token,
        version_suffix=version_suffix,
        exit_code_cases=_exit_code_cases(),
        log_dir=LOG_DIR,
        setup_log=SETUP_LOG,
        install_log=INSTALL_LOG,
    )


def build_installer_exe(server_url: str, enrollment_token: str) -> bytes:
    setup_exe = installer_path()
    if not os.path.isfile(setup_exe):
        raise RuntimeError(
            "Установщик агента ещё не синхронизирован на сервере: "
            "нажмите «Проверить обновление агента» в «Администрирование → Агент и токены»."
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        mask_ps1 = tmpdir / "mask-log.ps1"
        mask_ps1.write_text(MASK_LOG_PS1, encoding="ascii")
        output_exe = tmpdir / "installer.exe"
        nsi_path = tmpdir / "installer.nsi"
        nsi_path.write_text(
            render_nsi(
                server_url=server_url,
                enrollment_token=enrollment_token,
                setup_exe=setup_exe,
                mask_ps1=str(mask_ps1),
                output=str(output_exe),
                version=available_agent_version(),
            ),
            encoding="utf-8-sig",
        )

        result = subprocess.run(
            ["makensis", "-V2", "-INPUTCHARSET", "UTF8", str(nsi_path)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            # В выводе makensis может оказаться строка скрипта с токеном.
            output = f"{result.stdout}\n{result.stderr}".replace(enrollment_token, "***")
            raise RuntimeError(f"makensis failed (exit {result.returncode}):\n{output}")

        return output_exe.read_bytes()


def safe_filename(name: str) -> str:
    ascii_name = name.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^\w\-]", "_", ascii_name).strip("_")
    return f"FleetManagerAgent-{safe or 'Setup'}.exe"
