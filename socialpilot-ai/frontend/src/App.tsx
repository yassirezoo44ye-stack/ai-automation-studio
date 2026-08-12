import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { TopBar } from "./components/TopBar";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LandingPage } from "./pages/LandingPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ContentStrategyPage } from "./pages/content/ContentStrategyPage";
import { ContentGeneratePage } from "./pages/content/ContentGeneratePage";
import { ContentLibraryPage } from "./pages/content/ContentLibraryPage";

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <TopBar />
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <DashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/content/strategy"
            element={
              <ProtectedRoute>
                <ContentStrategyPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/content/generate"
            element={
              <ProtectedRoute>
                <ContentGeneratePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/content/library"
            element={
              <ProtectedRoute>
                <ContentLibraryPage />
              </ProtectedRoute>
            }
          />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
