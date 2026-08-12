import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function TopBar() {
  const { isAuthenticated, user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/");
  };

  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <span className="brand-mark" aria-hidden />
        SocialPilot AI
      </Link>
      <nav className="nav-actions">
        {isAuthenticated ? (
          <>
            <Link to="/dashboard" className="btn btn-ghost">
              Dashboard
            </Link>
            <Link to="/content/strategy" className="btn btn-ghost">
              Strategy
            </Link>
            <Link to="/content/generate" className="btn btn-ghost">
              Generate
            </Link>
            <Link to="/content/library" className="btn btn-ghost">
              Library
            </Link>
            <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>{user?.email}</span>
            <button className="btn btn-ghost" onClick={handleLogout}>
              Log out
            </button>
          </>
        ) : (
          <>
            <Link to="/login" className="btn btn-ghost">
              Log in
            </Link>
            <Link to="/register" className="btn btn-primary">
              Get started
            </Link>
          </>
        )}
      </nav>
    </header>
  );
}
