import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function LandingPage() {
  const [prompt, setPrompt] = useState("");
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const destination = isAuthenticated ? "/dashboard" : "/register";
    navigate(destination, { state: { draftPrompt: prompt } });
  };

  return (
    <div className="page">
      <div className="hero">
        <h1>What do you want to publish?</h1>
        <p>
          Describe a topic and a schedule in plain language — SocialPilot AI builds the content
          strategy, generates the posts, and publishes them for you.
        </p>
        <form className="composer" onSubmit={handleSubmit}>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="اكتب ما تريد أن ينشره النظام... مثال: أريد محتوى عربي عن الذكاء الاصطناعي، منشور أو فيديو كل ساعة لمدة 24 ساعة، وانشره على X وLinkedIn."
          />
          <div className="composer-footer">
            <button type="submit" className="btn btn-primary" disabled={!prompt.trim()}>
              Create Automation
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
