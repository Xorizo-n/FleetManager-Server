import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Hosts from "./pages/Hosts";
import Software from "./pages/Software";
import Playbooks from "./pages/Playbooks";
import Tasks from "./pages/Tasks";
import KeyStore from "./pages/KeyStore";
import Users from "./pages/Users";
import EnrollmentTokens from "./pages/EnrollmentTokens";
import Hardware from "./pages/Hardware";

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
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
              <Route path="/hosts" element={<Hosts />} />
              <Route path="/software" element={<Software />} />
              <Route path="/playbooks" element={<ProtectedRoute roles={["admin", "operator"]}><Playbooks /></ProtectedRoute>} />
              <Route path="/tasks" element={<Tasks />} />
              <Route path="/keystore" element={<KeyStore />} />
              <Route path="/users" element={<ProtectedRoute roles={["admin"]}><Users /></ProtectedRoute>} />
              <Route path="/tokens" element={<ProtectedRoute roles={["admin"]}><EnrollmentTokens /></ProtectedRoute>} />
              <Route path="/hardware" element={<Hardware />} />
            </Route>
          </Routes>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}
