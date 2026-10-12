// Подключение к ПК по RDP: браузер не может сам запустить mstsc, поэтому отдаём файл .rdp.
// Windows открывает его стандартным окном «Подключение к удалённому рабочему столу»,
// учётные данные вводит сам подключающийся — в файле только адрес.

interface RdpTarget {
  hostname: string | null;
  ip_address: string | null;
}

/**
 * Адрес — IP, который сообщает агент, а не имя: в зоне rtf.ustu много устаревших
 * DNS-записей, указывающих на чужие ПК, и подключение по имени могло бы попасть не туда.
 */
export function rdpAddress(host: RdpTarget): string | null {
  return host.ip_address || host.hostname || null;
}

export function rdpFileContent(address: string): string {
  return [
    `full address:s:${address}`,
    "prompt for credentials:i:1", // всегда спрашивать логин и пароль
    "authentication level:i:2", // сертификат не проверен — предупредить и дать решить
    "redirectclipboard:i:1",
    "audiomode:i:0",
    "",
  ].join("\r\n");
}

export function downloadRdpFile(host: RdpTarget) {
  const address = rdpAddress(host);
  if (!address) return;
  const blob = new Blob([rdpFileContent(address)], { type: "application/x-rdp" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${(host.hostname || address).replace(/[^\w.-]+/g, "_")}.rdp`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
