import { memo, useState } from "react";
import { FormField } from "./FormField";
import type { FieldBinding } from "../../forms/useForm";

export interface PasswordFieldProps extends FieldBinding<string> {
  label: string;
  required?: boolean;
  hint?: string;
  placeholder?: string;
  autoComplete?: "current-password" | "new-password";
  autoFocus?: boolean;
}

export const PasswordField = memo(function PasswordField({
  name, value, onChange, onBlur, error, "aria-invalid": ariaInvalid, "aria-describedby": describedBy,
  inputRef, label, required, hint, placeholder, autoComplete = "current-password", autoFocus,
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  return (
    <FormField name={name} label={label} required={required} error={error} hint={hint}>
      <div style={{ position: "relative" }}>
        <input
          id={name}
          name={name}
          type={visible ? "text" : "password"}
          className="g-input"
          style={{ paddingRight: 40 }}
          value={value}
          onChange={e => onChange({ target: { value: e.target.value } })}
          onBlur={onBlur}
          placeholder={placeholder}
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          required={required}
          aria-invalid={ariaInvalid}
          aria-describedby={describedBy}
          ref={inputRef as React.Ref<HTMLInputElement>}
        />
        <button
          type="button"
          className="g-password-toggle"
          onClick={() => setVisible(v => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          tabIndex={-1}
        >
          {visible ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" /><line x1="1" y1="1" x2="23" y2="23" /></svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>
          )}
        </button>
      </div>
    </FormField>
  );
});
