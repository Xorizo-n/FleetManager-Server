import json
import re


ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|$))")


def _load_json_fragment(raw: str):
    text = ANSI_ESCAPE_RE.sub("", raw or "")
    decoder = json.JSONDecoder()
    objects = []
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:].replace("\r", "").replace("\n", ""))
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            objects.append(value)
    return objects or None


def parse_get_package(raw: str) -> list[tuple[str, str]]:
    """Парсит вывод `Get-Package | ConvertTo-Json -Compress` (может быть объект или массив)."""
    data = _load_json_fragment(raw)
    if data is None:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        (str(item.get("Name", "")).strip(), str(item.get("Version", "")).strip())
        for item in data
        if isinstance(item, dict) and item.get("Name")
    ]


def parse_registry_packages(raw: str) -> list[tuple[str, str]]:
    data = _load_json_fragment(raw)
    if data is None:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        (str(item.get("Name", "")).strip(), str(item.get("Version", "")).strip())
        for item in data
        if isinstance(item, dict) and item.get("Name")
    ]


def parse_choco_list(raw: str) -> list[tuple[str, str]]:
    """Парсит вывод `choco list --local-only --limit-output` (строки вида name|version)."""
    results = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        name, _, version = line.partition("|")
        results.append((name.strip(), version.strip()))
    return results
