import { memo } from "react";
import { FormField } from "./FormField";
import type { FieldBinding } from "../../forms/useForm";

export interface TextFieldProps extends FieldBinding<string> {
  label: string;
  required?: boolean;
  hint?: string;
  type?: "text" | "email" | "tel" | "url";
  placeholder?: string;
  autoComplete?: string;
  autoFocus?: boolean;
}

/** Memoized: re-renders only when this field's own binding/props change, not on every keystroke in a sibling field. */
export const TextField = memo(function TextField({
  name, value, onChange, onBlur, error, "aria-invalid": ariaInvalid, "aria-describedby": describedBy,
  inputRef, label, required, hint, type = "text", placeholder, autoComplete, autoFocus,
}: TextFieldProps) {
  return (
    <FormField name={name} label={label} required={required} error={error} hint={hint}>
      <input
        id={name}
        name={name}
        type={type}
        className="g-input"
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
    </FormField>
  );
});
