import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Eye, EyeOff, Server } from "lucide-react";
import { apiClient, setTokens } from "../api/client";
import { useAuth } from "../context/AuthContext";
import TOTPSetup from "../components/TOTPSetup";
import Button from "../components/ui/Button";
import ThemeToggle from "../components/ui/ThemeToggle";

type Step =
  | { name: "credentials" }
  | { name: "totp_setup"; preAuthToken: string; qrCodeBase64: string; provisioningUri: string }
  | { name: "totp_required"; preAuthToken: string };

export default function Login() {
  const navigate = useNavigate();
  const { refreshUser } = useAuth();

  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [step, setStep] = useState<Step>({ name: "credentials" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleCredentialsSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === "register") {
        await apiClient.post("/auth/register", { username, email, password });
        setMode("login");
        setError("Регистрация выполнена, теперь войдите");
        return;
      }

      const { data } = await apiClient.post("/auth/login", { username, password });
      if (data.status === "totp_setup_required") {
        setStep({
          name: "totp_setup",
          preAuthToken: data.pre_auth_token,
          qrCodeBase64: data.qr_code_base64,
          provisioningUri: data.provisioning_uri,
        });
      } else {
        setStep({ name: "totp_required", preAuthToken: data.pre_auth_token });
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка входа");
    } finally {
      setLoading(false);
    }
  }

  async function handleTotpSubmit(code: string) {
    if (step.name === "credentials") return;
    setError(null);
    try {
      const { data } = await apiClient.post("/auth/totp/verify", {
        pre_auth_token: step.preAuthToken,
        code,
      });
      setTokens(data.access_token, data.refresh_token);
      await refreshUser();
      navigate("/");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Неверный код");
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background px-4">
      <ThemeToggle className="absolute right-4 top-4" />
      <div className="surface-card w-full max-w-sm animate-slide-up p-6 shadow-panel-lg">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-600 text-white">
            <Server className="h-5 w-5" />
          </span>
          <h1 className="text-xl font-semibold">Fleet Manager</h1>
        </div>

        {step.name === "credentials" && (
          <form onSubmit={handleCredentialsSubmit} className="space-y-3">
            <div>
              <label htmlFor="username" className="field-label">
                Имя пользователя
              </label>
              <input
                id="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                className="input-base"
              />
            </div>
            {mode === "register" && (
              <div>
                <label htmlFor="email" className="field-label">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="input-base"
                />
              </div>
            )}
            <div>
              <label htmlFor="password" className="field-label">
                Пароль
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  className="input-base pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-subtle transition-colors hover:text-foreground"
                  aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            {error && <p className="text-sm text-rose-600 dark:text-rose-400" role="alert">{error}</p>}
            <Button type="submit" loading={loading} className="w-full">
              {mode === "login" ? "Войти" : "Зарегистрироваться"}
            </Button>
            <button
              type="button"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError(null);
              }}
              className="w-full text-center text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {mode === "login" ? "Нет аккаунта? Зарегистрироваться" : "Уже есть аккаунт? Войти"}
            </button>
          </form>
        )}

        {step.name === "totp_setup" && (
          <TOTPSetup
            qrCodeBase64={step.qrCodeBase64}
            provisioningUri={step.provisioningUri}
            onSubmit={handleTotpSubmit}
            error={error}
          />
        )}

        {step.name === "totp_required" && (
          <TOTPSetup onSubmit={handleTotpSubmit} error={error} />
        )}
      </div>
    </div>
  );
}
