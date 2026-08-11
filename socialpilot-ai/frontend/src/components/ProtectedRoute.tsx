import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isBootstrapping } = useAuth();

  if (isBootstrapping) {
    return <div className="center-loading">Loading…</div>;
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
