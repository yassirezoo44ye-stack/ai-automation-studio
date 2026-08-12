import { useEffect, useState } from "react";
import * as contentApi from "../../api/content";
import { ApiError } from "../../api/client";
import type { ContentItem, ContentItemStatus } from "../../api/contentTypes";
import { useCurrentOrg } from "../../hooks/useCurrentOrg";

const STATUSES: ContentItemStatus[] = ["draft", "approved", "archived"];

export function ContentLibraryPage() {
  const org = useCurrentOrg();
  const [items, setItems] = useState<ContentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [platformFilter, setPlatformFilter] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");
  const [editStatus, setEditStatus] = useState<ContentItemStatus>("draft");

  const load = () => {
    if (!org) return;
    setLoading(true);
    contentApi
      .listItems(org.id, platformFilter ? { platform: platformFilter } : {})
      .then(setItems)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load library"))
      .finally(() => setLoading(false));
  };

  useEffect(load, [org, platformFilter]);

  if (!org) return <div className="center-loading">Loading…</div>;

  const startEdit = (item: ContentItem) => {
    setEditingId(item.id);
    setEditBody(item.body);
    setEditStatus(item.status);
  };

  const saveEdit = async (item: ContentItem) => {
    try {
      const updated = await contentApi.updateItem(org.id, item.id, { body: editBody, status: editStatus });
      setItems((prev) => prev.map((i) => (i.id === item.id ? updated : i)));
      setEditingId(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save changes");
    }
  };

  const remove = async (item: ContentItem) => {
    await contentApi.deleteItem(org.id, item.id);
    setItems((prev) => prev.filter((i) => i.id !== item.id));
  };

  return (
    <div className="page">
      <div className="dashboard">
        <h1>Content Library</h1>

        <div className="field" style={{ maxWidth: "240px" }}>
          <label htmlFor="platform-filter">Filter by platform</label>
          <input
            id="platform-filter"
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value)}
            placeholder="e.g. linkedin"
          />
        </div>

        {error && <div className="error-banner">{error}</div>}

        {loading ? (
          <div className="notice-card">Loading…</div>
        ) : items.length === 0 ? (
          <div className="notice-card">
            Nothing saved yet. Generate content and save it from the Generate page.
          </div>
        ) : (
          items.map((item) => (
            <div className="notice-card" key={item.id} style={{ marginBottom: "0.75rem", textAlign: "left" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <strong>{item.title || "(untitled)"}</strong>
                <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
                  {item.platform} · {item.status} · {new Date(item.created_at).toLocaleDateString()}
                </span>
              </div>

              {editingId === item.id ? (
                <>
                  <textarea
                    value={editBody}
                    onChange={(e) => setEditBody(e.target.value)}
                    style={{
                      width: "100%", minHeight: "100px", marginTop: "0.5rem", padding: "0.5rem",
                      borderRadius: 8, border: "1px solid var(--border)", background: "var(--bg)",
                      color: "var(--text)", fontFamily: "inherit",
                    }}
                  />
                  <select
                    value={editStatus}
                    onChange={(e) => setEditStatus(e.target.value as ContentItemStatus)}
                    style={{
                      marginTop: "0.5rem", padding: "0.4rem", borderRadius: 8,
                      border: "1px solid var(--border)", background: "var(--bg)", color: "var(--text)",
                    }}
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                  <div style={{ marginTop: "0.5rem" }}>
                    <button className="btn btn-primary" onClick={() => saveEdit(item)}>
                      Save
                    </button>
                    <button className="btn btn-ghost" style={{ marginLeft: "0.5rem" }} onClick={() => setEditingId(null)}>
                      Cancel
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <p style={{ margin: "0.5rem 0", whiteSpace: "pre-wrap" }}>
                    {item.body.length > 240 ? `${item.body.slice(0, 240)}…` : item.body}
                  </p>
                  {item.hashtags.length > 0 && (
                    <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                      {item.hashtags.map((h) => `#${h}`).join(" ")}
                    </p>
                  )}
                  <button className="btn btn-ghost" onClick={() => startEdit(item)}>
                    Edit
                  </button>
                  <button className="btn btn-ghost" style={{ marginLeft: "0.5rem" }} onClick={() => remove(item)}>
                    Delete
                  </button>
                </>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
