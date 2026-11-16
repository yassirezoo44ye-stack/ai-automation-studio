import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import "./WorkspaceDetails.css";

/** Optional workspace context; core work, errors and approvals stay outside. */
export function WorkspaceDetails({ kind, children, expanded, onExpandedChange }: { kind: "summary" | "examples" | "setup" | "technical" | "activity"; children: ReactNode; expanded?: boolean; onExpandedChange?: (open: boolean) => void }) {
  const { t } = useTranslation("common");
  const [internalOpen, setInternalOpen] = useState(false);
  const open = expanded ?? internalOpen;
  const [hasOpened, setHasOpened] = useState(false);
  // Preserve form drafts after the first expansion, without loading them early.
  if (open && !hasOpened) setHasOpened(true);
  const toggle = () => { setInternalOpen(!open); onExpandedChange?.(!open); };
  return <details className="workspace-details" open={open}>
    <summary onClick={event => { event.preventDefault(); toggle(); }}>{t(`workspaceDetails.${kind}`)}</summary>
    {(open || hasOpened) && <div className="workspace-details__body" hidden={!open}>{children}</div>}
  </details>;
}
