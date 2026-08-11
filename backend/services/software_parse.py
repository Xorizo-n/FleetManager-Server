import json


def parse_get_package(raw: str) -> list[tuple[str, str]]:
    """Парсит вывод `Get-Package | ConvertTo-Json -Compress` (может быть объект или массив)."""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        (str(item.get("Name", "")).strip(), str(item.get("Version", "")).strip())
        for item in data
        if item.get("Name")
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
