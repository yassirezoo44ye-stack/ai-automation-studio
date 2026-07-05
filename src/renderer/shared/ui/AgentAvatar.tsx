export const AGENT_COLORS = [
  ["#6c8ef7","#1a2040"], ["#a78bfa","#2a1a40"], ["#34d399","#0a2a1e"],
  ["#f472b6","#2a0a1e"], ["#fb923c","#2a1500"], ["#38bdf8","#0a1e2a"],
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
