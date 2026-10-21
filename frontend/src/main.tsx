import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router";
import { ApiError } from "./api";
import { AuthProvider } from "./auth";
import AppShell, { RequireAdmin } from "./components/AppShell";
import "./index.css";
import AnalysisPage from "./pages/Analysis";
import AuthPage from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import HistoryPage from "./pages/History";
import Landing from "./pages/Landing";
import NotFound from "./pages/NotFound";
import TemplateEditor from "./pages/TemplateEditor";
import Templates from "./pages/Templates";
import Users from "./pages/Users";
import Verify from "./pages/Verify";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<AuthPage mode="login" />} />
            <Route path="/register" element={<AuthPage mode="register" />} />
            <Route path="/app" element={<AppShell />}>
              <Route index element={<Dashboard />} />
              <Route path="verify" element={<Verify />} />
              <Route path="history" element={<HistoryPage />} />
              <Route path="analyses/:id" element={<AnalysisPage />} />
              <Route path="templates" element={<Templates />} />
              <Route path="templates/:id" element={<TemplateEditor />} />
              <Route
                path="admin/users"
                element={
                  <RequireAdmin>
                    <Users />
                  </RequireAdmin>
                }
              />
              <Route path="*" element={<NotFound inApp />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
