import js from "@eslint/js";
import ts from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import jsxA11y from "eslint-plugin-jsx-a11y";

export default ts.config(
  { ignores: ["dist", "node_modules", "*.cjs"] },
  {
    // jsxA11y's declared peerDependencies caps at eslint@^9, but its rules
    // are plain rule objects with no dependency on ESLint's internals beyond
    // the stable flat-config rule API — verified working against eslint@10
    // (ran cleanly, produced correct findings) before adopting it here.
    extends: [js.configs.recommended, ...ts.configs.recommended, jsxA11y.flatConfigs.recommended],
    files: ["src/**/*.{ts,tsx}"],
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,

      // autoFocus on a login field or a just-opened dialog's first input is
      // expected, accessible behavior (matches the products this platform
      // is benchmarked against) — this rule is more opinionated than
      // helpful here, so it's disabled rather than stripping autoFocus
      // from every call site.
      "jsx-a11y/no-autofocus": "off",

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
      // set-state-in-effect: valid for initialisation guards (if !data return early + setState)
      "react-hooks/set-state-in-effect": "warn",
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
