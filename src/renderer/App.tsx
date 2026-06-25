import { useState } from "react";

type Message = {
  role: "user" | "assistant";
  content: string;
};

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);

  async function sendMessage() {
    if (!prompt.trim()) return;

    const userMessage: Message = {
      role: "user",
      content: prompt,
    };

    setMessages((prev) => [...prev, userMessage]);

    try {
      const res = await fetch("http://127.0.0.1:8000/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          project_id: "demo",
          prompt,
        }),
      });

      const data = await res.json();

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.result.summary,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Backend connection failed",
        },
      ]);
    }

    setPrompt("");
  }

  return (
    <div style={{ padding: 20 }}>
      <h1>AI Automation Studio</h1>

      <div
        style={{
          height: 500,
          overflowY: "auto",
          border: "1px solid #ccc",
          padding: 10,
          marginBottom: 10,
        }}
      >
        {messages.map((m, i) => (
          <div key={i}>
            <b>{m.role}:</b> {m.content}
          </div>
        ))}
      </div>

      <input
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="Ask AI..."
        style={{ width: "80%", padding: 10 }}
      />

      <button
        onClick={sendMessage}
        style={{ marginLeft: 10 }}
      >
        Send
      </button>
    </div>
  );
}