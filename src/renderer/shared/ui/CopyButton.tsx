import { useState } from "react";

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }
  return (
    <button onClick={copy} className={`copy-btn${copied ? " copied" : ""}`} aria-label={copied ? "Copied" : "Copy code"}>
      {copied
        ? <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg> Copied</>
        : <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy</>}
    </button>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const MD_COMPONENTS: Record<string, React.ComponentType<any>> = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  pre: ({ children, ...props }: any) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const codeEl = (children as any)?.props as { children?: string } | undefined;
    const text = typeof codeEl?.children === "string" ? codeEl.children : "";
    return (
      <div className="code-block-wrap">
        <pre {...props}>{children}</pre>
        {text && <CopyButton text={text} />}
      </div>
    );
  },
};
