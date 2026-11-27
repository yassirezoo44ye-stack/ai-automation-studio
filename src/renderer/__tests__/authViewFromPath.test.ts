import { describe, it, expect } from "vitest";
import { authViewFromPath } from "../authView";

describe("authViewFromPath", () => {
  it("opens the sign-in form for direct sign-in links", () => {
    for (const p of ["/login", "/login/", "/LOGIN", "/signin", "/sign-in"]) expect(authViewFromPath(p), p).toBe("login");
  });

  it("opens the sign-in form for links from emails", () => {
    expect(authViewFromPath("/verify-email")).toBe("login");
    expect(authViewFromPath("/reset-password")).toBe("login");
  });

  it("opens the sign-up form for sign-up links", () => {
    for (const p of ["/register", "/signup", "/sign-up"]) expect(authViewFromPath(p), p).toBe("register");
  });

  it("shows the landing page everywhere else", () => {
    for (const p of ["/", "/ar", "/en", "/pricing", "/login-help"]) expect(authViewFromPath(p), p).toBe("landing");
  });
});
