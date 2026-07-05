import { useState } from "react";
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
  const [category, setCategory] = useState("All");
  const [query,    setQuery]    = useState("");

  const templates = query
    ? searchTemplates(query)
    : listTemplates(category);

  return (
    <div className={styles.panel}>
      <div className={styles.header}>Templates</div>

      <input
        className={styles.search}
        placeholder="Search templates…"
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
            title={`${tpl.name} — ${tpl.width}×${tpl.height}`}
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
