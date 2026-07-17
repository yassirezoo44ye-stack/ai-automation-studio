import { C } from "../../shared/lib/theme";
const AGENT_COLORS = [
  [C.blue,"#1a2040"], [C.purple,"#2a1a40"], [C.green,"#0a2a1e"],
  [C.pink,"#2a0a1e"], [C.orange,"#2a1500"], [C.sky,"#0a1e2a"],
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
