import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { api, ApiError, setUnauthorizedHandler, type User } from "./api";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (name: string, email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();

  const me = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api.me();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 5 * 60_000,
    retry: false,
  });

  // A 401 from any API call means the session expired: drop cached data and go to login.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      qc.setQueryData(["me"], null);
      if (location.pathname.startsWith("/app")) {
        navigate(`/login?next=${encodeURIComponent(location.pathname)}`, { replace: true });
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [qc, navigate, location.pathname]);

  const login = useCallback(
    async (email: string, password: string) => {
      const { user } = await api.login(email, password);
      qc.clear();
      qc.setQueryData(["me"], user);
      return user;
    },
    [qc],
  );

  const register = useCallback(
    async (name: string, email: string, password: string) => {
      const { user } = await api.register(name, email, password);
      qc.clear();
      qc.setQueryData(["me"], user);
      return user;
    },
    [qc],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      qc.clear();
      qc.setQueryData(["me"], null);
      navigate("/", { replace: true });
    }
  }, [qc, navigate]);

  const value = useMemo<AuthState>(
    () => ({ user: me.data ?? null, loading: me.isPending, login, register, logout }),
    [me.data, me.isPending, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
