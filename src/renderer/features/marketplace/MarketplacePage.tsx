import { C } from "../../shared/lib/theme";
/**
 * MarketplacePage — browse, search, and install agents, plugins, workflows,
 * themes, and datasets from the Axon marketplace.
 *
 * Backed by:  GET  /marketplace/listings, /marketplace/categories, /marketplace/search
 *             POST /marketplace/listings/{id}/install, .../uninstall, .../rollback
 *             GET  /marketplace/listings/{id}/{versions,dependencies,reviews}
 *             GET  /marketplace/publishers/{org_id}
 *
 * Field names and response shapes here match app/routers/marketplace.py and
 * app/marketplace/store.py exactly (list endpoints return {items,...}, not
 * {listings} or {results}; items use `type`/`price_usd`/`rating`/`installs`,
 * not `item_type`/`price`/`rating_avg`/`install_count`).
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/toast";
import { useOrg } from "../../contexts/OrgContext";
import { VersionsTab } from "./tabs/VersionsTab";
import { DependenciesTab } from "./tabs/DependenciesTab";
import { ReviewsTab } from "./tabs/ReviewsTab";
import { PublisherTab } from "./tabs/PublisherTab";

// ── Types ─────────────────────────────────────────────────────────────────────

type ItemType = "agent" | "plugin" | "theme" | "template" | "prompt_pack" | "workflow" | "dataset" | "model";

interface Listing {
  id: string;
  name: string;
  description: string;
  type: ItemType;
  author: string;
  version: string;
  pricing: "free" | "one_time" | "subscription" | "pay_per_use";
  price_usd: number;
  tags: string[];
  rating: number;
  rating_count: number;
  installs: number;
  created_at: number;
  verified: boolean;
  visibility: "public" | "private" | "internal";
  owner_organization_id: string | null;
}

interface ListingsResponse { items: Listing[]; total: number; page: number; per_page: number; pages: number }
interface Category { slug: string; label: string; icon: string; description: string | null; sort_order: number; item_count: number }

// ── Helpers ───────────────────────────────────────────────────────────────────

const TYPE_META: Record<ItemType, { label: string; icon: string; color: string }> = {
  agent:       { label: "Agent",       icon: "🤖", color: C.blue },
  plugin:      { label: "Plugin",      icon: "🔌", color: C.purple },
  theme:       { label: "Theme",       icon: "🎨", color: C.pink },
  template:    { label: "Template",    icon: "📄", color: C.green },
  prompt_pack: { label: "Prompts",     icon: "💬", color: C.amber },
  workflow:    { label: "Workflow",    icon: "⚡", color: "#22d3ee" },
  dataset:     { label: "Dataset",     icon: "📊", color: C.orange },
  model:       { label: "Model",       icon: "🧠", color: "#e879f9" },
};

function Stars({ rating, count }: { rating: number; count: number }) {
  const filled = Math.round(rating);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, color: C.amber }}>
      {"★".repeat(filled)}{"☆".repeat(5 - filled)}
      <span style={{ color: "var(--t4)", fontSize: 11 }}>({count})</span>
    </span>
  );
}

function PriceBadge({ priceUsd }: { priceUsd: number }) {
  if (priceUsd === 0) return (
    <span style={{ fontSize: 12, fontWeight: 700, color: C.green, background: "rgba(52,211,153,.12)", padding: "2px 8px", borderRadius: 99, border: "1px solid rgba(52,211,153,.25)" }}>
      Free
    </span>
  );
  return (
    <span style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)" }}>
      ${priceUsd.toFixed(2)}
    </span>
  );
}

// ── Listing card ─────────────────────────────────────────────────────────────

function ListingCard({ item, onInstall, onUninstall, onToggleDetails, installing, installed, expanded }: {
  item: Listing;
  onInstall: (id: string) => void;
  onUninstall: (id: string) => void;
  onToggleDetails: (id: string) => void;
  installing: boolean;
  installed: boolean;
  expanded: boolean;
}) {
  const meta = TYPE_META[item.type] ?? { label: item.type, icon: "📦", color: "var(--ta)" };

  return (
    <div
      style={{
        background: "var(--bg-surface)", border: `1px solid ${expanded ? meta.color + "60" : "var(--border)"}`, borderRadius: 14,
        padding: "18px 20px", display: "flex", flexDirection: "column", gap: 12,
        transition: "border-color .18s, transform .18s",
        position: "relative",
      }}
      className="card-hover"
    >
      {item.visibility !== "public" && (
        <span style={{
          position: "absolute", top: 12, right: 12,
          fontSize: 10, fontWeight: 700, letterSpacing: "0.6px",
          background: "rgba(255,255,255,.08)", color: "var(--t3)",
          padding: "2px 8px", borderRadius: 99,
        }}>
          {item.visibility.toUpperCase()}
        </span>
      )}

      {/* Header */}
      <div
        role="button" tabIndex={0}
        style={{ display: "flex", gap: 12, alignItems: "flex-start", cursor: "pointer" }}
        onClick={() => onToggleDetails(item.id)}
        onKeyDown={e => e.key === "Enter" && onToggleDetails(item.id)}
      >
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
                <path d="M9 12l2 2 4-4M21 12c0 4.97-4.03 9-9 9S3 16.97 3 12 7.03 3 12 3s9 4.03 9 9z" />
              </svg>
            )}
          </div>
          <div style={{ fontSize: 11, color: "var(--t4)" }}>by {item.author} · v{item.version}</div>
        </div>
      </div>

      {/* Description */}
      <p style={{
        fontSize: 13, color: "var(--t3)", lineHeight: 1.5, margin: 0,
        display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
      }}>
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
          <Stars rating={item.rating} count={item.rating_count} />
          <span style={{ fontSize: 11, color: "var(--t5)" }}>
            {item.installs.toLocaleString()} installs
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={() => onToggleDetails(item.id)}
            style={{
              padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border)", cursor: "pointer",
              fontSize: 12, fontWeight: 600, background: "rgba(255,255,255,.04)", color: "var(--t3)",
            }}
          >
            {expanded ? "Hide" : "Details"}
          </button>
          <PriceBadge priceUsd={item.price_usd} />
          {installed ? (
            <button
              onClick={() => onUninstall(item.id)}
              disabled={installing}
              style={{
                padding: "7px 16px", borderRadius: 8, border: "1px solid var(--border)", cursor: installing ? "wait" : "pointer",
                fontSize: 13, fontWeight: 600, background: "rgba(255,255,255,.04)", color: "var(--t3)",
                opacity: installing ? 0.7 : 1,
              }}
            >
              {installing ? "…" : "Uninstall"}
            </button>
          ) : (
            <button
              onClick={() => onInstall(item.id)}
              disabled={installing}
              style={{
                padding: "7px 16px", borderRadius: 8, border: "none", cursor: installing ? "wait" : "pointer",
                fontSize: 13, fontWeight: 600,
                background: installing ? "rgba(108,142,247,.4)" : "linear-gradient(135deg,#6c8ef7,#818cf8)",
                color: "#fff", opacity: installing ? 0.7 : 1, transition: "opacity .18s",
              }}
            >
              {installing ? "…" : item.price_usd === 0 ? "Install" : "Buy"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Detail panel (Versions / Dependencies / Reviews / Publisher tabs) ────────

type DetailTab = "versions" | "dependencies" | "reviews" | "publisher";
const DETAIL_TABS: [DetailTab, string][] = [
  ["versions", "Versions"], ["dependencies", "Dependencies"], ["reviews", "Reviews"], ["publisher", "Publisher"],
];

function DetailPanel({ item, onClose, canManage, onRolledBack }: {
  item: Listing;
  onClose: () => void;
  canManage: boolean;
  onRolledBack: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("versions");

  return (
    <div style={{
      background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 14,
      padding: "16px 20px", marginBottom: 16,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>{item.name}</span>
        <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", fontSize: 18, lineHeight: 1, padding: 4 }}>×</button>
      </div>
      <div style={{ display: "flex", gap: 6, marginBottom: 14, borderBottom: "1px solid var(--border)", paddingBottom: 10 }}>
        {DETAIL_TABS.map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)} style={{
            padding: "6px 12px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 500,
            background: tab === id ? "rgba(108,142,247,.18)" : "rgba(255,255,255,.04)",
            color: tab === id ? C.blue : "var(--t4)",
          }}>
            {label}
          </button>
        ))}
      </div>
      {tab === "versions" && (
        <VersionsTab listingId={item.id} currentVersion={item.version} canManage={canManage} onRolledBack={onRolledBack} />
      )}
      {tab === "dependencies" && <DependenciesTab listingId={item.id} />}
      {tab === "reviews" && <ReviewsTab listingId={item.id} />}
      {tab === "publisher" && <PublisherTab ownerOrganizationId={item.owner_organization_id} author={item.author} />}
    </div>
  );
}

// ── Category pills ────────────────────────────────────────────────────────────

function CategoryBar({ categories, active, onChange }: {
  categories: Category[];
  active: string;
  onChange: (c: string) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 4, flexShrink: 0 }}>
      <button
        onClick={() => onChange("all")}
        style={{
          padding: "7px 14px", borderRadius: 99, cursor: "pointer",
          fontSize: 12, fontWeight: 600, whiteSpace: "nowrap",
          background: active === "all" ? "rgba(108,142,247,.18)" : "rgba(255,255,255,.04)",
          color: active === "all" ? C.blue : "var(--t4)",
          outline: "none",
          border: active === "all" ? "1px solid rgba(108,142,247,.4)" : "1px solid transparent",
        }}
      >
        All
      </button>
      {categories.map(c => {
        const isActive = active === c.slug;
        const meta = TYPE_META[c.slug as ItemType];
        const color = meta?.color ?? C.blue;
        return (
          <button
            key={c.slug}
            onClick={() => onChange(c.slug)}
            style={{
              padding: "7px 14px", borderRadius: 99, cursor: "pointer",
              fontSize: 12, fontWeight: 600, whiteSpace: "nowrap",
              background: isActive ? `${color}22` : "rgba(255,255,255,.04)",
              color: isActive ? color : "var(--t4)",
              outline: "none",
              border: isActive ? `1px solid ${color}40` : "1px solid transparent",
              transition: "all .15s",
            }}
          >
            {c.icon ?? meta?.icon ?? "📦"} {c.label} ({c.item_count})
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

type SortBy = "verified" | "rating" | "installs" | "newest";

export function MarketplacePage() {
  const toast = useToast();
  const { currentOrgId } = useOrg();
  const [listings, setListings]     = useState<Listing[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading]       = useState(true);
  const [search, setSearch]         = useState("");
  const [category, setCategory]     = useState("all");
  const [sortBy, setSortBy]         = useState<SortBy>("installs");
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installedIds, setInstalledIds] = useState<Set<string>>(new Set());
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [searchTimer, setSearchTimer] = useState<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (q = "", type = "all") => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ per_page: "50" });
      if (type !== "all") params.set("type", type);
      let d: ListingsResponse;
      if (q) {
        params.set("q", q);
        const r = await apiFetch(`/marketplace/search?${params}`);
        if (!r.ok) throw new Error();
        d = await parseJSON<ListingsResponse>(r, "/marketplace/search");
      } else {
        const r = await apiFetch(`/marketplace/listings?${params}`);
        if (!r.ok) throw new Error();
        d = await parseJSON<ListingsResponse>(r, "/marketplace/listings");
      }
      setListings(d.items ?? []);
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
      const d = await parseJSON<Category[]>(r, "/marketplace/categories");
      setCategories(d);
    } catch { /* best-effort */ }
  }, []);

  useEffect(() => { void Promise.resolve().then(() => { void load(); void loadCategories(); }); }, [load, loadCategories]);

  const handleSearch = (q: string) => {
    setSearch(q);
    if (searchTimer) clearTimeout(searchTimer);
    setSearchTimer(setTimeout(() => void load(q, category), 350));
  };

  const handleCategory = (c: string) => {
    setCategory(c);
    void load(search, c);
  };

  const handleInstall = async (id: string) => {
    if (!currentOrgId) { toast("Select an organization first", "err"); return; }
    setInstalling(p => ({ ...p, [id]: true }));
    try {
      const r = await apiFetch(`/marketplace/listings/${id}/install`, { method: "POST" });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body?.detail ?? "Installation failed");
      }
      toast("Installed successfully!", "ok");
      setInstalledIds(prev => new Set(prev).add(id));
      void load(search, category);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Installation failed", "err");
    } finally {
      setInstalling(p => ({ ...p, [id]: false }));
    }
  };

  const handleUninstall = async (id: string) => {
    if (!currentOrgId) return;
    setInstalling(p => ({ ...p, [id]: true }));
    try {
      const r = await apiFetch(`/marketplace/listings/${id}/uninstall`, { method: "POST" });
      if (!r.ok) throw new Error();
      toast("Uninstalled", "ok");
      setInstalledIds(prev => { const next = new Set(prev); next.delete(id); return next; });
    } catch {
      toast("Uninstall failed", "err");
    } finally {
      setInstalling(p => ({ ...p, [id]: false }));
    }
  };

  const toggleDetails = (id: string) => setExpandedId(prev => (prev === id ? null : id));

  // Sort
  const sorted = [...listings].sort((a, b) => {
    if (sortBy === "verified") return (b.verified ? 1 : 0) - (a.verified ? 1 : 0);
    if (sortBy === "rating")   return b.rating - a.rating;
    if (sortBy === "installs") return b.installs - a.installs;
    if (sortBy === "newest")   return b.created_at - a.created_at;
    return 0;
  });

  const SORT_OPTIONS: [SortBy, string][] = [
    ["verified", "Verified"],
    ["rating",   "Top Rated"],
    ["installs", "Most Used"],
    ["newest",   "Newest"],
  ];

  const expandedItem = expandedId ? listings.find(l => l.id === expandedId) ?? null : null;

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
                         background: "rgba(108,142,247,.15)", color: C.blue, border: "1px solid rgba(108,142,247,.3)" }}>
            {listings.length} items
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            {SORT_OPTIONS.map(([id, label]) => (
              <button key={id} onClick={() => setSortBy(id)} style={{
                padding: "6px 12px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 500,
                background: sortBy === id ? "rgba(108,142,247,.18)" : "rgba(255,255,255,.04)",
                color: sortBy === id ? C.blue : "var(--t4)",
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
            <button onClick={() => { setSearch(""); void load("", category); }} style={{
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
        {expandedItem && (
          <DetailPanel
            item={expandedItem}
            onClose={() => setExpandedId(null)}
            canManage={!!currentOrgId}
            onRolledBack={() => void load(search, category)}
          />
        )}
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
                onInstall={id => void handleInstall(id)}
                onUninstall={id => void handleUninstall(id)}
                onToggleDetails={toggleDetails}
                installing={!!installing[item.id]}
                installed={installedIds.has(item.id)}
                expanded={expandedId === item.id}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
