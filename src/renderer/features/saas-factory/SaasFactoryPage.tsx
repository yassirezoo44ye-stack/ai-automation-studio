import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { IdeaInput } from "./components/IdeaInput";
import { PipelineView } from "./components/PipelineView";
import { useSaasFactory } from "./hooks/useSaasFactory";
import "./SaasFactoryPage.css";

export function SaasFactoryPage() {
  const { t } = useTranslation("saas-factory");
  const {
    project, projects, loading, error,
    submit, resume, remove, loadProjects, openProject,
  } = useSaasFactory();

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  return (
    <div className="sf-page" role="main" aria-label={t("page.ariaLabel")}>

      {/* Top bar */}
      <div className="sf-page__topbar">
        <h2 className="sf-page__heading">{t("page.heading")}</h2>
        <p className="sf-page__sub">{t("page.sub")}</p>
      </div>

      {/* Error banner */}
      {error && (
        <div className="sf-page__error" role="alert">
          {error}
        </div>
      )}

      {/* Main content: idea input OR active pipeline */}
      <div className="sf-page__body">
        {!project ? (
          <IdeaInput onSubmit={submit} loading={loading} />
        ) : (
          <PipelineView
            project={project}
            onResume={() => resume(project.id)}
            onDelete={() => remove(project.id)}
          />
        )}
      </div>

      {/* Previous projects list */}
      {projects.length > 0 && !project && (
        <section className="sf-page__history" aria-label={t("history.label")}>
          <h3 className="sf-page__history-title">{t("history.title")}</h3>
          <div className="sf-page__history-list">
            {projects.map(p => (
              <button
                key={p.id}
                className={`sf-history-item sf-history-item--${p.phase.toLowerCase()}`}
                onClick={() => openProject(p)}
              >
                <span className="sf-history-item__idea">{p.idea_text.slice(0, 80)}</span>
                <span className="sf-history-item__phase">{p.phase}</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
