import { useEffect, useRef, useState, useCallback } from "react";
import * as fabric from "fabric";

const API = "http://127.0.0.1:8000";

type Tool = "select" | "text" | "rect" | "circle" | "triangle" | "line" | "pen";
type Template = { name: string; w: number; h: number; icon: string };

const TEMPLATES: Template[] = [
  { name: "Instagram Post",  w: 1080, h: 1080, icon: "📸" },
  { name: "Instagram Story", w: 1080, h: 1920, icon: "📱" },
  { name: "Facebook Cover",  w: 820,  h: 312,  icon: "📘" },
  { name: "Facebook Post",   w: 1200, h: 630,  icon: "🖼" },
  { name: "Twitter Header",  w: 1500, h: 500,  icon: "🐦" },
  { name: "YouTube Thumb",   w: 1280, h: 720,  icon: "▶" },
  { name: "LinkedIn Banner", w: 1584, h: 396,  icon: "💼" },
  { name: "A4 Portrait",     w: 794,  h: 1123, icon: "📄" },
  { name: "Presentation",    w: 1920, h: 1080, icon: "🎯" },
  { name: "Business Card",   w: 1050, h: 600,  icon: "💳" },
];

const FONTS = [
  "Cairo", "Tajawal", "Almarai", "Noto Sans Arabic",
  "Inter", "Roboto", "Montserrat", "Playfair Display", "Poppins", "Arial",
];

const GRADIENTS = [
  ["#667eea","#764ba2"], ["#f093fb","#f5576c"], ["#4facfe","#00f2fe"],
  ["#43e97b","#38f9d7"], ["#fa709a","#fee140"], ["#a18cd1","#fbc2eb"],
  ["#ffecd2","#fcb69f"], ["#ff9a9e","#fecfef"], ["#a1c4fd","#c2e9fb"],
  ["#d4fc79","#96e6a1"],
];

const SHAPE_COLORS = [
  "#ffffff","#000000","#6366f1","#8b5cf6","#ec4899","#f59e0b",
  "#10b981","#3b82f6","#ef4444","#f97316","#14b8a6","#8b5cf6",
];

export default function DesignStudio({ toast }: { toast: (m: string, k?: "ok"|"err"|"info") => void }) {
  const canvasElRef   = useRef<HTMLCanvasElement>(null);
  const fabricRef     = useRef<fabric.Canvas | null>(null);
  const wrapRef       = useRef<HTMLDivElement>(null);
  const fileRef       = useRef<HTMLInputElement>(null);

  const [tool, setTool]               = useState<Tool>("select");
  const [template, setTemplate]       = useState<Template>(TEMPLATES[0]);
  const [zoom, setZoom]               = useState(0.45);
  const [selected, setSelected]       = useState<fabric.FabricObject | null>(null);
  const [bgColor, setBgColor]         = useState("#1a1a2e");
  const [showTemplates, setShowTempl] = useState(false);
  const [showGradients, setShowGrad]  = useState(false);
  const [aiPrompt, setAiPrompt]       = useState("");
  const [aiLoading, setAiLoading]     = useState(false);

  // Text props
  const [fontSize, setFontSize]   = useState(48);
  const [fontFamily, setFontFam]  = useState("Cairo");
  const [textColor, setTextColor] = useState("#ffffff");
  const [bold, setBold]           = useState(false);
  const [italic, setItalic]       = useState(false);
  const [textAlign, setTextAlign] = useState<"left"|"center"|"right">("center");

  // Shape props
  const [fillColor, setFillColor]     = useState("#6366f1");
  const [strokeColor, setStrokeColor] = useState("transparent");
  const [strokeWidth, setStrokeW]     = useState(0);
  const [opacity, setOpacity]         = useState(100);

  // Init canvas
  useEffect(() => {
    if (!canvasElRef.current || fabricRef.current) return;
    let fc: fabric.Canvas;
    try {
      fc = new fabric.Canvas(canvasElRef.current, {
        width: template.w * zoom,
        height: template.h * zoom,
        backgroundColor: bgColor,
        selection: true,
        preserveObjectStacking: true,
      });
    } catch (e) {
      console.error("Fabric init error:", e);
      return;
    }
    fabricRef.current = fc;

    fc.on("selection:created",  (e: any) => setSelected(e.selected?.[0] ?? null));
    fc.on("selection:updated",  (e: any) => setSelected(e.selected?.[0] ?? null));
    fc.on("selection:cleared",  () => setSelected(null));
    fc.on("mouse:down", (e: any) => {
      if (!e.target) handleCanvasClick(fc, e);
    });

    return () => { try { fc.dispose(); } catch {} fabricRef.current = null; };
  }, []);

  // Resize canvas when template or zoom changes
  useEffect(() => {
    const fc = fabricRef.current; if (!fc) return;
    fc.setDimensions({ width: template.w * zoom, height: template.h * zoom });
    fc.setZoom(zoom);
    fc.renderAll();
  }, [template, zoom]);

  // Background color
  useEffect(() => {
    const fc = fabricRef.current; if (!fc) return;
    fc.backgroundColor = bgColor;
    fc.renderAll();
  }, [bgColor]);

  // Tool cursor
  useEffect(() => {
    const fc = fabricRef.current; if (!fc) return;
    fc.defaultCursor = tool === "select" ? "default" : "crosshair";
    fc.isDrawingMode = tool === "pen";
    if (tool === "pen" && fc.freeDrawingBrush) {
      fc.freeDrawingBrush.color = fillColor;
      fc.freeDrawingBrush.width = 3;
    }
  }, [tool, fillColor]);

  function handleCanvasClick(fc: fabric.Canvas, e: any) {
    const pt = fc.getScenePoint ? fc.getScenePoint(e.e) : (fc as any).getPointer(e.e);
    const x = pt.x, y = pt.y;

    if (tool === "text") {
      const obj = new fabric.IText("اكتب هنا", {
        left: x, top: y,
        fontSize, fontFamily, fill: textColor,
        fontWeight: bold ? "bold" : "normal",
        fontStyle: italic ? "italic" : "normal",
        textAlign, originX: "center", originY: "center",
        scaleX: 1/1, scaleY: 1/1,
      });
      fc.add(obj); fc.setActiveObject(obj); obj.enterEditing(); setTool("select");
    } else if (tool === "rect") {
      const obj = new fabric.Rect({ left: x - 100, top: y - 60, width: 200, height: 120, fill: fillColor, stroke: strokeColor, strokeWidth, opacity: opacity/100, rx: 8, ry: 8 });
      fc.add(obj); fc.setActiveObject(obj); setTool("select");
    } else if (tool === "circle") {
      const obj = new fabric.Circle({ left: x - 60, top: y - 60, radius: 60, fill: fillColor, stroke: strokeColor, strokeWidth, opacity: opacity/100 });
      fc.add(obj); fc.setActiveObject(obj); setTool("select");
    } else if (tool === "triangle") {
      const obj = new fabric.Triangle({ left: x - 70, top: y - 60, width: 140, height: 120, fill: fillColor, stroke: strokeColor, strokeWidth, opacity: opacity/100 });
      fc.add(obj); fc.setActiveObject(obj); setTool("select");
    } else if (tool === "line") {
      const obj = new fabric.Line([x - 80, y, x + 80, y], { stroke: fillColor, strokeWidth: Math.max(strokeWidth, 3), opacity: opacity/100 });
      fc.add(obj); fc.setActiveObject(obj); setTool("select");
    }
    fc.renderAll();
  }

  // Update selected object properties
  useEffect(() => {
    const obj = selected; if (!obj) return;
    if (obj instanceof fabric.IText || obj instanceof fabric.Textbox) {
      obj.set({ fontSize, fontFamily, fill: textColor, fontWeight: bold ? "bold" : "normal", fontStyle: italic ? "italic" : "normal", textAlign });
    } else {
      obj.set({ fill: fillColor, stroke: strokeColor, strokeWidth, opacity: opacity/100 });
    }
    fabricRef.current?.renderAll();
  }, [fontSize, fontFamily, textColor, bold, italic, textAlign, fillColor, strokeColor, strokeWidth, opacity]);

  // Load selected props into state
  useEffect(() => {
    if (!selected) return;
    setOpacity(Math.round((selected.opacity ?? 1) * 100));
    if (selected instanceof fabric.IText || selected instanceof fabric.Textbox) {
      setFontSize((selected.fontSize as number) ?? 48);
      setFontFam((selected.fontFamily as string) ?? "Cairo");
      setTextColor((selected.fill as string) ?? "#ffffff");
      setBold(selected.fontWeight === "bold");
      setItalic(selected.fontStyle === "italic");
    } else {
      setFillColor((selected.fill as string) ?? "#6366f1");
      setStrokeColor((selected.stroke as string) ?? "transparent");
      setStrokeW((selected.strokeWidth as number) ?? 0);
    }
  }, [selected]);

  function applyGradient(c1: string, c2: string) {
    const fc = fabricRef.current; if (!fc) return;
    const grad = new fabric.Gradient({
      type: "linear",
      coords: { x1: 0, y1: 0, x2: template.w, y2: template.h },
      colorStops: [{ offset: 0, color: c1 }, { offset: 1, color: c2 }],
    });
    fc.backgroundColor = grad as unknown as string;
    fc.renderAll();
    setShowGrad(false);
    toast("تم تطبيق التدرج");
  }

  function addTextbox() {
    const fc = fabricRef.current; if (!fc) return;
    const obj = new fabric.IText("اكتب هنا", {
      left: template.w / 2, top: template.h / 2,
      fontSize, fontFamily, fill: textColor, fontWeight: bold ? "bold" : "normal",
      fontStyle: italic ? "italic" : "normal", textAlign, originX: "center", originY: "center",
    });
    fc.add(obj); fc.setActiveObject(obj); obj.enterEditing(); setTool("select");
  }

  function uploadImage() { fileRef.current?.click(); }
  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => {
      const url = ev.target?.result as string;
      fabric.FabricImage.fromURL(url).then(img => {
        const fc = fabricRef.current; if (!fc) return;
        const scale = Math.min(400 / (img.width ?? 400), 300 / (img.height ?? 300));
        img.set({ left: template.w/2, top: template.h/2, originX: "center", originY: "center", scaleX: scale, scaleY: scale });
        fc.add(img); fc.setActiveObject(img); fc.renderAll();
      });
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  }

  function deleteSelected() {
    const fc = fabricRef.current; if (!fc) return;
    const objs = fc.getActiveObjects();
    objs.forEach(o => fc.remove(o));
    fc.discardActiveObject(); fc.renderAll();
    toast("تم الحذف");
  }

  function duplicateSelected() {
    const fc = fabricRef.current; const obj = selected; if (!fc || !obj) return;
    obj.clone().then((clone: fabric.FabricObject) => {
      clone.set({ left: (obj.left ?? 0) + 20, top: (obj.top ?? 0) + 20 });
      fc.add(clone); fc.setActiveObject(clone); fc.renderAll();
    });
  }

  function bringForward()  { selected && fabricRef.current?.bringObjectForward(selected); fabricRef.current?.renderAll(); }
  function sendBackward()  { selected && fabricRef.current?.sendObjectBackwards(selected); fabricRef.current?.renderAll(); }

  function exportPNG() {
    const fc = fabricRef.current; if (!fc) return;
    const origZoom = fc.getZoom();
    fc.setZoom(1); fc.setDimensions({ width: template.w, height: template.h });
    fc.renderAll();
    const url = fc.toDataURL({ format: "png", multiplier: 1 });
    const a = document.createElement("a"); a.href = url; a.download = "design.png"; a.click();
    fc.setZoom(origZoom); fc.setDimensions({ width: template.w * origZoom, height: template.h * origZoom });
    fc.renderAll(); toast("تم التصدير PNG");
  }

  function exportJSON() {
    const fc = fabricRef.current; if (!fc) return;
    const json = JSON.stringify(fc.toJSON());
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "design.json"; a.click();
    URL.revokeObjectURL(url); toast("تم التصدير JSON");
  }

  function clearCanvas() {
    if (!confirm("مسح كل العناصر؟")) return;
    const fc = fabricRef.current; if (!fc) return;
    fc.getObjects().forEach(o => fc.remove(o));
    fc.renderAll(); toast("تم المسح");
  }

  async function aiGenerate() {
    if (!aiPrompt.trim()) return;
    setAiLoading(true);
    try {
      const res = await fetch(`${API}/api/design/ai-generate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: aiPrompt, template: template.name }),
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      const data = await res.json();
      const fc = fabricRef.current; if (!fc) return;
      fc.loadFromJSON(data.canvas_json).then(() => { fc.renderAll(); toast("تم توليد التصميم بالذكاء الاصطناعي"); });
    } catch (e: any) { toast(e.message, "err"); }
    finally { setAiLoading(false); }
  }

  const isText = selected instanceof fabric.IText || selected instanceof fabric.Textbox;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "#05070f" }}>
      {/* Top toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 16px", borderBottom: "1px solid rgba(255,255,255,.06)", background: "rgba(8,10,20,.8)", backdropFilter: "blur(12px)", flexShrink: 0, flexWrap: "wrap" }}>
        {/* Template picker */}
        <div style={{ position: "relative" }}>
          <button onClick={() => setShowTempl(p => !p)} style={TB.btn}>
            {template.icon} {template.name} <span style={{ opacity: .5, fontSize: 10 }}>▼</span>
          </button>
          {showTemplates && (
            <div style={{ position: "absolute", top: "110%", left: 0, background: "#0d0f1a", border: "1px solid rgba(255,255,255,.08)", borderRadius: 12, padding: 8, zIndex: 999, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, width: 300, boxShadow: "0 20px 40px rgba(0,0,0,.6)" }}>
              {TEMPLATES.map(t => (
                <button key={t.name} onClick={() => { setTemplate(t); setShowTempl(false); }}
                  style={{ ...TB.btn, textAlign: "left", justifyContent: "flex-start", fontSize: 12, gap: 6, background: template.name === t.name ? "rgba(139,92,246,.2)" : "transparent" }}>
                  {t.icon} {t.name} <span style={{ opacity:.4, fontSize:10 }}>{t.w}×{t.h}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div style={TB.sep} />

        {/* Tools */}
        {([
          ["select","⬚","تحديد"],["text","T","نص"],
          ["rect","▭","مستطيل"],["circle","○","دائرة"],
          ["triangle","△","مثلث"],["line","—","خط"],["pen","✎","رسم حر"],
        ] as [Tool,string,string][]).map(([id,icon,label]) => (
          <button key={id} title={label} onClick={() => setTool(id)}
            style={{ ...TB.btn, ...(tool === id ? TB.btnActive : {}), minWidth: 36, padding: "7px 10px", fontSize: id === "text" ? 15 : 13 }}>
            {icon}
          </button>
        ))}

        <div style={TB.sep} />

        <button onClick={addTextbox} style={TB.btn}>+ نص</button>
        <button onClick={uploadImage} style={TB.btn}>🖼 صورة</button>
        <input ref={fileRef} type="file" accept="image/*" onChange={onFileChange} style={{ display: "none" }} />

        <div style={{ position: "relative" }}>
          <button onClick={() => setShowGrad(p => !p)} style={TB.btn}>🎨 خلفية</button>
          {showGradients && (
            <div style={{ position: "absolute", top: "110%", left: 0, background: "#0d0f1a", border: "1px solid rgba(255,255,255,.08)", borderRadius: 12, padding: 10, zIndex: 999, boxShadow: "0 20px 40px rgba(0,0,0,.6)" }}>
              <div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap", width: 220 }}>
                {GRADIENTS.map(([c1,c2]) => (
                  <button key={c1} onClick={() => applyGradient(c1, c2)}
                    style={{ width: 36, height: 36, borderRadius: 8, border: "none", cursor: "pointer", background: `linear-gradient(135deg,${c1},${c2})`, transition: "transform .15s" }}
                    onMouseEnter={e => (e.currentTarget.style.transform = "scale(1.1)")}
                    onMouseLeave={e => (e.currentTarget.style.transform = "scale(1)")} />
                ))}
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{ fontSize: 11, color: "rgba(148,163,184,.5)" }}>لون مخصص:</span>
                <input type="color" value={bgColor} onChange={e => setBgColor(e.target.value)} style={{ width: 36, height: 28, borderRadius: 6, border: "none", cursor: "pointer" }} />
              </div>
            </div>
          )}
        </div>

        <div style={TB.sep} />

        {selected && (<>
          <button onClick={duplicateSelected} title="نسخ" style={TB.btn}>⧉</button>
          <button onClick={bringForward}      title="للأمام" style={TB.btn}>↑</button>
          <button onClick={sendBackward}      title="للخلف"  style={TB.btn}>↓</button>
          <button onClick={deleteSelected}    title="حذف"    style={{ ...TB.btn, color: "#f87171" }}>✕</button>
          <div style={TB.sep} />
        </>)}

        {/* Zoom */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button onClick={() => setZoom(z => Math.max(.1, +(z-.1).toFixed(1)))} style={TB.btn}>−</button>
          <span style={{ fontSize: 12, color: "rgba(148,163,184,.6)", width: 38, textAlign: "center" }}>{Math.round(zoom*100)}%</span>
          <button onClick={() => setZoom(z => Math.min(2, +(z+.1).toFixed(1)))} style={TB.btn}>+</button>
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button onClick={clearCanvas} style={{ ...TB.btn, color: "#f87171" }}>🗑</button>
          <button onClick={exportPNG}  style={{ ...TB.btnPrimary }}>⬇ PNG</button>
          <button onClick={exportJSON} style={TB.btn}>⬇ JSON</button>
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Left: Properties panel */}
        <div style={{ width: 240, borderRight: "1px solid rgba(255,255,255,.05)", overflowY: "auto", background: "rgba(8,10,20,.7)", flexShrink: 0, padding: "14px 12px", display: "flex", flexDirection: "column", gap: 14 }}>

          {/* AI Generate */}
          <div style={PP.section}>
            <div style={PP.title}>✨ AI Design</div>
            <textarea value={aiPrompt} onChange={e => setAiPrompt(e.target.value)}
              placeholder="صف التصميم الذي تريده…"
              style={{ width: "100%", background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 8, padding: "8px 10px", color: "#e2e8f0", fontSize: 12, lineHeight: 1.5, resize: "none", minHeight: 64, fontFamily: "inherit" }} />
            <button onClick={aiGenerate} disabled={aiLoading || !aiPrompt.trim()}
              style={{ ...TB.btnPrimary, width: "100%", marginTop: 6, fontSize: 12, padding: "8px" }}>
              {aiLoading ? "⏳ جاري التوليد…" : "✨ ولّد التصميم"}
            </button>
          </div>

          {isText ? (<>
            <div style={PP.section}>
              <div style={PP.title}>نص</div>
              <input type="number" value={fontSize} onChange={e => setFontSize(+e.target.value)} min={8} max={300}
                style={PP.input} placeholder="حجم الخط" />
              <select value={fontFamily} onChange={e => setFontFam(e.target.value)} style={{ ...PP.input, marginTop: 6 }}>
                {FONTS.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
              <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                <button onClick={() => setBold(b => !b)} style={{ ...TB.btn, flex: 1, fontWeight: 700, background: bold ? "rgba(139,92,246,.25)" : undefined }}>B</button>
                <button onClick={() => setItalic(i => !i)} style={{ ...TB.btn, flex: 1, fontStyle: "italic", background: italic ? "rgba(139,92,246,.25)" : undefined }}>I</button>
                {(["left","center","right"] as const).map(a => (
                  <button key={a} onClick={() => setTextAlign(a)} style={{ ...TB.btn, flex: 1, fontSize: 11, background: textAlign === a ? "rgba(139,92,246,.25)" : undefined }}>
                    {a === "left" ? "⫷" : a === "center" ? "≡" : "⫸"}
                  </button>
                ))}
              </div>
              <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
                <span style={PP.label}>لون</span>
                <input type="color" value={textColor} onChange={e => setTextColor(e.target.value)} style={PP.colorInput} />
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, flex: 1 }}>
                  {SHAPE_COLORS.slice(0,8).map(c => (
                    <button key={c} onClick={() => setTextColor(c)} style={{ width: 18, height: 18, borderRadius: 4, background: c, border: textColor === c ? "2px solid #8b5cf6" : "1px solid rgba(255,255,255,.1)", cursor: "pointer" }} />
                  ))}
                </div>
              </div>
            </div>
          </>) : (<>
            <div style={PP.section}>
              <div style={PP.title}>شكل</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={PP.label}>تعبئة</span>
                <input type="color" value={fillColor === "transparent" ? "#000000" : fillColor} onChange={e => setFillColor(e.target.value)} style={PP.colorInput} />
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 10 }}>
                {SHAPE_COLORS.map(c => (
                  <button key={c} onClick={() => setFillColor(c)} style={{ width: 22, height: 22, borderRadius: 5, background: c, border: fillColor === c ? "2px solid #8b5cf6" : "1px solid rgba(255,255,255,.1)", cursor: "pointer" }} />
                ))}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={PP.label}>حدود</span>
                <input type="color" value={strokeColor === "transparent" ? "#ffffff" : strokeColor} onChange={e => setStrokeColor(e.target.value)} style={PP.colorInput} />
                <input type="number" value={strokeWidth} onChange={e => setStrokeW(+e.target.value)} min={0} max={20} style={{ ...PP.input, width: 50 }} />
              </div>
            </div>
          </>)}

          <div style={PP.section}>
            <div style={PP.title}>شفافية</div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="range" min={0} max={100} value={opacity} onChange={e => setOpacity(+e.target.value)} style={{ flex: 1, accentColor: "#8b5cf6" }} />
              <span style={{ fontSize: 12, color: "rgba(148,163,184,.6)", width: 32, textAlign: "right" }}>{opacity}%</span>
            </div>
          </div>

          {/* Quick shapes */}
          <div style={PP.section}>
            <div style={PP.title}>عناصر سريعة</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {[
                ["مستطيل","rect"],["دائرة","circle"],
                ["مثلث","triangle"],["خط","line"],
                ["نص","text"],["صورة","image"],
              ].map(([label,id]) => (
                <button key={id} onClick={() => id === "image" ? uploadImage() : setTool(id as Tool)}
                  style={{ ...TB.btn, fontSize: 12, padding: "8px 6px" }}>
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Center: Canvas */}
        <div ref={wrapRef} style={{ flex: 1, overflow: "auto", display: "flex", alignItems: "flex-start", justifyContent: "center", padding: 32, background: "radial-gradient(circle at 50% 50%, rgba(139,92,246,.04), transparent 70%)" }}>
          <div style={{ boxShadow: "0 32px 80px rgba(0,0,0,.8), 0 0 0 1px rgba(255,255,255,.06)", borderRadius: 4, overflow: "hidden", flexShrink: 0 }}>
            <canvas ref={canvasElRef} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Toolbar styles ─────────────────────────────────────────────────────────────
const TB: Record<string, React.CSSProperties> = {
  btn: { background: "rgba(255,255,255,.05)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 8, padding: "7px 12px", color: "rgba(226,232,240,.8)", fontSize: 13, cursor: "pointer", display: "flex", alignItems: "center", gap: 5, transition: "all .15s", whiteSpace: "nowrap" },
  btnActive: { background: "rgba(139,92,246,.25)", borderColor: "rgba(139,92,246,.5)", color: "#e2e8f0", boxShadow: "0 0 12px rgba(139,92,246,.2)" },
  btnPrimary: { background: "linear-gradient(135deg,#8b5cf6,#6366f1)", border: "none", borderRadius: 8, padding: "7px 16px", color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer", boxShadow: "0 2px 12px rgba(139,92,246,.35)", whiteSpace: "nowrap" },
  sep: { width: 1, height: 28, background: "rgba(255,255,255,.07)", flexShrink: 0 },
};
const PP: Record<string, React.CSSProperties> = {
  section: { background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.06)", borderRadius: 10, padding: "12px 10px" },
  title:   { fontSize: 11, fontWeight: 600, color: "rgba(148,163,184,.5)", marginBottom: 10, letterSpacing: "0.05em", textTransform: "uppercase" },
  label:   { fontSize: 11, color: "rgba(148,163,184,.5)", whiteSpace: "nowrap" },
  input:   { width: "100%", background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 7, padding: "7px 10px", color: "#e2e8f0", fontSize: 12 },
  colorInput: { width: 32, height: 28, borderRadius: 7, border: "1px solid rgba(255,255,255,.1)", cursor: "pointer", padding: 0 },
};
