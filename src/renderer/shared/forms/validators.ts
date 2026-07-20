/**
 * Composable field validators. Each returns undefined when valid, or a
 * user-readable error string. Compose with `all(...)` to run several in
 * order and stop at the first failure — matches how useForm calls them.
 */
export type Validator<V = unknown> = (value: V, values: object) => string | undefined;

export function all<V>(...validators: Validator<V>[]): Validator<V> {
  return (value, values) => {
    for (const v of validators) {
      const err = v(value, values);
      if (err) return err;
    }
    return undefined;
  };
}

export function required(message = "This field is required"): Validator<unknown> {
  return value => {
    if (value === null || value === undefined) return message;
    if (typeof value === "string" && value.trim() === "") return message;
    if (Array.isArray(value) && value.length === 0) return message;
    return undefined;
  };
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export function email(message = "Enter a valid email address"): Validator<string> {
  return value => (!value || EMAIL_RE.test(value)) ? undefined : message;
}

export function minLength(n: number, message?: string): Validator<string> {
  return value => (!value || value.length >= n) ? undefined : (message ?? `Must be at least ${n} characters`);
}

export function maxLength(n: number, message?: string): Validator<string> {
  return value => (!value || value.length <= n) ? undefined : (message ?? `Must be ${n} characters or fewer`);
}

export function pattern(re: RegExp, message: string): Validator<string> {
  return value => (!value || re.test(value)) ? undefined : message;
}

/** Cross-field validator — e.g. confirm-password. Reads a sibling field from the full values object. */
export function matchesField(otherFieldName: string, message = "Fields do not match"): Validator<unknown> {
  return (value, values) => value === (values as Record<string, unknown>)[otherFieldName] ? undefined : message;
}

export function custom<V>(fn: (value: V, values: object) => boolean, message: string): Validator<V> {
  return (value, values) => fn(value, values) ? undefined : message;
}

/**
 * Password strength — the one validator with an opinion baked in, since
 * every registration form in this app wants the same bar. Length is a
 * separate, composable validator (minLength(8)) so callers can adjust it.
 */
export function passwordStrength(message = "Use at least one letter and one number"): Validator<string> {
  return value => (!value || (/[A-Za-z]/.test(value) && /[0-9]/.test(value))) ? undefined : message;
}
