import type { ReactNode } from "react";

/**
 * Label + input slot + error + hint, wired for a11y: the input passed as
 * children must carry the same `id` as `htmlFor`, and read `describedBy`
 * for its aria-describedby (useForm's register() already returns a
 * matching aria-describedby — this just renders the element it points at).
 */
export function FormField({
  name, label, required, error, hint, children,
}: {
  name: string;
  label: string;
  required?: boolean;
  error?: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="g-field">
      <label className="g-label" htmlFor={name}>
        <span>{label}{required && <span className="g-label__required" aria-hidden="true"> *</span>}</span>
      </label>
      {children}
      {error && (
        <p className="g-field-error" id={`${name}-error`} role="alert">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
            <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          {error}
        </p>
      )}
      {!error && hint && <p className="g-field-hint" id={`${name}-hint`}>{hint}</p>}
    </div>
  );
}
