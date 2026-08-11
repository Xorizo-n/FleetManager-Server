import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate, useLocation } from "react-router-dom";
import { ChevronDown, LogOut, Menu, Server, Settings, X } from "lucide-react";
import { UserRole, useAuth } from "../context/AuthContext";
import ThemeToggle from "./ui/ThemeToggle";

const NAV_ITEMS: { to: string; label: string; end?: boolean; roles?: UserRole[] }[] = [
  { to: "/", label: "Дашборд", end: true },
  { to: "/hosts", label: "Хосты" },
  { to: "/software", label: "ПО" },
  { to: "/hardware", label: "Железо" },
  { to: "/playbooks", label: "Плейбуки" },
  { to: "/tasks", label: "Задачи" },
  { to: "/keystore", label: "Ключи" },
];

const ADMIN_ITEMS: { to: string; label: string }[] = [
  { to: "/users", label: "Пользователи" },
  { to: "/tokens", label: "Токены агентов" },
];

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150 ${
    isActive
      ? "bg-blue-600 text-white"
      : "text-muted-foreground hover:bg-muted hover:text-foreground"
  }`;

const mobileLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150 ${
    isActive
      ? "bg-blue-600 text-white"
      : "text-muted-foreground hover:bg-muted hover:text-foreground"
  }`;

function AdminDropdown() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const isAdminActive = ADMIN_ITEMS.some((i) => location.pathname === i.to);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onEscape(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onEscape);
    };
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={`flex items-center gap-1 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 ${
          isAdminActive
            ? "bg-blue-600 text-white"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"
        }`}
      >
        <Settings className="h-3.5 w-3.5" />
        <span>Управление</span>
        <ChevronDown
          className={`h-3.5 w-3.5 transition-transform duration-150 ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div role="menu" className="absolute right-0 top-full z-50 mt-1 min-w-[180px] rounded-xl border border-border bg-background shadow-lg py-1">
          {ADMIN_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              role="menuitem"
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `block px-4 py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500/60 ${
                  isActive
                    ? "text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/40"
                    : "text-foreground hover:bg-muted"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  const visibleNavItems = NAV_ITEMS.filter((item) => {
    if (item.to === "/playbooks" && user?.role === "viewer") return false;
    return !item.roles || (user && item.roles.includes(user.role));
  });

  const isAdmin = user?.role === "admin";

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-20 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">

          {/* Logo */}
          <div className="flex items-center gap-6">
            <span className="flex items-center gap-2 text-base font-semibold tracking-tight shrink-0">
              <span className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-600 text-white">
                <Server className="h-4 w-4" />
              </span>
              Fleet Manager
            </span>

            {/* Desktop nav */}
            <nav className="hidden md:flex md:items-center md:gap-0.5">
              {visibleNavItems.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end} className={linkClass}>
                  {item.label}
                </NavLink>
              ))}
              {isAdmin && <AdminDropdown />}
            </nav>
          </div>

          {/* Right side: user + controls */}
          <div className="flex items-center gap-2">
            {user && (
              <span className="hidden items-center gap-2 text-sm text-muted-foreground sm:flex">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-muted text-xs font-medium text-foreground">
                  {user.username.slice(0, 1).toUpperCase()}
                </span>
                <span className="max-w-[120px] truncate">{user.username}</span>
                <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium text-foreground">
                  {user.role}
                </span>
              </span>
            )}
            <ThemeToggle />
            <button onClick={handleLogout} aria-label="Выйти" className="btn-ghost btn-sm">
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline" aria-hidden="true">Выйти</span>
            </button>
            <button
              className="btn-ghost btn-icon md:hidden"
              onClick={() => setMenuOpen((v) => !v)}
              aria-label="Меню"
              aria-expanded={menuOpen}
            >
              {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>

        {/* Mobile nav */}
        <div
          className={`grid overflow-hidden border-t border-border transition-all duration-200 ease-out md:hidden ${
            menuOpen ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
          }`}
        >
          <nav className="flex min-h-0 flex-col gap-1 px-4 py-2">
            {visibleNavItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={mobileLinkClass}
                onClick={() => setMenuOpen(false)}
              >
                {item.label}
              </NavLink>
            ))}
            {isAdmin &&
              ADMIN_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={mobileLinkClass}
                  onClick={() => setMenuOpen(false)}
                >
                  {item.label}
                </NavLink>
              ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
