// Toast context + hook — split from ToastContext.tsx so that file exports
// only its component (react-refresh/only-export-components).
import { createContext, useContext } from "react";

export type ToastKind = "ok" | "err" | "info";
export const ToastCtx = createContext<(msg: string, kind?: ToastKind) => void>(() => {});
export function useToast() { return useContext(ToastCtx); }
