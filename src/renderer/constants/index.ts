// Shared frontend constants — single source of truth. Extracted from App.tsx
// during the merge-conflict-hardening refactor; import from here instead of
// redeclaring per-file.

// API base url lives in utils/api.ts alongside the fetch helpers that use it —
// re-exported here so `import { API } from "../constants"` also works.
export { API } from "../utils/api";

export const AGENT_TEMPLATES = [
  { name: "Code Reviewer", avatar: "🔍", description: "Reviews code for bugs, style, and improvements", system_prompt: "You are an expert code reviewer. Analyze code thoroughly, pointing out bugs, security issues, performance problems, and style improvements. Be specific with line references and provide corrected code snippets." },
  { name: "Python Tutor", avatar: "🐍", description: "Teaches Python clearly with examples", system_prompt: "You are an expert Python tutor. Explain concepts clearly with working examples, explain each line, and encourage best practices. Tailor your explanations to the student's level." },
  { name: "DevOps Engineer", avatar: "⚙️", description: "Docker, CI/CD, infrastructure specialist", system_prompt: "You are a senior DevOps engineer specializing in Docker, Kubernetes, CI/CD pipelines, and cloud infrastructure. Provide production-ready solutions with security and scalability in mind." },
  { name: "Data Analyst", avatar: "📊", description: "Data analysis, SQL, pandas expert", system_prompt: "You are a data analyst expert in SQL, Python (pandas/numpy/matplotlib), and data visualization. Help users analyze data, write efficient queries, and create insightful visualizations." },
  { name: "Creative Writer", avatar: "✍️", description: "Engaging creative and technical writing", system_prompt: "You are a skilled creative writer. Help with storytelling, blog posts, documentation, and any writing task. Focus on clarity, engagement, and the right tone for the audience." },
  { name: "Security Auditor", avatar: "🛡️", description: "Security analysis and best practices", system_prompt: "You are a cybersecurity expert. Analyze code and systems for vulnerabilities (OWASP Top 10, injection, auth issues), suggest hardening measures, and explain security concepts clearly." },
];

// Note: the agent-avatar color palette lives in components/ui/AgentAvatar.tsx
// (colocated with its one consumer) rather than here — keeping it here too
// would itself be the duplicate this file exists to avoid.

export const BUILD_TEMPLATES = [
  { label: "🐍 Python CLI", prompt: "Build a Python command-line calculator with add, subtract, multiply, divide operations. Use argparse for arguments." },
  { label: "🌐 Web App",    prompt: "Build a beautiful responsive to-do list web app in a single HTML file with embedded CSS and JavaScript. Support add, complete, and delete tasks with local storage." },
  { label: "🎮 Game",       prompt: "Build a Snake game in a single HTML file with embedded CSS and JavaScript. Include score, game over screen, and restart button." },
  { label: "📊 Dashboard",  prompt: "Build a beautiful data dashboard in a single HTML file showing fake sales analytics with charts using Chart.js from CDN." },
  { label: "🔗 REST API",   prompt: "Build a FastAPI REST API with SQLite for a simple blog: CRUD for posts (title, content, author, created_at). Include requirements.txt." },
  { label: "🤖 Chatbot",    prompt: "Build a Python chatbot using the anthropic library that reads ANTHROPIC_API_KEY from environment. Include requirements.txt and README." },
];

export const PRIORITY_COLOR: Record<string, string> = { low: "#8F8F8F", medium: "#FFB300", high: "#FF5252" };
