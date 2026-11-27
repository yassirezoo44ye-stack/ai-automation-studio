import { describe, it, expect } from "vitest";
import { extractActions, validateAction, actionKey } from "../shared/utils/assistantActions";
import { extractNavSuggestions } from "../shared/utils/assistantNav";

describe("extractActions", () => {
  it("parses allowed proposals and strips markers", () => {
    const r = extractActions('Sure.\n[[action:create_task {"title": "Call supplier", "priority": "high", "due_date": "2026-11-20"}]]');
    expect(r.text.trim()).toBe("Sure.");
    expect(r.actions).toEqual([{ kind: "create_task", title: "Call supplier", priority: "high", due_date: "2026-11-20" }]);
  });
  it("drops unknown or destructive kinds and malformed JSON", () => {
    const r = extractActions('[[action:delete_lead {"id": "1"}]] [[action:send_email {"to": "a@b.c"}]] [[action:create_task {bad json}]]');
    expect(r.actions).toEqual([]);
    expect(r.text.trim()).toBe("");
  });
  it("caps at three proposals", () => {
    const one = '[[action:create_task {"title": "t"}]]\n';
    expect(extractActions(one.repeat(5)).actions).toHaveLength(3);
  });
});

describe("validateAction", () => {
  it("normalises and rejects bad fields", () => {
    expect(validateAction("create_task", { title: "  x  ", priority: "urgent!!", due_date: "tomorrow" }))
      .toEqual({ kind: "create_task", title: "x", priority: "medium" });
    expect(validateAction("create_task", { title: "" })).toBeNull();
    expect(validateAction("create_lead", { name: "Sara", email: "not-an-email", phone: "call me" }))
      .toEqual({ kind: "create_lead", name: "Sara" });
    expect(validateAction("create_lead", { name: "Sara", email: "s@x.io", phone: "+971 50 000 0000" }))
      .toEqual({ kind: "create_lead", name: "Sara", email: "s@x.io", phone: "+971 50 000 0000" });
    expect(validateAction("create_task", ["array"])).toBeNull();
  });
});

it("hides a half-streamed action marker", () => {
  expect(extractNavSuggestions('Okay.\n[[action:create_task {"ti').text).toBe("Okay.");
});

it("keys are stable per message and index", () => {
  expect(actionKey("abc", 0)).toBe(actionKey("abc", 0));
  expect(actionKey("abc", 0)).not.toBe(actionKey("abc", 1));
});

describe("status changes (M5)", () => {
  const ID = "3f2b8c1e-9a4d-4c2b-8e1f-0a1b2c3d4e5f";
  it("accepts only a real uuid and a known status", () => {
    expect(validateAction("update_task_status", { id: ID.toUpperCase(), status: "done" }))
      .toEqual({ kind: "update_task_status", id: ID, status: "done" });
    expect(validateAction("update_lead_status", { id: ID, status: "won" }))
      .toEqual({ kind: "update_lead_status", id: ID, status: "won" });
    expect(validateAction("update_task_status", { id: "task-1", status: "done" })).toBeNull();
    expect(validateAction("update_task_status", { id: ID, status: "deleted" })).toBeNull();
    expect(validateAction("update_lead_status", { id: ID, status: "done" })).toBeNull();
    expect(validateAction("update_lead_status", { id: `${ID}'; DROP TABLE leads`, status: "won" })).toBeNull();
  });
});
