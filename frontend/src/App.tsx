import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, UserRole } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import { queryClient } from "./api/queries";
import { ToastProvider } from "./components/ui/Toast";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import HostsPage from "./pages/hosts/HostsPage";
import Software from "./pages/Software";
import Automation from "./pages/Automation";
import Tasks from "./pages/Tasks";
import Users from "./pages/admin/Users";
import Credentials from "./pages/admin/Credentials";
import Groups from "./pages/admin/Groups";
import Agent from "./pages/admin/Agent";
import Files from "./pages/admin/Files";

const EDITORS: UserRole[] = ["admin", "operator"];

const guard = (roles: UserRole[], element: JSX.Element) => <ProtectedRoute roles={roles}>{element}</ProtectedRoute>;

export default function App() {
  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <AuthProvider>
            <ToastProvider>
              <Routes>
                <Route path="/login" element={<Login />} />
                <Route
                  element={
                    <ProtectedRoute>
                      <Layout />
                    </ProtectedRoute>
                  }
                >
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/hosts" element={<HostsPage />} />
                  <Route path="/software" element={<Software />} />
                  <Route path="/automation" element={guard(EDITORS, <Automation />)} />
                  <Route path="/tasks" element={<Tasks />} />
                  <Route path="/admin/users" element={guard(["admin"], <Users />)} />
                  <Route path="/admin/credentials" element={guard(EDITORS, <Credentials />)} />
                  <Route path="/admin/groups" element={guard(EDITORS, <Groups />)} />
                  <Route path="/admin/agent" element={guard(EDITORS, <Agent />)} />
                  <Route path="/admin/files" element={guard(EDITORS, <Files />)} />
                  {/* Старые адреса — закладки пользователей продолжают работать */}
                  <Route path="/playbooks" element={<Navigate to="/automation" replace />} />
                  <Route path="/hardware" element={<Navigate to="/hosts" replace />} />
                  <Route path="/keystore" element={<Navigate to="/admin/credentials" replace />} />
                  <Route path="/users" element={<Navigate to="/admin/users" replace />} />
                  <Route path="/tokens" element={<Navigate to="/admin/agent" replace />} />
                  <Route path="/installers" element={<Navigate to="/admin/files" replace />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
              </Routes>
            </ToastProvider>
          </AuthProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </BrowserRouter>
  );
}
