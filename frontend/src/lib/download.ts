import { apiClient } from "../api/client";

/** Скачивает файл с API с токеном авторизации (обычная ссылка токен не передаёт). */
export async function downloadFromApi(path: string, filename: string) {
  const response = await apiClient.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
