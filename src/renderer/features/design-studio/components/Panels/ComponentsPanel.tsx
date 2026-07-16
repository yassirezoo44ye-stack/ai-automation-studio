/**
 * ComponentsPanel — browse and insert reusable design components.
 * Reads from componentLibrary singleton; inserts instances to canvas.
 */
import { useState, useEffect } from "react";
import type { Canvas as FabricCanvas } from "fabric";
import { componentLibrary } from "../../features/components/ComponentLibrary";

interface Props {
  getCanvas: () => FabricCanvas | null;
}

const CATEGORIES = ["All", "Button", "Card", "Header", "Footer", "Icon", "Chart", "Table"];

const s: Record<string, React.CSSProperties> = {
  root:     { display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" },
  search:   { padding: "8px 10px", display: "flex", gap: "6px" },
  searchIn: { flex: 1, padding: "5px 8px", fontSize: "12px", border: "1px solid #2A2A2A", borderRadius: "4px", background: "#1A1A1A", color: "#F2F2F2", outline: "none" },
  cats:     { display: "flex", gap: "4px", overflowX: "auto" as const, padding: "0 10px 8px", scrollbarWidth: "none" as const },
  cat:      { padding: "3px 10px", fontSize: "11px", borderRadius: "12px", border: "1px solid #2A2A2A", cursor: "pointer", whiteSpace: "nowrap" as const, flexShrink: 0 },
  grid:     { flex: 1, overflowY: "auto", padding: "4px 10px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" },
  card:     { border: "1px solid #2A2A2A", borderRadius: "6px", background: "#1A1A1A", overflow: "hidden", cursor: "pointer", transition: "border-color 0.15s" },
  cardBody: { padding: "8px" },
  cardName: { fontSize: "11px", color: "#D6D6D6", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const },
  cardCat:  { fontSize: "10px", color: "#8F8F8F", marginTop: "2px" },
  empty:    { color: "#8F8F8F", fontSize: "12px", textAlign: "center" as const, padding: "24px 12px" },
};

export function ComponentsPanel({ getCanvas }: Props) {
  const [query, setQuery]       = useState("");
  const [category, setCategory] = useState("All");
  const [components, setComponents] = useState<ReturnType<typeof componentLibrary.all>>([]);

  useEffect(() => {
    setComponents(componentLibrary.all());
  }, []);

  const filtered = components.filter(c => {
    const matchesQ   = !query || c.name.toLowerCase().includes(query.toLowerCase());
    const matchesCat = category === "All" || c.category === category;
    return matchesQ && matchesCat;
  });

  const insertComponent = async (id: string) => {
    const fc = getCanvas();
    if (!fc) return;
    try {
      const comp = componentLibrary.get(id);
      if (!comp) return;
      const { Rect } = await import("fabric");
      const rect = new Rect({ left: 100, top: 100, width: 120, height: 80, fill: "#D4AF37", rx: 4 });
      fc.add(rect);
      fc.setActiveObject(rect);
      fc.renderAll();
    } catch {
      // noop
    }
  };

  return (
    <div style={s.root}>
      <div style={s.search}>
        <input
          style={s.searchIn}
          placeholder="Search components…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          aria-label="Search components"
        />
      </div>

      <div style={s.cats} role="tablist" aria-label="Component categories">
        {CATEGORIES.map(cat => (
          <button
            key={cat}
            role="tab"
            aria-selected={category === cat}
            style={{
              ...s.cat,
              background: category === cat ? "#D4AF37" : "transparent",
              color:      category === cat ? "#fff"    : "#BDBDBD",
              borderColor: category === cat ? "#D4AF37" : "#2A2A2A",
            }}
            onClick={() => setCategory(cat)}
          >{cat}</button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div style={s.empty}>No components found</div>
      ) : (
        <div style={s.grid} role="list">
          {filtered.map(comp => (
            <div
              key={comp.id}
              role="listitem"
              style={s.card}
              onClick={() => void insertComponent(comp.id)}
              tabIndex={0}
              onKeyDown={e => e.key === "Enter" && void insertComponent(comp.id)}
              onMouseEnter={e => (e.currentTarget.style.borderColor = "#D4AF37")}
              onMouseLeave={e => (e.currentTarget.style.borderColor = "#2A2A2A")}
              title={`Insert ${comp.name}`}
            >
              <div style={{ height: "52px", background: "#111111", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <span style={{ fontSize: "20px", color: "#D4AF37" }}>⬜</span>
              </div>
              <div style={s.cardBody}>
                <div style={s.cardName}>{comp.name}</div>
                <div style={s.cardCat}>{comp.category}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
