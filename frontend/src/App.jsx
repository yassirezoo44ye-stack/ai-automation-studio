import { useState } from "react";

export default function App() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");

  const askAI = async () => {
    const res = await fetch("http://127.0.0.1:8000/api/chat/ask", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ question }),
    });

    const data = await res.json();
    setAnswer(data.answer);
  };

  return (
    <div style={{ padding: 20 }}>
      <h2>AI Chat App</h2>

      <input
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="اكتب سؤالك..."
        style={{ padding: 10, width: 300 }}
      />

      <button onClick={askAI} style={{ marginLeft: 10 }}>
        إرسال
      </button>

      <div style={{ marginTop: 20 }}>
        <strong>الرد:</strong>
        <p>{answer}</p>
      </div>
    </div>
  );
}