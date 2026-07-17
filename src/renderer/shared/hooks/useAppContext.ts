// Re-export from the canonical context location for use inside shared/
// Feature components should import from ../../contexts/app directly
export { useAppContext } from "../../contexts/app";
export { useToast }      from "../../contexts/toast";
