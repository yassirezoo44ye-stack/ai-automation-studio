import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import type { ProjectWorkspace } from "../../contexts/app";
import { Icons } from "../../icons";
import type { Page } from "../../types";
import { createProject } from "../app-builder/services/builderService";
import { APIError } from "../../shared/utils/api";

type ProjectTypeConfig = {
  id: string;
  page: Page;
  iconKey: keyof typeof Icons;
  accent: string;
};

const PROJECT_TYPES: ProjectTypeConfig[] = [
  { id: "business",    page: "business-lab", iconKey: "business-lab", accent: "var(--teal)"   },
  { id: "application", page: "app-builder",  iconKey: "app-builder",  accent: "var(--accent)" },
  { id: "saas",        page: "saas-factory", iconKey: "saas-factory", accent: "#7c3aed"       },
  { id: "design",      page: "design",       iconKey: "design",       accent: "#0ea5e9"       },
  { id: "automation",  page: "automation",   iconKey: "automation",   accent: "#f59e0b"       },
];

const WORKSPACE_FOR_TYPE: Partial<Record<string, ProjectWorkspace>> = {
  application: "build",
  saas:        "build",
  design:      "design",
  automation:  "automation",
};

// RFC 4122 UUID shape — server-generated only; never produced client-side.
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function NewProjectPage() {
  const { t } = useTranslation("common");
  const { setPage, setActiveProject } = useAppContext();
  const [hoveredId,      setHoveredId]      = useState<string | null>(null);
  const [creatingTypeId, setCreatingTypeId] = useState<string | null>(null);
  const [error,          setError]          = useState<string | null>(null);

  const handleCardClick = async (type: ProjectTypeConfig) => {
    if (creatingTypeId !== null) return; // block while any creation is in flight

    // Business Lab has no project — navigate directly.
    if (type.id === "business") {
      setPage("business-lab");
      return;
    }

    const workspace = WORKSPACE_FOR_TYPE[type.id];
    if (!workspace) return;

    setError(null);
    setCreatingTypeId(type.id);
    try {
      const name        = t(`newProject.types.${type.id}.title`);
      const description = t(`newProject.types.${type.id}.desc`);
      const project     = await createProject(name, description);

      // Guard: only navigate when the server hands back a valid UUID.
      if (!project?.id || !UUID_RE.test(project.id)) {
        throw new Error("Server returned an invalid project ID.");
      }

      setActiveProject(project.id, workspace);
    } catch (err) {
      const msg =
        err instanceof APIError
          ? (err.details.probableCause ?? err.message)
          : err instanceof Error
          ? err.message
          : "Failed to create project. Please try again.";
      setError(msg);
    } finally {
      setCreatingTypeId(null);
    }
  };

  const isAnyCreating = creatingTypeId !== null;

  return (
    <div style={{ padding: "40px 32px", maxWidth: 800, margin: "0 auto" }}>
      <div style={{ marginBottom: 36 }}>
        <h1 style={{
          fontSize: 28, fontWeight: 700, color: "var(--t1)",
          margin: 0, marginBottom: 8, letterSpacing: "-0.5px",
        }}>
          {t("newProject.pageTitle")}
        </h1>
        <p style={{ fontSize: 15, color: "var(--t3)", margin: 0 }}>
          {t("newProject.subtitle")}
        </p>
      </div>

      {error && (
        <p role="alert" style={{ color: "var(--err, #f87171)", fontSize: 13, marginBottom: 16, margin: "0 0 16px" }}>
          {error}
        </p>
      )}

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
        gap: 16,
      }}>
        {PROJECT_TYPES.map(type => {
          const Icon       = Icons[type.iconKey];
          const isHovered  = hoveredId === type.id;
          const isCreating = creatingTypeId === type.id;
          return (
            <button
              key={type.id}
              onClick={() => { void handleCardClick(type); }}
              onMouseEnter={() => setHoveredId(type.id)}
              onMouseLeave={() => setHoveredId(null)}
              disabled={isAnyCreating}
              aria-busy={isCreating}
              style={{
                display: "flex", flexDirection: "column", alignItems: "flex-start",
                gap: 12, padding: "20px",
                background: "var(--bg-card)",
                border: `1.5px solid ${isHovered && !isAnyCreating ? type.accent : "var(--b1)"}`,
                borderRadius: 12,
                cursor: isAnyCreating ? "not-allowed" : "pointer",
                textAlign: "start",
                transition: "border-color 0.15s ease, box-shadow 0.15s ease",
                outline: "none",
                boxShadow: isHovered && !isAnyCreating ? `0 0 0 3px ${type.accent}22` : "none",
                opacity: isAnyCreating ? 0.6 : 1,
              }}
            >
              <div style={{
                width: 36, height: 36, borderRadius: 10,
                background: `${type.accent}22`,
                display: "flex", alignItems: "center", justifyContent: "center",
                color: type.accent, flexShrink: 0,
              }}>
                <Icon />
              </div>
              <div>
                <div style={{
                  fontSize: 14, fontWeight: 600, color: "var(--t1)",
                  marginBottom: 4, lineHeight: 1.3,
                }}>
                  {t(`newProject.types.${type.id}.title`)}
                </div>
                <div style={{ fontSize: 12, color: "var(--t4)", lineHeight: 1.4 }}>
                  {isCreating ? "Creating…" : t(`newProject.types.${type.id}.desc`)}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
