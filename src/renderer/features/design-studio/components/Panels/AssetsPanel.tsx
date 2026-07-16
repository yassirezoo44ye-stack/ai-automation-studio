import { useState, useEffect, useCallback } from "react";
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

const TABS: { id: AssetType | "all"; label: string }[] = [
  { id: "all",   label: "All"    },
  { id: "image", label: "Images" },
  { id: "svg",   label: "SVG"    },
  { id: "video", label: "Video"  },
];

export function AssetsPanel({ onInsert }: Props) {
  const [assets,   setAssets]   = useState<Asset[]>([]);
  const [tab,      setTab]      = useState<AssetType | "all">("all");
  const [query,    setQuery]    = useState("");
  const [loading,  setLoading]  = useState(false);

  useEffect(() => {
    let active = true;
     
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
        <span>Assets</span>
        <label className={styles.uploadBtn} title="Upload files">
          + Upload
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
        {TABS.map(t => (
          <button
            key={t.id}
            className={`${styles.tab} ${tab === t.id ? styles.active : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <input
        className={styles.search}
        placeholder="Search assets…"
        value={query}
        onChange={e => setQuery(e.target.value)}
      />

      {loading && <p className={styles.status}>Loading…</p>}
      {!loading && filtered.length === 0 && (
        <p className={styles.status}>No assets found. Upload files to get started.</p>
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
                title="Insert"
              >
                +
              </button>
              <button
                className={styles.action}
                onClick={() => void handleFav(asset.id)}
                title={asset.isFavorite ? "Remove favourite" : "Favourite"}
              >
                {asset.isFavorite ? "★" : "☆"}
              </button>
              <button
                className={styles.action}
                onClick={() => void handleDelete(asset.id)}
                title="Delete"
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
