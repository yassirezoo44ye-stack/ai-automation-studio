import type { ReactNode } from "react";
import { GoldButton } from "../gold";

export function SubmitButton({
  loading, disabled, children, loadingText, fullWidth = true,
}: {
  loading: boolean;
  disabled?: boolean;
  children: ReactNode;
  loadingText?: ReactNode;
  fullWidth?: boolean;
}) {
  return (
    <GoldButton type="submit" disabled={loading || disabled} style={fullWidth ? { width: "100%" } : undefined}>
      {loading ? (loadingText ?? "Working…") : children}
    </GoldButton>
  );
}
