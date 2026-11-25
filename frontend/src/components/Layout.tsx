import { MouseEvent, Suspense, useEffect, useId, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { ChevronDown, LayoutDashboard, Menu as MenuIcon, Monitor, Server, Settings, Workflow, X } from "lucide-react";
import { UserRole, useAuth } from "../context/AuthContext";
import UserMenu, { ROLE_LABELS } from "./UserMenu";
import { TaskPanelProvider } from "./TaskPanel";
import { Loading } from "./ui/States";

const EDITORS: UserRole[] = ["admin", "operator"];
// Инженер мониторинга видит только раздел «Мониторинг» — остальным пунктам
// задаём роли, в которые monitoring не входит
const STAFF: UserRole[] = ["admin", "operator", "viewer"];

type NavItem = { to: string; label: string; end?: boolean; roles: UserRole[] };
const NAV_GROUPS: { label: string; icon: typeof LayoutDashboard; items: NavItem[] }[] = [
  { label: "Обзор", icon: LayoutDashboard, items: [
    { to: "/", label: "Обзор", end: true, roles: STAFF },
    { to: "/monitoring", label: "Мониторинг", roles: ["monitoring", "admin"] },
  ] },
  { label: "Хосты", icon: Monitor, items: [
    { to: "/hosts", label: "ПК", end: true, roles: STAFF },
    { to: "/hosts/printers", label: "Принтеры", roles: STAFF },
  ] },
  { label: "Автоматизация", icon: Workflow, items: [
    { to: "/automation", label: "Плейбуки", roles: EDITORS },
    { to: "/software", label: "ПО", roles: STAFF },
    { to: "/wallpapers", label: "Обои", roles: STAFF },
    { to: "/tasks", label: "Задачи", roles: STAFF },
  ] },
];

export const ADMIN_ITEMS: { to: string; label: string; roles: UserRole[] }[] = [
  { to: "/admin/users", label: "Пользователи", roles: ["admin"] },
  { to: "/admin/ldap", label: "Вход через домен", roles: ["admin"] },
  { to: "/admin/backup", label: "Резервные копии", roles: ["admin"] },
  { to: "/admin/platform", label: "Обновление платформы", roles: ["admin"] },
  { to: "/admin/credentials", label: "Учётные данные", roles: EDITORS },
  { to: "/admin/groups", label: "Группы хостов", roles: EDITORS },
  { to: "/admin/tags", label: "Теги хостов", roles: EDITORS },
  { to: "/admin/agent", label: "Агент и токены", roles: EDITORS },
  { to: "/admin/files", label: "Хранилище установщиков", roles: EDITORS },
];

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150 ${
    isActive ? "bg-blue-600 text-white" : "text-muted-foreground hover:bg-muted hover:text-foreground"
  }`;

const followsLink = (event: MouseEvent<HTMLAnchorElement>) =>
  event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey;

function NavDropdown({ label, icon: Icon, items, active }: {
  label: string;
  icon: typeof LayoutDashboard;
  items: Omit<NavItem, "roles">[];
  active: boolean;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const container = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const { pathname } = useLocation();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open]);

  return (
    <div
      ref={container}
      className="relative"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (!open) return;
        if (event.key === "Escape") {
          event.preventDefault();
          button.current?.focus();
          setOpen(false);
        }
      }}
    >
      <button ref={button} type="button" onClick={() => setOpen((value) => !value)} aria-controls={id} aria-expanded={open}
        className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors ${active ? "bg-blue-600 text-white" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
      >
        <Icon aria-hidden="true" className="h-3.5 w-3.5" />
        {label}
        <ChevronDown aria-hidden="true" className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      <ul id={id} hidden={!open} className="absolute left-0 top-full z-50 mt-1 min-w-[220px] animate-scale-in rounded-xl border border-border bg-surface py-1 shadow-panel-lg">
        {items.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              className={({ isActive }) => `block px-3 py-2 text-sm transition-colors hover:bg-muted focus-visible:bg-muted ${isActive ? "font-medium text-primary" : "text-foreground"}`}
              onClick={(event) => {
                if (!followsLink(event)) return;
                button.current?.focus();
                setOpen(false);
              }}
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Layout() {
  const { user } = useAuth();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const mobileMenu = useRef<HTMLButtonElement>(null);
  function closeMobileMenu() {
    mobileMenu.current?.focus();
    setMenuOpen(false);
  }
  function onMobileFollow(event: MouseEvent<HTMLAnchorElement>) {
    if (followsLink(event)) closeMobileMenu();
  }

  useEffect(() => setMenuOpen(false), [location.pathname]);

  const allowed = (roles?: UserRole[]) => !roles || (user && roles.includes(user.role));
  const navGroups = NAV_GROUPS.map((group) => ({ ...group, items: group.items.filter((item) => allowed(item.roles)) }))
    .filter((group) => group.items.length > 0);
  const groupActive = (group: typeof navGroups[number]) => group.items.some((item) =>
    item.to === "/" ? location.pathname === "/" : location.pathname === item.to || location.pathname.startsWith(`${item.to}/`));
  const adminItems = ADMIN_ITEMS.filter((i) => allowed(i.roles));
  const adminActive = location.pathname.startsWith("/admin");
  // Мониторинг — настенный дисплей (ТВ): страница сама занимает всю высоту под
  // шапкой и управляет своим скроллом, поэтому убираем отступы и ограничение ширины.
  const wallboard = location.pathname === "/monitoring";

  return (
    <TaskPanelProvider>
      <div className="min-h-screen bg-background text-foreground">
        <header
          className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur-md"
          onKeyDown={(event) => {
            if (event.key !== "Escape" || event.defaultPrevented || !menuOpen) return;
            event.preventDefault();
            closeMobileMenu();
          }}
        >
          <div className="mx-auto flex h-14 max-w-[96rem] items-center justify-between gap-4 px-4">
            <div className="flex min-w-0 items-center gap-6">
              <NavLink to="/" end aria-label="Fleet Manager" className="flex shrink-0 items-center gap-2 text-base font-semibold tracking-tight">
                <span className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-600 text-white">
                  <Server className="h-4 w-4" />
                </span>
                <span className="hidden sm:inline">Fleet Manager</span>
              </NavLink>
              <nav aria-label="Основная навигация" className="hidden items-center gap-0.5 lg:flex">
                {navGroups.map((group) => (
                  <NavDropdown key={group.label} label={group.label} icon={group.icon} items={group.items} active={groupActive(group)} />
                ))}
                {adminItems.length > 0 && (
                  <NavDropdown label="Администрирование" icon={Settings} items={adminItems} active={adminActive} />
                )}
              </nav>
            </div>

            <div className="flex shrink-0 items-center gap-1">
              <UserMenu />
              <button ref={mobileMenu} type="button" className="btn-ghost btn-icon lg:hidden" onClick={() => setMenuOpen((v) => !v)} aria-label="Меню" aria-expanded={menuOpen} aria-controls={menuOpen ? "mobile-navigation" : undefined}>
                {menuOpen ? <X className="h-5 w-5" /> : <MenuIcon className="h-5 w-5" />}
              </button>
            </div>
          </div>

          {menuOpen && (
            <nav id="mobile-navigation" aria-label="Основная навигация" className="flex flex-col gap-1 border-t border-border px-4 py-2 lg:hidden">
              {navGroups.map((group) => (
                <div key={group.label} className="flex flex-col gap-1">
                  <p className="flex items-center gap-1.5 px-3 pt-2 text-xs font-medium uppercase tracking-wide text-subtle">
                    <group.icon className="h-3.5 w-3.5" aria-hidden="true" />{group.label}
                  </p>
                  {group.items.map((item) => <NavLink key={item.to} to={item.to} end={item.end} className={linkClass} onClick={onMobileFollow}>{item.label}</NavLink>)}
                </div>
              ))}
              {adminItems.length > 0 && <p className="px-3 pt-2 text-xs font-medium uppercase tracking-wide text-subtle">Администрирование</p>}
              {adminItems.map((item) => (
                <NavLink key={item.to} to={item.to} className={linkClass} onClick={onMobileFollow}>
                  {item.label}
                </NavLink>
              ))}
              {user && <p className="px-3 py-2 text-xs text-muted-foreground">{user.username} · {ROLE_LABELS[user.role]}</p>}
            </nav>
          )}
        </header>

        <main className={wallboard ? "" : "mx-auto max-w-[96rem] px-4 py-6"}>
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </TaskPanelProvider>
  );
}
