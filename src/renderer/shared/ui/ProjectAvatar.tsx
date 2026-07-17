import { C } from "../../shared/lib/theme";
export function ProjectAvatar({ name, size = 42 }: { name: string; size?: number }) {
  const colors = [C.blue,"#8b5cf6",C.green,C.amber,C.redSoft,"#06b6d4","#ec4899"];
  const color  = colors[name.charCodeAt(0) % colors.length];
  return (
    <div style={{ width: size, height: size, borderRadius: Math.round(size * 0.28), background: color + "22", border: `1px solid ${color}35`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: Math.round(size * 0.4), fontWeight: 700, color, flexShrink: 0, letterSpacing: "-0.5px" }}>
      {name.slice(0, 2).toUpperCase()}
    </div>
  );
}
