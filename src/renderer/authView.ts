export type AuthView = "landing" | "login" | "register";

const LOGIN_PATHS = ["/login", "/signin", "/sign-in", "/verify-email", "/reset-password"];
const REGISTER_PATHS = ["/register", "/signup", "/sign-up"];

/**
 * Which screen a signed-out visitor sees first. Direct links to sign in or
 * sign up open the form, and links from emails (/verify-email,
 * /reset-password) open the auth form too, since the landing page knows
 * nothing about their tokens.
 */
export function authViewFromPath(pathname: string): AuthView {
  const path = pathname.replace(/\/+$/, "").toLowerCase() || "/";
  if (LOGIN_PATHS.includes(path)) return "login";
  if (REGISTER_PATHS.includes(path)) return "register";
  return "landing";
}
