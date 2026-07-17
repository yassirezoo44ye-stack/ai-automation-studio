// react-markdown component map — lives apart from CopyButton.tsx so that
// file exports only components (react-refresh/only-export-components).
import { CopyButton } from "./CopyButton";

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
