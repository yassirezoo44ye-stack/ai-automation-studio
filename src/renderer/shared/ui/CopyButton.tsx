import { useState } from "react";
import { useTranslation } from "react-i18next";
import { copyText } from "../utils/clipboard";

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const { t } = useTranslation("common");
  async function copy() {
    setFailed(false); setCopied(false);
    try {
      await copyText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { setFailed(true); }
  }
  return (
    <button type="button" onClick={() => void copy()} className={`copy-btn${copied ? " copied" : ""}`} aria-label={failed ? t("actions.copyFailed") : copied ? "Copied" : "Copy code"}>
      {failed ? t("actions.copyFailed") : copied
        ? <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg> Copied</>
        : <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy</>}
    </button>
  );
}
