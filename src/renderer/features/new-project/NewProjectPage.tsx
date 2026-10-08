import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { Icons } from "../../icons";
import type { Page } from "../../types";

type ProjectTypeConfig = {
  id: string;
  page: Page;
  iconKey: keyof typeof Icons;
  accent: string;
};

const PROJECT_TYPES: ProjectTypeConfig[] = [
  { id: "business",    page: "business-lab", iconKey: "business-lab", accent: "var(--teal)"    },
  { id: "application", page: "app-builder",  iconKey: "app-builder",  accent: "var(--accent)"  },
  { id: "saas",        page: "saas-factory", iconKey: "saas-factory", accent: "#7c3aed"        },
  { id: "design",      page: "design",       iconKey: "design",       accent: "#0ea5e9"        },
  { id: "automation",  page: "automation",   iconKey: "automation",   accent: "#f59e0b"        },
];

export function NewProjectPage() {
  const { t } = useTranslation("common");
  const { setPage } = useAppContext();
  const [hoveredId, setHoveredId] = useState<string | null>(null);

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

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
        gap: 16,
      }}>
        {PROJECT_TYPES.map(type => {
          const Icon = Icons[type.iconKey];
          const isHovered = hoveredId === type.id;
          return (
            <button
              key={type.id}
              onClick={() => setPage(type.page)}
              onMouseEnter={() => setHoveredId(type.id)}
              onMouseLeave={() => setHoveredId(null)}
              style={{
                display: "flex", flexDirection: "column", alignItems: "flex-start",
                gap: 12, padding: "20px",
                background: "var(--bg-card)",
                border: `1.5px solid ${isHovered ? type.accent : "var(--b1)"}`,
                borderRadius: 12, cursor: "pointer", textAlign: "start",
                transition: "border-color 0.15s ease, box-shadow 0.15s ease",
                outline: "none",
                boxShadow: isHovered ? `0 0 0 3px ${type.accent}22` : "none",
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
                  {t(`newProject.types.${type.id}.desc`)}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
