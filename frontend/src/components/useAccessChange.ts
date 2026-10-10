import { useQueryClient } from "@tanstack/react-query";
import { AccessChange, changeAccess } from "../api/accessChange";
import { keys } from "../api/queries";
import { useToast } from "./ui/Toast";
import { useOpenTask } from "./TaskPanel";
import { pcCount } from "../lib/format";

/**
 * Запускает смену доступа и показывает результат: если нужна проверка входа —
 * открывает её лог (изменения применятся по завершении), иначе сообщает, что применено.
 * Возвращает true, если запрос принят.
 */
export function useAccessChange() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const openTask = useOpenTask();

  return async (change: AccessChange): Promise<boolean> => {
    const result = await changeAccess(change);
    if (result.task) {
      toast({
        tone: "info",
        message: `Проверяем вход новыми данными на ${pcCount(result.to_check)}. Изменение применится там, где вход пройдёт`,
      });
      openTask(result.task.id);
    } else {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.hosts }),
        queryClient.invalidateQueries({ queryKey: keys.groups }),
        queryClient.invalidateQueries({ queryKey: keys.credentials }),
      ]);
      toast({
        tone: "success",
        message: `Применено: ${pcCount(result.applied)}${result.skipped ? `, пропущено ${result.skipped} (ключ агента не меняется)` : ""}`,
      });
    }
    return true;
  };
}
