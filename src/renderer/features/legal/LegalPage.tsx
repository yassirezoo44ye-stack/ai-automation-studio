/**
 * Public Privacy Policy / Terms of Use page (/privacy, /terms).
 * Reachable signed in or out; follows the current UI language.
 */
import { useEffect } from "react";
import { useLangContext } from "../../contexts/lang";
import { getLegalContent, LEGAL_LAST_UPDATED, type LegalDoc } from "./legalContent";
import "./legal.css";

interface Props {
  doc: LegalDoc;
}

export function LegalPage({ doc }: Props) {
  const { lang, toggleLang } = useLangContext();
  const content = getLegalContent(doc, lang);
  const isAr = lang === "ar";

  useEffect(() => {
    document.title = `${content.title} — Flow`;
  }, [content.title]);

  const other: LegalDoc = doc === "privacy" ? "terms" : "privacy";
  const otherTitle = getLegalContent(other, lang).title;

  return (
    <div className="legal-root" dir={isAr ? "rtl" : "ltr"} lang={lang}>
      <header className="legal-header">
        <a className="legal-home" href="/">Flow</a>
        <button type="button" className="legal-lang" onClick={toggleLang}>
          {isAr ? "English" : "العربية"}
        </button>
      </header>
      <main className="legal-main">
        <h1>{content.title}</h1>
        <p className="legal-updated">
          {content.updatedLabel}: <time dateTime={LEGAL_LAST_UPDATED}>{LEGAL_LAST_UPDATED}</time>
        </p>
        <p className="legal-intro">{content.intro}</p>
        {content.sections.map((section) => (
          <section key={section.heading} className="legal-section">
            <h2>{section.heading}</h2>
            {section.paragraphs?.map((p) => <p key={p}>{p}</p>)}
            {section.bullets && (
              <ul>
                {section.bullets.map((b) => <li key={b}>{b}</li>)}
              </ul>
            )}
            {section.after?.map((p) => <p key={p}>{p}</p>)}
          </section>
        ))}
        <nav className="legal-footer" aria-label={isAr ? "روابط قانونية" : "Legal links"}>
          <a href={`/${other}`}>{otherTitle}</a>
          <a href="/">{isAr ? "العودة إلى Flow" : "Back to Flow"}</a>
        </nav>
      </main>
    </div>
  );
}
