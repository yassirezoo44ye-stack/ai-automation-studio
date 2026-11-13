import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAutoSave } from "./useAutoSave";
import type { DesignProject } from "../types/canvas.types";

const project = (revision: string) => ({ id: "design-1", name: revision } as DesignProject);
beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); });

it("does not mark newer edits saved when an older request completes and queues the latest revision", async () => {
  let release!: () => void;
  const first = project("A"), latest = project("B");
  const onSave = vi.fn().mockReturnValueOnce(new Promise<void>(resolve => { release = resolve; })).mockResolvedValue(undefined);
  const onSaved = vi.fn();
  const { rerender } = renderHook(({ value }) => useAutoSave({ project: value, unsaved: true, onSave, onSaved }), { initialProps: { value: first } });
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(onSave).toHaveBeenCalledWith(first);
  rerender({ value: latest });
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(onSave).toHaveBeenCalledOnce();
  await act(async () => { release(); });
  expect(onSaved).not.toHaveBeenCalled();
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(onSave).toHaveBeenLastCalledWith(latest);
  expect(onSaved).toHaveBeenCalledOnce();
});

it("retains dirty state and reports rejected saves without an infinite retry loop", async () => {
  const error = new Error("save rejected"), onSaved = vi.fn(), onError = vi.fn();
  const onSave = vi.fn().mockRejectedValue(error);
  renderHook(() => useAutoSave({ project: project("A"), unsaved: true, onSave, onSaved, onError }));
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(onSave).toHaveBeenCalledOnce();
  expect(onSaved).not.toHaveBeenCalled();
  expect(onError).toHaveBeenCalledWith(error);
});

it("does not reset the debounce when only callback identities change", async () => {
  const value = project("A"), onSave = vi.fn().mockResolvedValue(undefined), onSaved = vi.fn();
  const { rerender } = renderHook(() => useAutoSave({ project: value, unsaved: true, onSave: p => onSave(p), onSaved: () => onSaved() }));
  await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
  rerender();
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
  expect(onSave).toHaveBeenCalledOnce();
  expect(onSaved).toHaveBeenCalledOnce();
});

it("does not acknowledge an in-flight save after the editor is closed", async () => {
  let release!: () => void;
  const onSaved = vi.fn(), onSave = vi.fn(() => new Promise<void>(resolve => { release = resolve; }));
  const { unmount } = renderHook(() => useAutoSave({ project: project("A"), unsaved: true, onSave, onSaved }));
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  unmount();
  await act(async () => { release(); await vi.advanceTimersByTimeAsync(5000); });
  expect(onSaved).not.toHaveBeenCalled();
  expect(onSave).toHaveBeenCalledOnce();
});
