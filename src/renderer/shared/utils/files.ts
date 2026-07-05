export function fileIcon(path: string) {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = { py: "🐍", js: "🟨", ts: "🔷", tsx: "⚛️", jsx: "⚛️", html: "🌐", css: "🎨", json: "📋", md: "📄", txt: "📝", sh: "⚙️", bat: "⚙️", yaml: "📋", yml: "📋", sql: "🗄️", env: "🔑", dockerfile: "🐳", requirements: "📦", toml: "📋" };
  return map[ext] ?? "📄";
}

const LANG_MAP: Record<string, string> = {
  py: "python", js: "javascript", ts: "typescript", tsx: "tsx", jsx: "jsx",
  html: "html", css: "css", json: "json", md: "markdown", sh: "bash",
  yml: "yaml", yaml: "yaml", sql: "sql",
};

export function getLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return LANG_MAP[ext] ?? "text";
}
