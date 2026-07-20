import { memo } from "react";

export interface CheckboxProps {
  name: string;
  checked: boolean;
  onChange: (e: { target: { checked: boolean } }) => void;
  label: string;
}

export const Checkbox = memo(function Checkbox({ name, checked, onChange, label }: CheckboxProps) {
  return (
    <label className="g-checkbox-row" htmlFor={name}>
      <input
        id={name}
        name={name}
        type="checkbox"
        checked={checked}
        onChange={e => onChange({ target: { checked: e.target.checked } })}
      />
      {label}
    </label>
  );
});
