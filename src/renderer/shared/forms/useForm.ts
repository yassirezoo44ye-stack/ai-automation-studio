/**
 * useForm — field values, per-field validation, touched/dirty tracking,
 * and a submit handler that validates before ever calling your onValid.
 *
 * Deliberately does NOT own network/submission state (loading, retry,
 * abort) — that's useAsyncSubmit's job. Wire them together:
 *
 *   const submit = useAsyncSubmit(values => api.login(values));
 *   const form = useForm({ initialValues, validators, onValid: submit.run });
 *   <form onSubmit={form.handleSubmit}>
 *     <TextField {...form.register("email")} />
 *     <SubmitButton loading={submit.isSubmitting}>Sign in</SubmitButton>
 *   </form>
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Validator } from "./validators";

export type Touched<T> = Partial<Record<keyof T, boolean>>;
export type Errors<T> = Partial<Record<keyof T, string>>;

export interface UseFormOptions<T extends object> {
  initialValues: T;
  /** One validator per field. Cross-field validators (matchesField) receive the full values object. */
  validators?: Partial<{ [K in keyof T]: Validator<T[K]> }>;
  /** Called only once every field passes validation. */
  onValid: (values: T) => void | Promise<void>;
}

export interface FieldBinding<V> {
  name: string;
  value: V;
  onChange: (e: { target: { value: V } }) => void;
  onBlur: () => void;
  error?: string;
  touched: boolean;
  "aria-invalid": boolean;
  "aria-describedby": string | undefined;
  inputRef: (el: HTMLElement | null) => void;
}

export interface UseFormResult<T extends object> {
  values: T;
  errors: Errors<T>;
  touched: Touched<T>;
  dirty: boolean;
  isValid: boolean;
  setValue: <K extends keyof T>(name: K, value: T[K]) => void;
  setTouched: (name: keyof T) => void;
  validateAll: () => boolean;
  reset: (nextValues?: T) => void;
  handleSubmit: (e?: { preventDefault?: () => void }) => void;
  /** Field-binding helper — the useField() ergonomics without a second hook fighting over the same state. */
  register: <K extends keyof T>(name: K) => FieldBinding<T[K]>;
  /** For checkbox/toggle fields, whose native onChange reads `checked` not `value`. */
  registerCheckbox: (name: keyof T) => { name: string; checked: boolean; onChange: (e: { target: { checked: boolean } }) => void };
}

export function useForm<T extends object>(options: UseFormOptions<T>): UseFormResult<T> {
  const { initialValues, validators, onValid } = options;
  const [values, setValues]   = useState<T>(initialValues);
  const [errors, setErrors]   = useState<Errors<T>>({});
  const [touched, setTouchedState] = useState<Touched<T>>({});
  const fieldRefs = useRef<Map<keyof T, HTMLElement>>(new Map());
  const validatorsRef = useRef(validators);
  useEffect(() => { validatorsRef.current = validators; });

  const dirty = useMemo(() => JSON.stringify(values) !== JSON.stringify(initialValues), [values, initialValues]);

  const validateField = useCallback((name: keyof T, currentValues: T): string | undefined => {
    const validator = validatorsRef.current?.[name];
    return validator ? validator(currentValues[name], currentValues) : undefined;
  }, []);

  const setValue = useCallback(<K extends keyof T>(name: K, value: T[K]) => {
    setValues(prev => {
      const next = { ...prev, [name]: value };
      // Re-validate live only once the field has already been touched —
      // avoids flashing "required" errors before the user has typed anything.
      setErrors(prevErrors => {
        if (!touched[name]) return prevErrors;
        const err = validateField(name, next);
        return { ...prevErrors, [name]: err };
      });
      return next;
    });
  }, [touched, validateField]);

  const setTouched = useCallback((name: keyof T) => {
    setTouchedState(prev => ({ ...prev, [name]: true }));
    setValues(current => {
      setErrors(prevErrors => ({ ...prevErrors, [name]: validateField(name, current) }));
      return current;
    });
  }, [validateField]);

  const validateAll = useCallback((): boolean => {
    let firstInvalid: keyof T | null = null;
    const nextErrors: Errors<T> = {};
    const nextTouched: Touched<T> = {};
    for (const key of Object.keys(values) as (keyof T)[]) {
      nextTouched[key] = true;
      const err = validateField(key, values);
      if (err) {
        nextErrors[key] = err;
        if (!firstInvalid) firstInvalid = key;
      }
    }
    setErrors(nextErrors);
    setTouchedState(nextTouched);
    if (firstInvalid) {
      const el = fieldRefs.current.get(firstInvalid);
      el?.focus();
      // Not implemented in jsdom (test environment) — real browsers all support it.
      el?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    }
    return firstInvalid === null;
  }, [values, validateField]);

  const reset = useCallback((nextValues?: T) => {
    setValues(nextValues ?? initialValues);
    setErrors({});
    setTouchedState({});
  }, [initialValues]);

  const handleSubmit = useCallback((e?: { preventDefault?: () => void }) => {
    e?.preventDefault?.();
    if (validateAll()) void onValid(values);
  }, [validateAll, values, onValid]);

  const register = useCallback(<K extends keyof T>(name: K): FieldBinding<T[K]> => ({
    name: String(name),
    value: values[name],
    onChange: e => setValue(name, e.target.value),
    onBlur: () => setTouched(name),
    error: touched[name] ? errors[name] : undefined,
    touched: !!touched[name],
    "aria-invalid": !!(touched[name] && errors[name]),
    "aria-describedby": touched[name] && errors[name] ? `${String(name)}-error` : undefined,
    inputRef: el => { if (el) fieldRefs.current.set(name, el); else fieldRefs.current.delete(name); },
  }), [values, errors, touched, setValue, setTouched]);

  const registerCheckbox = useCallback((name: keyof T) => ({
    name: String(name),
    checked: !!values[name],
    onChange: (e: { target: { checked: boolean } }) => setValue(name, e.target.checked as T[keyof T]),
  }), [values, setValue]);

  const isValid = useMemo(
    () => (Object.keys(values) as (keyof T)[]).every(key => !validateField(key, values)),
    [values, validateField],
  );

  return { values, errors, touched, dirty, isValid, setValue, setTouched, validateAll, reset, handleSubmit, register, registerCheckbox };
}
