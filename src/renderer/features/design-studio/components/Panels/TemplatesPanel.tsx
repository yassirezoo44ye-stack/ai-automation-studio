import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Template } from "../../types/canvas.types";
import {
  listTemplates,
  searchTemplates,
  TEMPLATE_CATEGORIES,
} from "../../services/templateService";
import styles from "./TemplatesPanel.module.css";

interface Props {
  onApply: (template: Template) => void;
}

export function TemplatesPanel({ onApply }: Props) {
  const { t } = useTranslation("designStudio");
  const [category, setCategory] = useState("All");
  const [query,    setQuery]    = useState("");

  const templates = query
    ? searchTemplates(query)
    : listTemplates(category);

  return (
    <div className={styles.panel}>
      <div className={styles.header}>{t("templatesPanel.header")}</div>

      <input
        className={styles.search}
        placeholder={t("templatesPanel.searchPlaceholder")}
        value={query}
        onChange={e => setQuery(e.target.value)}
      />

      {!query && (
        <div className={styles.categories}>
          {TEMPLATE_CATEGORIES.map(cat => (
            <button
              key={cat}
              className={`${styles.catBtn} ${category === cat ? styles.active : ""}`}
              onClick={() => setCategory(cat)}
            >
              {cat}
            </button>
          ))}
        </div>
      )}

      <div className={styles.grid}>
        {templates.map(tpl => (
          <button
            key={tpl.id}
            className={styles.card}
            onClick={() => onApply(tpl)}
            title={t("templatesPanel.cardTitle", { name: tpl.name, width: tpl.width, height: tpl.height })}
          >
            <div
              className={styles.thumb}
              style={{
                aspectRatio: `${tpl.width}/${tpl.height}`,
                maxHeight: 72,
              }}
            >
              <span className={styles.thumbLabel}>
                {tpl.width}×{tpl.height}
              </span>
            </div>
            <span className={styles.name}>{tpl.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
