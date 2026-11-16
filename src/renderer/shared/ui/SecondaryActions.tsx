import { Children, cloneElement, isValidElement, useEffect, useRef, useState, type ReactNode, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import "./SecondaryActions.css";

function textContent(node: ReactNode): string {
  return Children.toArray(node).map(child => {
    if (typeof child === "string" || typeof child === "number") return String(child);
    if (isValidElement<{ children?: ReactNode }>(child) && child.type !== "svg") return textContent(child.props.children);
    return "";
  }).join("");
}

function labeledAction(child: ReactNode): ReactNode {
  if (!isValidElement<{ title?: string; children?: ReactNode; style?: CSSProperties; "aria-label"?: string }>(child) || child.type !== "button") return child;
  const { title, children, style } = child.props;
  if (!title || /\p{L}/u.test(textContent(children))) return child;
  return cloneElement(child, { "aria-label": child.props["aria-label"] ?? title,
    style: { ...style, width: "auto", height: "auto", display: "inline-flex", gap: 6, padding: "6px 10px" } }, children, <span>{title}</span>);
}

/** In-flow disclosure: secondary controls stay reachable without clipped overlays. */
export function SecondaryActions({ children, label }: { children: ReactNode; label?: string }) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      const details = ref.current;
      if (details?.open && event.target instanceof Node && !details.contains(event.target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      const details = ref.current;
      if (event.key === "Escape" && details?.open && event.target instanceof Node && details.contains(event.target)) {
        event.stopPropagation();
        setOpen(false);
        details.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, []);
  return <details className="flow-secondary-actions" ref={ref} open={open}>
    <summary onClick={event => { event.preventDefault(); setOpen(value => !value); }}>{label ?? t("actions.more", { defaultValue: "More" })} <span aria-hidden="true">⋯</span></summary>
    <div className="flow-secondary-actions__content" hidden={!open}>{Children.map(children, labeledAction)}</div>
  </details>;
}
