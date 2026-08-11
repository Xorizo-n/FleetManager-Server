import { FormEvent, useState } from "react";
import { ShieldCheck } from "lucide-react";
import Button from "./ui/Button";

interface Props {
  qrCodeBase64?: string;
  provisioningUri?: string;
  onSubmit: (code: string) => Promise<void>;
  error?: string | null;
}

export default function TOTPSetup({ qrCodeBase64, provisioningUri, onSubmit, error }: Props) {
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit(code);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="animate-fade-in space-y-4">
      {qrCodeBase64 ? (
        <div className="space-y-2 text-center">
          <p className="text-sm text-muted-foreground">
            Отсканируйте QR-код в Google Authenticator / Authy, затем введите 6-значный код
          </p>
          <img
            src={`data:image/png;base64,${qrCodeBase64}`}
            alt="QR-код для настройки двухфакторной аутентификации"
            className="mx-auto rounded-lg border border-border bg-white p-2"
            width={200}
            height={200}
          />
          {provisioningUri && (
            <p className="break-all text-xs text-subtle">{provisioningUri}</p>
          )}
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
            <ShieldCheck className="h-5 w-5" />
          </span>
          <p className="text-sm text-muted-foreground">Введите 6-значный код из приложения-аутентификатора</p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <input
          type="text"
          inputMode="numeric"
          pattern="[0-9]{6}"
          maxLength={6}
          placeholder="000000"
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          className="input-base text-center text-lg tracking-[0.5em]"
          autoFocus
        />
        {error && <p className="text-sm text-rose-600 dark:text-rose-400" role="alert">{error}</p>}
        <Button type="submit" loading={submitting} disabled={code.length !== 6} className="w-full">
          Подтвердить
        </Button>
      </form>
    </div>
  );
}
