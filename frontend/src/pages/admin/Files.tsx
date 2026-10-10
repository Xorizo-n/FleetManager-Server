import PageHeader from "../../components/ui/PageHeader";
import InstallerManager from "../../components/InstallerManager";

export default function Files() {
  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader title="Хранилище установщиков" description="Файлы в /mnt/soft-share, которые используют плейбуки установки ПО" />
      <InstallerManager />
    </div>
  );
}
