import Badge from "./ui/Badge";

export interface SoftwareItemRow {
  id: string;
  host_id: string;
  name: string;
  version: string | null;
  install_method: string;
  status: string;
  detected_at: string;
}

export default function SoftwareTable({ items, hostNameById }: { items: SoftwareItemRow[]; hostNameById: (id: string) => string }) {
  return (
    <div className="table-shell">
      <table className="table-base">
        <thead>
          <tr>
            <th>Хост</th>
            <th>Название</th>
            <th>Версия</th>
            <th>Способ установки</th>
            <th>Статус</th>
            <th>Обнаружено</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{hostNameById(item.host_id)}</td>
              <td className="font-medium text-foreground">{item.name}</td>
              <td className="font-mono text-foreground/80">{item.version || "—"}</td>
              <td>{item.install_method}</td>
              <td><Badge status={item.status} /></td>
              <td className="text-muted-foreground">{new Date(item.detected_at).toLocaleString("ru-RU")}</td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr>
              <td colSpan={6} className="px-3 py-8 text-center text-subtle">Нет данных</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
