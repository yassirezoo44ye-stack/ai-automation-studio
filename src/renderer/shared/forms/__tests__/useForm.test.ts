import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { useForm } from "../useForm";
import { all, required, email, matchesField } from "../validators";

interface Values { name: string; email: string; confirm: string }

function setup(onValid = vi.fn()) {
  return renderHook(() => useForm<Values>({
    initialValues: { name: "", email: "", confirm: "" },
    validators: {
      name: required("Name required"),
      email: all(required("Email required"), email()),
      confirm: matchesField("email", "Must match email"),
    },
    onValid,
  }));
}

describe("useForm", () => {
  it("starts clean: not dirty, no errors shown, values match initialValues", () => {
    const { result } = setup();
    expect(result.current.dirty).toBe(false);
    expect(result.current.errors).toEqual({});
    expect(result.current.values).toEqual({ name: "", email: "", confirm: "" });
  });

  it("setValue updates the value and marks the form dirty", () => {
    const { result } = setup();
    act(() => result.current.setValue("name", "Ada"));
    expect(result.current.values.name).toBe("Ada");
    expect(result.current.dirty).toBe(true);
  });

  it("does not show a field's error until it has been touched (blurred) or the whole form validated", () => {
    const { result } = setup();
    act(() => result.current.setValue("name", "")); // still empty/invalid
    expect(result.current.register("name").error).toBeUndefined(); // not touched yet
    act(() => result.current.setTouched("name"));
    expect(result.current.register("name").error).toBe("Name required");
  });

  it("handleSubmit blocks and does not call onValid when a field is invalid", () => {
    const onValid = vi.fn();
    const { result } = setup(onValid);
    act(() => result.current.handleSubmit());
    expect(onValid).not.toHaveBeenCalled();
    // validateAll should have populated errors for every required field
    expect(result.current.errors.name).toBeTruthy();
    expect(result.current.errors.email).toBeTruthy();
  });

  it("handleSubmit calls onValid with the current values once every field is valid", () => {
    const onValid = vi.fn();
    const { result } = setup(onValid);
    act(() => {
      result.current.setValue("name", "Ada");
      result.current.setValue("email", "ada@example.com");
      result.current.setValue("confirm", "ada@example.com");
    });
    act(() => result.current.handleSubmit());
    expect(onValid).toHaveBeenCalledWith({ name: "Ada", email: "ada@example.com", confirm: "ada@example.com" });
  });

  it("cross-field validation (matchesField) re-runs against the sibling's latest value", () => {
    const { result } = setup();
    act(() => {
      result.current.setValue("email", "ada@example.com");
      result.current.setValue("confirm", "different@example.com");
    });
    act(() => result.current.handleSubmit());
    expect(result.current.errors.confirm).toBe("Must match email");
  });

  it("reset() restores initial values and clears errors/touched", () => {
    const { result } = setup();
    act(() => {
      result.current.setValue("name", "Ada");
      result.current.handleSubmit(); // populates errors/touched
    });
    expect(result.current.dirty).toBe(true);
    act(() => result.current.reset());
    expect(result.current.dirty).toBe(false);
    expect(result.current.errors).toEqual({});
    expect(result.current.touched).toEqual({});
  });

  it("register() exposes ARIA wiring that only activates once a field is touched and invalid", () => {
    const { result } = setup();
    let field = result.current.register("name");
    expect(field["aria-invalid"]).toBe(false);
    expect(field["aria-describedby"]).toBeUndefined();
    act(() => result.current.setTouched("name"));
    field = result.current.register("name");
    expect(field["aria-invalid"]).toBe(true);
    expect(field["aria-describedby"]).toBe("name-error");
  });

  it("registerCheckbox reads/writes a boolean field", () => {
    const { result } = renderHook(() => useForm<{ remember: boolean }>({
      initialValues: { remember: false },
      onValid: vi.fn(),
    }));
    const cb = result.current.registerCheckbox("remember");
    expect(cb.checked).toBe(false);
    act(() => cb.onChange({ target: { checked: true } }));
    expect(result.current.values.remember).toBe(true);
  });
});
