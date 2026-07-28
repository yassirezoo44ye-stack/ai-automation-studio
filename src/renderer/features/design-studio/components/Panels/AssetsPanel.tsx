import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { Asset, AssetType } from "../../types/canvas.types";
import {
  listAssets,
  saveAsset,
  deleteAsset,
  toggleAssetFavorite,
  inferAssetType,
} from "../../services/assetService";
import styles from "./AssetsPanel.module.css";

interface Props {
  onInsert: (src: string) => void;
}

const TAB_IDS: (AssetType | "all")[] = ["all", "image", "svg", "video"];
const TAB_JSON_KEY: Record<string, string> = { all: "all", image: "images", svg: "svg", video: "video" };

export function AssetsPanel({ onInsert }: Props) {
  const { t } = useTranslation("designStudio");
  const [assets,   setAssets]   = useState<Asset[]>([]);
  const [tab,      setTab]      = useState<AssetType | "all">("all");
  const [query,    setQuery]    = useState("");
  const [loading,  setLoading]  = useState(false);

  useEffect(() => {
    let active = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    listAssets(tab === "all" ? undefined : tab)
      .then(all => { if (active) setAssets(all); })
      .catch(() => { /* ignore */ })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [tab]);

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    for (const file of files) {
      const asset = await saveAsset(file, inferAssetType(file));
      setAssets(prev => [asset, ...prev]);
    }
    e.target.value = "";
  }, []);

  const handleDelete = useCallback(async (id: string) => {
    await deleteAsset(id);
    setAssets(prev => prev.filter(a => a.id !== id));
  }, []);

  const handleFav = useCallback(async (id: string) => {
    const updated = await toggleAssetFavorite(id);
    if (updated) setAssets(prev => prev.map(a => a.id === id ? updated : a));
  }, []);

  const filtered = query
    ? assets.filter(a => a.name.toLowerCase().includes(query.toLowerCase()))
    : assets;

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <span>{t("assetsPanel.header")}</span>
        <label className={styles.uploadBtn} title={t("assetsPanel.uploadTitle")}>
          + {t("assetsPanel.upload")}
          <input
            type="file"
            multiple
            accept="image/*,video/*,audio/*,.svg,.pdf"
            onChange={handleUpload}
            className={styles.hidden}
          />
        </label>
      </div>

      <div className={styles.tabs}>
        {TAB_IDS.map(id => (
          <button
            key={id}
            className={`${styles.tab} ${tab === id ? styles.active : ""}`}
            onClick={() => setTab(id)}
          >
            {t(`assetsPanel.tabs.${TAB_JSON_KEY[id]}`)}
          </button>
        ))}
      </div>

      <input
        className={styles.search}
        placeholder={t("assetsPanel.searchPlaceholder")}
        value={query}
        onChange={e => setQuery(e.target.value)}
      />

      {loading && <p className={styles.status}>{t("assetsPanel.loading")}</p>}
      {!loading && filtered.length === 0 && (
        <p className={styles.status}>{t("assetsPanel.empty")}</p>
      )}

      <div className={styles.grid}>
        {filtered.map(asset => (
          <div key={asset.id} className={styles.card}>
            {asset.type === "video" ? (
              <video src={asset.src} className={styles.thumb} muted />
            ) : (
              <img src={asset.src} alt={asset.name} className={styles.thumb} loading="lazy" />
            )}
            <div className={styles.overlay}>
              <button
                className={styles.action}
                onClick={() => onInsert(asset.src)}
                title={t("assetsPanel.insertTitle")}
              >
                +
              </button>
              <button
                className={styles.action}
                onClick={() => void handleFav(asset.id)}
                title={asset.isFavorite ? t("assetsPanel.removeFavourite") : t("assetsPanel.favourite")}
              >
                {asset.isFavorite ? "★" : "☆"}
              </button>
              <button
                className={styles.action}
                onClick={() => void handleDelete(asset.id)}
                title={t("assetsPanel.delete")}
              >
                ✕
              </button>
            </div>
            <span className={styles.name}>{asset.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
