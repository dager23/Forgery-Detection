import clsx from "clsx";
import {
  FileStack,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Monitor,
  Moon,
  ScanLine,
  Sun,
  UserCog,
  X,
} from "lucide-react";
import { useState } from "react";
import { Navigate, NavLink, Outlet, useLocation } from "react-router";
import { useAuth } from "../auth";
import { useTheme, type ThemePref } from "../theme";
import { Logo, Spinner } from "./ui";

const NAV = [
  { to: "/app", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/app/verify", label: "Verify document", icon: ScanLine },
  { to: "/app/history", label: "History", icon: History },
  { to: "/app/templates", label: "Templates", icon: FileStack },
];

export function ThemeSwitch() {
  const [pref, setPref] = useTheme();
  const opts: { v: ThemePref; icon: typeof Sun; label: string }[] = [
    { v: "light", icon: Sun, label: "Light" },
    { v: "system", icon: Monitor, label: "System" },
    { v: "dark", icon: Moon, label: "Dark" },
  ];
  return (
    <div className="inline-flex rounded-lg border border-slate-200 p-0.5 dark:border-slate-800" role="radiogroup" aria-label="Theme">
      {opts.map(({ v, icon: Icon, label }) => (
        <button
          key={v}
          role="radio"
          aria-checked={pref === v}
          title={label}
          onClick={() => setPref(v)}
          className={clsx(
            "rounded-md p-1.5 transition-colors",
            pref === v ? "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-white" : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200",
          )}
        >
          <Icon className="size-4" />
        </button>
      ))}
    </div>
  );
}

function NavItems({ admin, onNavigate }: { admin: boolean; onNavigate?: () => void }) {
  const items = admin ? [...NAV, { to: "/app/admin/users", label: "Users", icon: UserCog }] : NAV;
  return (
    <nav className="space-y-1">
      {items.map(({ to, label, icon: Icon, ...rest }) => (
        <NavLink
          key={to}
          to={to}
          end={"end" in rest}
          onClick={onNavigate}
          className={({ isActive }) =>
            clsx(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              isActive
                ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-100",
            )
          }
        >
          <Icon className="size-4.5" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

export default function AppShell() {
  const { user, loading, logout } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);

  if (loading) return <Spinner label="Checking your session..." />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;

  const userBlock = (
    <div className="border-t border-slate-200 pt-4 dark:border-slate-800">
      <div className="mb-3 flex items-center gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-600 text-sm font-semibold text-white">
          {user.name.slice(0, 1).toUpperCase()}
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-slate-900 dark:text-white">{user.name}</div>
          <div className="truncate text-xs muted">
            {user.email}
            {user.role === "admin" && " - admin"}
          </div>
        </div>
      </div>
      <div className="flex items-center justify-between">
        <ThemeSwitch />
        <button
          onClick={logout}
          className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
        >
          <LogOut className="size-4" /> Sign out
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-dvh lg:flex">
      {/* desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col justify-between border-r border-slate-200 bg-white px-4 py-5 lg:flex dark:border-slate-800 dark:bg-slate-900">
        <div>
          <NavLink to="/" className="mb-8 block px-2">
            <Logo className="text-lg text-slate-900 dark:text-white" />
          </NavLink>
          <NavItems admin={user.role === "admin"} />
        </div>
        {userBlock}
      </aside>

      {/* mobile top bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur lg:hidden dark:border-slate-800 dark:bg-slate-900/90">
        <NavLink to="/">
          <Logo className="text-slate-900 dark:text-white" />
        </NavLink>
        <button onClick={() => setOpen(true)} aria-label="Open menu" className="rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800">
          <Menu className="size-5" />
        </button>
      </header>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 right-0 flex w-72 flex-col justify-between bg-white p-5 shadow-xl dark:bg-slate-900">
            <div>
              <div className="mb-6 flex items-center justify-between">
                <Logo className="text-slate-900 dark:text-white" />
                <button onClick={() => setOpen(false)} aria-label="Close menu" className="rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800">
                  <X className="size-5" />
                </button>
              </div>
              <NavItems admin={user.role === "admin"} onNavigate={() => setOpen(false)} />
            </div>
            {userBlock}
          </div>
        </div>
      )}

      <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
        <div className="mx-auto max-w-7xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== "admin") return <Navigate to="/app" replace />;
  return <>{children}</>;
}
