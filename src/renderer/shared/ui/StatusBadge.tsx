import { S, BADGE_STYLE, type StatusBadgeKind } from "../../styles/theme";

export function StatusBadge({ kind, label }: { kind: StatusBadgeKind; label: string }) {
  return <span style={{ ...S.badge, ...BADGE_STYLE[kind] }}><span style={S.dot} />{label}</span>;
}
