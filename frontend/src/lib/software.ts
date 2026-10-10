// Те же правила, что у backend (routers/software.py, _SYSTEM_PREFIXES):
// системное ПО Microsoft/Windows, обновления и AppX-пакеты с GUID вместо имени.
const SYSTEM_PREFIXES = [
  "microsoft ", "microsoft.", "microsoftwindows.", "microsoftcorporationii.", "windows ", "windows.", "kb", "update for ",
  "security update", "hotfix", "visual c++", ".net", "directx", "vs_", "vcpp_crt", "vs script debugging", "winrt intellisense",
  "universal crt", "sdk arm64", "winappde", "wptx64", "kits configuration", "application verifier", "diagnosticshub_",
  "msi development tools", "universal general midi", "office 16 click-to-run", "clickonce bootstrapper", "ncsiuwpapp", "mdodrmcpfilter",
];
const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isSystemSoftware(name: string) {
  const lower = name.toLowerCase();
  return SYSTEM_PREFIXES.some((p) => lower.startsWith(p)) || GUID.test(name);
}
