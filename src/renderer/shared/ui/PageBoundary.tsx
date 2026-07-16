import { Component } from "react";
import type { ReactNode } from "react";
import { S } from "../../styles/theme";

export class PageBoundary extends Component<{ name: string; children: ReactNode }, { err: string | null }> {
  state = { err: null };
  static getDerivedStateFromError(e: Error) { return { err: e.message }; }
  componentDidCatch(e: Error) { console.error("PageBoundary:", e); }
  render() {
    if (this.state.err) return (
      <div className="empty-state" style={{ flex: 1, direction: "ltr" }}>
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#FF5252" strokeWidth="1.5" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        <h3 style={{ color: "#FF5252" }}>Error loading {this.props.name}</h3>
        <p>{this.state.err}</p>
        <button onClick={() => this.setState({ err: null })} style={S.btnPrimary}>Retry</button>
      </div>
    );
    return this.props.children;
  }
}
