import { HardDrive } from "lucide-react";
import InstallerManager from "../components/InstallerManager";

export default function Installers() {
  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Установщики</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Файлы из хранилища установочников (/mnt/soft-share)
          </p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400">
          <HardDrive className="h-5 w-5" aria-hidden="true" />
        </div>
      </div>
      <InstallerManager />
    </div>
  );
}
