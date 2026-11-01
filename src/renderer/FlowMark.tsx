import type React from "react";

interface Props {
  size?: number;
  style?: React.CSSProperties;
}

/** Flow brand mark: an "F" drawn as a workflow — trigger ring → step node → output node. */
export default function FlowMark({ size = 32, style }: Props) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" role="img" aria-label="Flow" style={style}>
      <rect width="120" height="120" rx="30" fill="#0B1220" />
      <path d="M40 82 V46 Q40 34 52 34 H74" stroke="#FFFFFF" strokeWidth="11" fill="none" strokeLinecap="round" />
      <path d="M40 62 H58" stroke="#FFFFFF" strokeWidth="11" fill="none" strokeLinecap="round" />
      <circle cx="40" cy="94" r="6" fill="none" stroke="#FFFFFF" strokeWidth="4" />
      <circle cx="72" cy="62" r="7" fill="#FFFFFF" />
      <circle cx="88" cy="34" r="8.5" fill="#FF7A2F" />
    </svg>
  );
}
