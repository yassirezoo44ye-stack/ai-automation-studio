import js from "@eslint/js";
import ts from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default ts.config(
  { ignores: ["dist", "node_modules", "*.cjs"] },
  {
    extends: [js.configs.recommended, ...ts.configs.recommended],
    files: ["src/**/*.{ts,tsx}"],
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,

      // React Refresh — only for the public surface of feature modules
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],

      // Unused vars — errors for real dead code, allow _ prefix for intentional ignores
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_?" },
      ],

      // `any` is a warning not an error — large workspace files have unavoidable cases
      "@typescript-eslint/no-explicit-any": "warn",

      // Type imports — enforced for cleaner bundles
      "@typescript-eslint/consistent-type-imports": ["error", { prefer: "type-imports" }],

      // Empty catch blocks are valid for fire-and-forget patterns
      "no-empty": ["error", { allowEmptyCatch: true }],

      // console.warn/error are fine; console.log is a warning (not error) to not block CI
      "no-console": ["warn", { allow: ["warn", "error"] }],

      // These react-hooks rules fire on patterns that work correctly in React 19
      "react-hooks/rules-of-hooks": "warn",
      "react-hooks/exhaustive-deps": "warn",
      // set-state-in-effect flags every fetch-on-mount loader (`useEffect(() => { void load(); })`)
      // because the loader sets a loading flag synchronously. That is the intended data-fetching
      // pattern here; revisit when data fetching moves to a query library (e.g. TanStack Query).
      "react-hooks/set-state-in-effect": "off",
      // refs-in-effect: valid for the useRef stable-callback pattern
      "react-hooks/refs": "warn",

      // Allow void expressions (used for fire-and-forget async calls)
      "@typescript-eslint/no-unused-expressions": ["error", { allowShortCircuit: true, allowTernary: true }],
    },
  },
  // Shared utility + new files get stricter rules
  {
    files: ["src/renderer/shared/**/*.{ts,tsx}", "src/renderer/contexts/**/*.{ts,tsx}"],
    rules: {
      "no-console": "error",
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
);
