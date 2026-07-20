import { memo } from "react";
import { TextField, type TextFieldProps } from "./TextField";

export const EmailField = memo(function EmailField(props: Omit<TextFieldProps, "type">) {
  return <TextField {...props} type="email" />;
});
