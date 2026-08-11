import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation() as { state?: { draftPrompt?: string } };

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register({
        email,
        password,
        full_name: fullName,
        organization_name: orgName.trim() || undefined,
      });
      navigate("/dashboard", { state: location.state });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page">
      <div className="auth-card">
        <h1>Create your account</h1>
        {error && <div className="error-banner">{error}</div>}
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="full_name">Full name</label>
            <input
              id="full_name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
              autoComplete="name"
            />
          </div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
            />
          </div>
          <div className="field">
            <label htmlFor="org_name">Workspace name (optional)</label>
            <input
              id="org_name"
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              placeholder="Acme Inc"
              autoComplete="organization"
            />
          </div>
          <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={submitting}>
            {submitting ? "Creating account…" : "Create account"}
          </button>
        </form>
        <p className="switch-link">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>
    </div>
  );
}
