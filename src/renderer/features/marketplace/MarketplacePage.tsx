/**
 * MarketplacePage — browse, search, and install agents, plugins, workflows,
 * themes, and datasets from the Axon marketplace.
 *
 * Backed by:  GET /marketplace/listings, GET /marketplace/categories,
 *             GET /marketplace/search, POST /marketplace/{id}/install
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../utils/api";
import { useToast } from "../../contexts/ToastContext";

// ── Types ─────────────────────────────────────────────────────────────────────

type ItemType = "agent" | "plugin" | "theme" | "template" | "prompt_pack" | "workflow" | "dataset" | "model";

interface Listing {
  id: string;
  name: string;
  description: string;
  item_type: ItemType;
  author: string;
  version: string;
  price: number;
  currency: string;
  tags: string[];
  rating_avg: number;
  rating_count: number;
  install_count: number;
  published_at: string;
  verified: boolean;
  featured: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const TYPE_META: Record<ItemType, { label: string; icon: string; color: string }> = {
  agent:       { label: "Agent",       icon: "🤖", color: "#6c8ef7" },
  plugin:      { label: "Plugin",      icon: "🔌", color: "#a78bfa" },
  theme:       { label: "Theme",       icon: "🎨", color: "#f472b6" },
  template:    { label: "Template",    icon: "📄", color: "#34d399" },
  prompt_pack: { label: "Prompts",     icon: "💬", color: "#f59e0b" },
  workflow:    { label: "Workflow",    icon: "⚡", color: "#22d3ee" },
  dataset:     { label: "Dataset",     icon: "📊", color: "#fb923c" },
  model:       { label: "Model",       icon: "🧠", color: "#e879f9" },
};

function Stars({ rating, count }: { rating: number; count: number }) {
  const filled = Math.round(rating);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, color: "#f59e0b" }}>
      {"★".repeat(filled)}{"☆".repeat(5 - filled)}
      <span style={{ color: "var(--t4)", fontSize: 11 }}>({count})</span>
    </span>
  );
}

function PriceBadge({ price, currency }: { price: number; currency: string }) {
  if (price === 0) return (
    <span style={{ fontSize: 12, fontWeight: 700, color: "#34d399", background: "rgba(52,211,153,.12)", padding: "2px 8px", borderRadius: 99, border: "1px solid rgba(52,211,153,.25)" }}>
      Free
    </span>
  );
  return (
    <span style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)" }}>
      {currency === "USD" ? "$" : currency}{price.toFixed(2)}
    </span>
  );
}

// ── Listing card ─────────────────────────────────────────────────────────────

function ListingCard({ item, onInstall, installing }: {
  item: Listing;
  onInstall: (id: string) => void;
  installing: boolean;
}) {
  const meta = TYPE_META[item.item_type] ?? { label: item.item_type, icon: "📦", color: "var(--ta)" };

  return (
    <div style={{
      background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 14,
      padding: "18px 20px", display: "flex", flexDirection: "column", gap: 12,
      transition: "border-color .18s, transform .18s",
      position: "relative",
    }}
    className="card-hover"
    >
      {item.featured && (
        <span style={{
          position: "absolute", top: 12, right: 12,
          fontSize: 10, fontWeight: 700, letterSpacing: "0.6px",
          background: "linear-gradient(135deg,#f59e0b,#fbbf24)", color: "#000",
          padding: "2px 8px", borderRadius: 99,
        }}>FEATURED</span>
      )}

      {/* Header */}
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        <div style={{
          width: 44, height: 44, borderRadius: 10, flexShrink: 0,
          background: `${meta.color}18`, border: `1px solid ${meta.color}30`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 22,
        }}>
          {meta.icon}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {item.name}
            </span>
            {item.verified && (
              <svg width="14" height="14" viewBox="0 0 24 24" fill={meta.color} style={{ flexShrink: 0 }}>
                <path d="M9 12l2 2 4-4M21 12c0 4.97-4.03 9-9 9S3 16.97 3 12 7.03 3 12 3s9 4.03 9 9z"/>
              </svg>
            )}
          </div>
          <div style={{ fontSize: 11, color: "var(--t4)" }}>by {item.author} · v{item.version}</div>
        </div>
      </div>

      {/* Description */}
      <p style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.5, margin: 0,
                  display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {item.description}
      </p>

      {/* Tags */}
      {item.tags.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          <span style={{
            fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 99,
            background: `${meta.color}15`, color: meta.color, border: `1px solid ${meta.color}25`,
          }}>
            {meta.icon} {meta.label}
          </span>
          {item.tags.slice(0, 3).map(t => (
            <span key={t} style={{
              fontSize: 11, padding: "2px 8px", borderRadius: 99,
              background: "rgba(255,255,255,.04)", color: "var(--t4)",
              border: "1px solid var(--border)",
            }}>
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Footer */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "auto" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <Stars rating={item.rating_avg} count={item.rating_count} />
          <span style={{ fontSize: 11, color: "var(--t5)" }}>
            {item.install_count.toLocaleString()} installs
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <PriceBadge price={item.price} currency={item.currency} />
          <button
            onClick={() => onInstall(item.id)}
            disabled={installing}
            style={{
              padding: "7px 16px", borderRadius: 8, border: "none", cursor: installing ? "wait" : "pointer",
              fontSize: 13, fontWeight: 600,
              background: installing ? "rgba(108,142,247,.4)" : "linear-gradient(135deg,#6c8ef7,#818cf8)",
              color: "#fff",
              opacity: installing ? 0.7 : 1,
              transition: "opacity .18s",
            }}
          >
            {installing ? "…" : item.price === 0 ? "Install" : "Buy"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Category pills ────────────────────────────────────────────────────────────

function CategoryBar({ categories, active, onChange }: {
  categories: string[];
  active: string;
  onChange: (c: string) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 4, flexShrink: 0 }}>
      {["all", ...categories].map(c => {
        const meta = c === "all" ? null : TYPE_META[c as ItemType];
        const isActive = active === c;
        return (
          <button
            key={c}
            onClick={() => onChange(c)}
            style={{
              padding: "7px 14px", borderRadius: 99, cursor: "pointer",
              fontSize: 12, fontWeight: 600, whiteSpace: "nowrap",
              background: isActive
                ? meta ? `${meta.color}22` : "rgba(108,142,247,.18)"
                : "rgba(255,255,255,.04)",
              color: isActive
                ? meta ? meta.color : "#6c8ef7"
                : "var(--t4)",
              outline: "none",
              border: isActive
                ? `1px solid ${meta ? meta.color + "40" : "rgba(108,142,247,.4)"}`
                : "1px solid transparent",
              transition: "all .15s",
            }}
          >
            {meta ? `${meta.icon} ${meta.label}` : "All"}
          </button>
        );
      })}
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ query }: { query: string }) {
  return (
    <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: "64px 0", color: "var(--t4)" }}>
      <div style={{ fontSize: 48, marginBottom: 16 }}>🔍</div>
      <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: "var(--t2)" }}>
        {query ? `No results for "${query}"` : "No listings yet"}
      </div>
      <p style={{ fontSize: 13, maxWidth: 320, margin: "0 auto" }}>
        {query ? "Try a different search term or browse by category." : "Be the first to publish to the marketplace."}
      </p>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type SortBy = "featured" | "rating" | "installs" | "newest";

export function MarketplacePage() {
  const toast = useToast();
  const [listings, setListings]     = useState<Listing[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading]       = useState(true);
  const [search, setSearch]         = useState("");
  const [category, setCategory]     = useState("all");
  const [sortBy, setSortBy]         = useState<SortBy>("featured");
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [searchTimer, setSearchTimer] = useState<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (q = "", cat = "all") => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "50" });
      if (q) params.set("q", q);
      if (cat !== "all") params.set("category", cat);
      const url = q ? `/marketplace/search?${params}` : `/marketplace/listings?${params}`;
      const r = await apiFetch(url);
      if (!r.ok) throw new Error();
      const d = await r.json();
      setListings(d.listings ?? d.results ?? []);
    } catch {
      toast("Could not load marketplace", "err");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  const loadCategories = useCallback(async () => {
    try {
      const r = await apiFetch("/marketplace/categories");
      if (!r.ok) return;
      const d = await r.json();
      setCategories(d.categories ?? []);
    } catch {}
  }, []);

  useEffect(() => { load(); loadCategories(); }, [load, loadCategories]);

  const handleSearch = (q: string) => {
    setSearch(q);
    if (searchTimer) clearTimeout(searchTimer);
    setSearchTimer(setTimeout(() => load(q, category), 350));
  };

  const handleCategory = (c: string) => {
    setCategory(c);
    load(search, c);
  };

  const handleInstall = async (id: string) => {
    setInstalling(p => ({ ...p, [id]: true }));
    try {
      const r = await apiFetch(`/marketplace/${id}/install`, { method: "POST" });
      if (!r.ok) throw new Error();
      toast("Installed successfully!", "ok");
      load(search, category);
    } catch {
      toast("Installation failed", "err");
    } finally {
      setInstalling(p => ({ ...p, [id]: false }));
    }
  };

  // Sort
  const sorted = [...listings].sort((a, b) => {
    if (sortBy === "featured") return (b.featured ? 1 : 0) - (a.featured ? 1 : 0);
    if (sortBy === "rating")   return b.rating_avg - a.rating_avg;
    if (sortBy === "installs") return b.install_count - a.install_count;
    if (sortBy === "newest")   return new Date(b.published_at).getTime() - new Date(a.published_at).getTime();
    return 0;
  });

  const SORT_OPTIONS: [SortBy, string][] = [
    ["featured", "Featured"],
    ["rating",   "Top Rated"],
    ["installs", "Most Used"],
    ["newest",   "Newest"],
  ];

  return (
    <>
      {/* Header */}
      <header style={{
        padding: "20px 24px 16px", borderBottom: "1px solid var(--border)",
        background: "var(--bg-surface)", flexShrink: 0, display: "flex", flexDirection: "column", gap: 14,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-0.3px", color: "var(--t1)" }}>
            Marketplace
          </span>
          <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 99,
                         background: "rgba(108,142,247,.15)", color: "#6c8ef7", border: "1px solid rgba(108,142,247,.3)" }}>
            {listings.length} items
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            {SORT_OPTIONS.map(([id, label]) => (
              <button key={id} onClick={() => setSortBy(id)} style={{
                padding: "6px 12px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 500,
                background: sortBy === id ? "rgba(108,142,247,.18)" : "rgba(255,255,255,.04)",
                color: sortBy === id ? "#6c8ef7" : "var(--t4)",
                transition: "all .15s",
              }}>{label}</button>
            ))}
          </div>
        </div>

        {/* Search */}
        <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            style={{ position: "absolute", left: 12, color: "var(--t4)", pointerEvents: "none" }}>
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            value={search}
            onChange={e => handleSearch(e.target.value)}
            placeholder="Search agents, plugins, workflows, themes…"
            style={{
              width: "100%", padding: "10px 14px 10px 38px", fontSize: 14,
              background: "var(--bg-base)", border: "1px solid var(--border)",
              borderRadius: 10, color: "var(--t1)", outline: "none", boxSizing: "border-box",
              fontFamily: "inherit",
            }}
          />
          {search && (
            <button onClick={() => { setSearch(""); load("", category); }} style={{
              position: "absolute", right: 10, background: "none", border: "none",
              cursor: "pointer", color: "var(--t4)", padding: 4, fontSize: 16, lineHeight: 1,
            }}>×</button>
          )}
        </div>

        {/* Category filter */}
        <CategoryBar categories={categories} active={category} onChange={handleCategory} />
      </header>

      {/* Grid */}
      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {loading ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
            {[1,2,3,4,5,6].map(i => (
              <div key={i} className="skeleton" style={{ height: 220, borderRadius: 14 }} />
            ))}
          </div>
        ) : sorted.length === 0 ? (
          <EmptyState query={search} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
            {sorted.map(item => (
              <ListingCard
                key={item.id}
                item={item}
                onInstall={handleInstall}
                installing={!!installing[item.id]}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
