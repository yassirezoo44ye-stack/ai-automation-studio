import { useEffect } from "react";
import { useLangContext } from "../../contexts/lang";
import { LEGAL_DOCS, LEGAL_PATHS, LEGAL_VERSION, type LegalDocId } from "./content";
import "./legal.css";

const UI = {
  en: { updated: "Last updated", back: "Back to Flow", other: "Other policies", lang: "العربية" },
  ar: { updated: "آخر تحديث", back: "العودة إلى Flow", other: "سياسات أخرى", lang: "English" },
} as const;

/** Public, standalone page: works signed in or out, so it can be linked from
 *  sign-up, checkout, OAuth consent screens and app-store listings. */
export function LegalPage({ doc }: { doc: LegalDocId }) {
  const { lang, toggleLang } = useLangContext();
  const content = LEGAL_DOCS[lang][doc];
  const ui = UI[lang];

  useEffect(() => {
    document.title = `${content.title} · Flow`;
  }, [content.title]);

  return (
    <div className="legal-page">
      <header className="legal-page__bar">
        <a href="/" className="legal-page__home">{ui.back}</a>
        <button type="button" className="legal-page__lang" onClick={toggleLang}>{ui.lang}</button>
      </header>
      <main className="legal-page__body">
        <h1>{content.title}</h1>
        <p className="legal-page__meta">{ui.updated}: {LEGAL_VERSION}</p>
        <p>{content.intro}</p>
        {content.sections.map(section => (
          <section key={section.heading}>
            <h2>{section.heading}</h2>
            {section.paragraphs?.map(p => <p key={p}>{p}</p>)}
            {section.bullets && (
              <ul>{section.bullets.map(b => <li key={b}>{b}</li>)}</ul>
            )}
          </section>
        ))}
        <nav className="legal-page__other" aria-label={ui.other}>
          {(Object.keys(LEGAL_PATHS) as LegalDocId[]).filter(id => id !== doc).map(id => (
            <a key={id} href={LEGAL_PATHS[id]}>{LEGAL_DOCS[lang][id].title}</a>
          ))}
        </nav>
      </main>
    </div>
  );
}

/** Small row of links to the three policies, for footers and settings. */
export function LegalLinks({ className }: { className?: string }) {
  const { lang } = useLangContext();
  return (
    <nav className={["legal-links", className].filter(Boolean).join(" ")} aria-label="Legal">
      {(Object.keys(LEGAL_PATHS) as LegalDocId[]).map(id => (
        <a key={id} href={LEGAL_PATHS[id]}>{LEGAL_DOCS[lang][id].title}</a>
      ))}
    </nav>
  );
}
