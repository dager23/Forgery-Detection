import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { useAuth } from "../auth";
import { Button, ErrorNote, Logo } from "../components/ui";

export default function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next");
  const dest = next && next.startsWith("/app") ? next : "/app";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={dest} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email.trim(), password);
      else await register(name.trim(), email.trim(), password);
      navigate(dest, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const isLogin = mode === "login";
  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-brand-600 via-brand-700 to-brand-900 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -top-24 -right-24 size-80 rounded-full bg-white/10" />
        <div className="absolute bottom-10 -left-20 size-64 rounded-full bg-gradient-to-tr from-sky-400/30 to-fuchsia-400/20" />
        <Link to="/" className="relative">
          <Logo className="text-xl [&_span_span]:text-brand-200" />
        </Link>
        <div className="relative">
          <h2 className="text-4xl leading-tight font-bold">
            Every stamp, signature
            <br />
            and digit, checked.
          </h2>
          <p className="mt-4 max-w-md text-brand-100">
            Upload a certificate or ID and get an explainable verdict backed by eight forensic tests, from
            metadata to deep learning.
          </p>
        </div>
        <p className="relative text-sm text-brand-200">DocAuth v2</p>
      </div>

      <div className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <Link to="/" className="mb-10 inline-block lg:hidden">
            <Logo className="text-xl text-slate-900 dark:text-white" />
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">
            {isLogin ? "Welcome back" : "Create your account"}
          </h1>
          <p className="mt-1 text-sm muted">
            {isLogin ? "Sign in to verify documents." : "It takes less than a minute."}
          </p>

          <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
            {!isLogin && (
              <div>
                <label htmlFor="name" className="label">
                  Full name
                </label>
                <input id="name" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
              </div>
            )}
            <div>
              <label htmlFor="email" className="label">
                Email
              </label>
              <input
                id="email"
                type="email"
                className="input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
                autoFocus
              />
            </div>
            <div>
              <label htmlFor="password" className="label">
                Password
              </label>
              <input
                id="password"
                type="password"
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={isLogin ? "current-password" : "new-password"}
                required
              />
              {!isLogin && <p className="mt-1.5 text-xs muted">At least 8 characters, mixing letters with numbers or symbols.</p>}
            </div>
            <ErrorNote error={error} />
            <Button type="submit" loading={busy} className="w-full py-2.5">
              {isLogin ? "Sign in" : "Create account"}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm muted">
            {isLogin ? "New to DocAuth? " : "Already have an account? "}
            <Link
              to={`${isLogin ? "/register" : "/login"}${next ? `?next=${encodeURIComponent(next)}` : ""}`}
              className="font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400"
            >
              {isLogin ? "Create an account" : "Sign in"}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
