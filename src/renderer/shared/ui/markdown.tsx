import { isValidElement } from "react";
import type { Components } from "react-markdown";
import { CopyButton } from "./CopyButton";

/** react-markdown component overrides — adds a copy button to code blocks. */
export const MD_COMPONENTS: Components = {
  pre: ({ children, ...props }) => {
    const codeProps = isValidElement(children)
      ? (children.props as { children?: unknown })
      : undefined;
    const text = typeof codeProps?.children === "string" ? codeProps.children : "";
    return (
      <div className="code-block-wrap">
        <pre {...props}>{children}</pre>
        {text && <CopyButton text={text} />}
      </div>
    );
  },
};
