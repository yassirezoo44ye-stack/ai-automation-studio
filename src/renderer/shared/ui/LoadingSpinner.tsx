interface Props {
  size?: number;
  label?: string;
  fullPage?: boolean;
}

export function LoadingSpinner({ size = 32, label = "Loading…", fullPage = false }: Props) {
  const spinner = (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
      <svg
        width={size} height={size}
        viewBox="0 0 24 24" fill="none" stroke="var(--accent)"
        strokeWidth="2" strokeLinecap="round"
        style={{ animation: "spin 0.9s linear infinite" }}
      >
        <circle cx="12" cy="12" r="10" strokeOpacity="0.2" />
        <path d="M12 2a10 10 0 0 1 10 10" />
      </svg>
      {label && <span style={{ fontSize: 13, color: "var(--t4)" }}>{label}</span>}
    </div>
  );

  if (fullPage) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
        {spinner}
      </div>
    );
  }
  return spinner;
}
