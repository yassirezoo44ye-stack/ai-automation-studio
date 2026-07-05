// Re-export from the canonical context location for use inside shared/
// Feature components should import from ../../contexts/AppContext directly
export { useAppContext } from "../../contexts/AppContext";
export { useToast }      from "../../contexts/ToastContext";
