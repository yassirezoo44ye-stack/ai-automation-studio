const AGENT_COLORS = [
  ["#FFD700","#26200a"], ["#E8C87D","#241d0e"], ["#00C853","#0a2a1e"],
  ["#E0A899","#2a1510"], ["#FFB300","#2a1c00"], ["#D6D6D6","#222222"],
];

export function AgentAvatar({ name, size = 44 }: { name: string; size?: number }) {
  const idx = name.charCodeAt(0) % AGENT_COLORS.length;
  const [fg, bg] = AGENT_COLORS[idx];
  return (
    <div style={{ width: size, height: size, borderRadius: size * 0.27, background: bg, border: `1.5px solid ${fg}33`,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: size * 0.38, fontWeight: 700, color: fg, flexShrink: 0 }}>
      {name.charAt(0).toUpperCase()}
    </div>
  );
}
