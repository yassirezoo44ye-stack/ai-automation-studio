import { useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  onSubmit: (idea: string) => void;
  loading: boolean;
}

const EXAMPLES = [
  "A project management tool for remote design teams with AI task prioritisation",
  "A subscription box service for indie coffee roasters with automated fulfilment",
  "A legal document review platform for small law firms with AI contract analysis",
];

export function IdeaInput({ onSubmit, loading }: Props) {
  const { t } = useTranslation("saas-factory");
  const [idea, setIdea] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = idea.trim();
    if (trimmed.length >= 10) onSubmit(trimmed);
  }

  return (
    <div className="sf-idea-input">
      <div className="sf-idea-input__header">
        <h1 className="sf-idea-input__title">{t("input.title")}</h1>
        <p className="sf-idea-input__subtitle">{t("input.subtitle")}</p>
      </div>

      <form onSubmit={handleSubmit} className="sf-idea-input__form">
        <textarea
          className="sf-idea-input__textarea"
          value={idea}
          onChange={e => setIdea(e.target.value)}
          placeholder={t("input.placeholder")}
          rows={5}
          maxLength={3000}
          aria-label={t("input.ariaLabel")}
          disabled={loading}
        />
        <div className="sf-idea-input__footer">
          <span className="sf-idea-input__counter">{idea.length}/3000</span>
          <button
            type="submit"
            className="sf-btn sf-btn--primary"
            disabled={loading || idea.trim().length < 10}
          >
            {loading ? t("input.building") : t("input.cta")}
          </button>
        </div>
      </form>

      <div className="sf-idea-input__examples">
        <p className="sf-idea-input__examples-label">{t("input.examplesLabel")}</p>
        <div className="sf-idea-input__examples-list">
          {EXAMPLES.map((ex, i) => (
            <button
              key={i}
              className="sf-idea-input__example"
              onClick={() => setIdea(ex)}
              disabled={loading}
            >
              {ex}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
