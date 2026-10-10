import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, LogOut, Menu as MenuIcon, Server, Settings, X } from "lucide-react";
import { UserRole, useAuth } from "../context/AuthContext";
import ThemeToggle from "./ui/ThemeToggle";
import Menu from "./ui/Menu";
import { TaskPanelProvider } from "./TaskPanel";

const EDITORS: UserRole[] = ["admin", "operator"];

export const NAV_ITEMS: { to: string; label: string; end?: boolean; roles?: UserRole[] }[] = [
  { to: "/", label: "Обзор", end: true },
  { to: "/hosts", label: "Хосты" },
  { to: "/software", label: "ПО" },
  { to: "/automation", label: "Автоматизация", roles: EDITORS },
  { to: "/tasks", label: "Задачи" },
];

export const ADMIN_ITEMS: { to: string; label: string; roles: UserRole[] }[] = [
  { to: "/admin/users", label: "Пользователи", roles: ["admin"] },
  { to: "/admin/credentials", label: "Учётные данные", roles: EDITORS },
  { to: "/admin/groups", label: "Группы хостов", roles: EDITORS },
  { to: "/admin/agent", label: "Агент и токены", roles: EDITORS },
  { to: "/admin/files", label: "Хранилище установщиков", roles: EDITORS },
];

const ROLE_LABELS: Record<UserRole, string> = { admin: "админ", operator: "оператор", viewer: "наблюдатель" };

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150 ${
    isActive ? "bg-blue-600 text-white" : "text-muted-foreground hover:bg-muted hover:text-foreground"
  }`;

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => setMenuOpen(false), [location.pathname]);

  const allowed = (roles?: UserRole[]) => !roles || (user && roles.includes(user.role));
  const navItems = NAV_ITEMS.filter((i) => allowed(i.roles));
  const adminItems = ADMIN_ITEMS.filter((i) => allowed(i.roles));
  const adminActive = location.pathname.startsWith("/admin");

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <TaskPanelProvider>
      <div className="min-h-screen bg-background text-foreground">
        <header className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur-md">
          <div className="mx-auto flex h-14 max-w-[96rem] items-center justify-between gap-4 px-4">
            <div className="flex min-w-0 items-center gap-6">
              <NavLink to="/" className="flex shrink-0 items-center gap-2 text-base font-semibold tracking-tight">
                <span className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-600 text-white">
                  <Server className="h-4 w-4" />
                </span>
                <span className="hidden sm:inline">Fleet Manager</span>
              </NavLink>
              <nav className="hidden items-center gap-0.5 lg:flex">
                {navItems.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.end} className={linkClass}>
                    {item.label}
                  </NavLink>
                ))}
                {adminItems.length > 0 && (
                  <Menu
                    align="left"
                    trigger={({ open, toggle }) => (
                      <button
                        onClick={toggle}
                        aria-haspopup="menu"
                        aria-expanded={open}
                        className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                          adminActive ? "bg-blue-600 text-white" : "text-muted-foreground hover:bg-muted hover:text-foreground"
                        }`}
                      >
                        <Settings className="h-3.5 w-3.5" />
                        Администрирование
                        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
                      </button>
                    )}
                    items={adminItems.map((item) => ({ label: item.label, onClick: () => navigate(item.to) }))}
                  />
                )}
              </nav>
            </div>

            <div className="flex shrink-0 items-center gap-1">
              {user && (
                <span className="mr-1 hidden items-center gap-2 text-sm text-muted-foreground xl:flex" title={`${user.username} (${ROLE_LABELS[user.role]})`}>
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-muted text-xs font-medium text-foreground">
                    {user.username.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="max-w-[120px] truncate">{user.username}</span>
                  <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs">{ROLE_LABELS[user.role]}</span>
                </span>
              )}
              <ThemeToggle />
              <button onClick={handleLogout} aria-label="Выйти" title="Выйти" className="btn-ghost btn-icon">
                <LogOut className="h-4 w-4" />
              </button>
              <button className="btn-ghost btn-icon lg:hidden" onClick={() => setMenuOpen((v) => !v)} aria-label="Меню" aria-expanded={menuOpen}>
                {menuOpen ? <X className="h-5 w-5" /> : <MenuIcon className="h-5 w-5" />}
              </button>
            </div>
          </div>

          {menuOpen && (
            <nav className="flex flex-col gap-1 border-t border-border px-4 py-2 lg:hidden">
              {navItems.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end} className={linkClass}>
                  {item.label}
                </NavLink>
              ))}
              {adminItems.length > 0 && <p className="px-3 pt-2 text-xs font-medium uppercase tracking-wide text-subtle">Администрирование</p>}
              {adminItems.map((item) => (
                <NavLink key={item.to} to={item.to} className={linkClass}>
                  {item.label}
                </NavLink>
              ))}
              {user && <p className="px-3 py-2 text-xs text-muted-foreground">{user.username} · {ROLE_LABELS[user.role]}</p>}
            </nav>
          )}
        </header>

        <main className="mx-auto max-w-[96rem] px-4 py-6">
          <Outlet />
        </main>
      </div>
    </TaskPanelProvider>
  );
}
