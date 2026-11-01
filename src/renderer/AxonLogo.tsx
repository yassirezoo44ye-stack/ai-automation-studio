import type React from "react";
import FlowMark from "./FlowMark";

interface Props {
  size?: number;
  style?: React.CSSProperties;
}

// Kept for existing imports; renders the Flow brand mark.
export default function AxonLogo({ size = 48, style }: Props) {
  return <FlowMark size={size} style={style} />;
}
