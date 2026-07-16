import { createContext, useContext } from "react";

export type ToastKind = "ok" | "err" | "info";
export type Toast = { id: string; msg: string; kind: ToastKind };

export const ToastCtx = createContext<(msg: string, kind?: ToastKind) => void>(() => {});
export function useToast() { return useContext(ToastCtx); }
