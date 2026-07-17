import { C } from "../../shared/lib/theme";
import { Component } from "react";
import type { ReactNode } from "react";

interface Props {
  name?: string;
  fallback?: ReactNode;
  children: ReactNode;
}

interface State { error: string | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(e: Error): State {
    return { error: e.message };
  }

  componentDidCatch(e: Error) {
    console.error(`[ErrorBoundary${this.props.name ? ` ${this.props.name}` : ""}]`, e);
  }

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="empty-state" style={{ flex: 1, direction: "ltr" }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke={C.redSoft} strokeWidth="1.5" strokeLinecap="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <h3 style={{ color: C.redSoft }}>
            {this.props.name ? `Error in ${this.props.name}` : "Something went wrong"}
          </h3>
          <p style={{ color: "var(--t4)", fontSize: 13 }}>{this.state.error}</p>
          <button
            onClick={() => this.setState({ error: null })}
            style={{ marginTop: 12, padding: "8px 20px", borderRadius: 8, background: "var(--accent)", color: "#fff", border: "none", cursor: "pointer", fontSize: 13 }}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
