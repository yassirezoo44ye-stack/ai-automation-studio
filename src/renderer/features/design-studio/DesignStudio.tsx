import { useState, useCallback, useRef } from "react";
import { DesignProvider, useDesign } from "./stores/designStore";
import { apiFetch } from "../../utils/api";
import { useFabricCanvas }           from "./hooks/useFabricCanvas";
import { useHistory }                from "./hooks/useHistory";
import { useKeyboard }               from "./hooks/useKeyboard";
import { useAutoSave }               from "./hooks/useAutoSave";
import { CanvasView }                from "./components/Canvas/CanvasView";
import { CanvasMinimap }             from "./components/Canvas/CanvasMinimap";
import { LeftToolbar }               from "./components/Toolbar/LeftToolbar";
import { TopToolbar }                from "./components/Toolbar/TopToolbar";
import { LayersPanel }               from "./components/Panels/LayersPanel";
import { AssetsPanel }               from "./components/Panels/AssetsPanel";
import { TemplatesPanel }            from "./components/Panels/TemplatesPanel";
import { PagesPanel }                from "./components/Panels/PagesPanel";
import { BrandKitPanel }             from "./components/Panels/BrandKitPanel";
import { ComponentsPanel }           from "./components/Panels/ComponentsPanel";
import { TokensPanel }               from "./components/Panels/TokensPanel";
import { HistoryPanel }              from "./components/Panels/HistoryPanel";
import { AIPanel }                   from "./components/Panels/AIPanel";
import { PropertiesPanel }           from "./components/Panels/PropertiesPanel";
import { ExportModal }               from "./components/Modals/ExportModal";
import type { PanelId, Tool }        from "./types/canvas.types";
import type { Template }             from "./types/canvas.types";
import { findById }                  from "./utils/fabricUtils";
import styles                        from "./DesignStudio.module.css";

function DesignStudioInner() {
  const { state, dispatch, setTool, setSelectedIds, setPanel } = useDesign();
  const [showExport, setShowExport] = useState(false);
  const designIdRef = useRef<string | null>(null);

  // Fabric canvas
  const fabricCanvas = useFabricCanvas(
    useCallback((json: object) => {
      dispatch({ type: "UPDATE_PAGE_JSON", pageId: state.project.currentPageId, json });
    }, [dispatch, state.project.currentPageId]),
    useCallback((ids: string[]) => {
      setSelectedIds(ids);
    }, [setSelectedIds]),
  );

  const { getCanvas, addShape, addText, addImage, deleteSelected, copySelected,
          pasteClipboard, selectAll, clearSelection, setActiveTool,
          zoomIn, zoomOut, zoomReset, getThumbnail } = fabricCanvas;

  // History
  const { saveSnapshot, undo, redo, canUndo, canRedo } = useHistory(
    getCanvas,
    useCallback((index: number, length: number) => {
      dispatch({ type: "SET_HISTORY", index, length });
    }, [dispatch]),
  );

  // Auto-save: persist canvas JSON to /api/design/canvases
  useAutoSave({
    project: state.project,
    unsaved: state.unsaved,
    onSave:  useCallback(async (proj) => {
      const page = proj.pages.find(p => p.id === proj.currentPageId);
      if (!page) return;
      try {
        const r = await apiFetch("/api/design/canvases", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            design_id:   designIdRef.current,
            name:        proj.name,
            canvas_json: page.json ?? {},
            thumbnail:   getThumbnail(),
            width:       page.width,
            height:      page.height,
          }),
        });
        if (r.ok) {
          const data = await r.json() as { id: string };
          designIdRef.current = data.id;
        }
      } catch { /* network unavailable — fail silently */ }
    }, [getThumbnail]),
    onSaved: () => dispatch({ type: "MARK_SAVED" }),
    enabled: true,
  });

  // Tool change handler
  const handleToolChange = useCallback((tool: Tool) => {
    setTool(tool);
    setActiveTool(tool);
    if (["rect", "circle", "triangle"].includes(tool)) {
      addShape(tool);
      saveSnapshot("add shape");
      setTool("select");
      setActiveTool("select");
    } else if (tool === "text") {
      addText();
      saveSnapshot("add text");
      setTool("select");
      setActiveTool("select");
    }
  }, [setTool, setActiveTool, addShape, addText, saveSnapshot]);

  // Keyboard shortcuts
  useKeyboard({
    getCanvas,
    undo: () => void undo(),
    redo: () => void redo(),
    onToolChange: handleToolChange,
    onDelete:    () => { deleteSelected(); saveSnapshot("delete"); },
    onCopy:      copySelected,
    onPaste:     () => { pasteClipboard(); saveSnapshot("paste"); },
    onSelectAll: selectAll,
    onEscape:    clearSelection,
    onZoomIn:    zoomIn,
    onZoomOut:   zoomOut,
    onZoomReset: zoomReset,
  });

  // Template apply
  const handleApplyTemplate = useCallback(async (tpl: Template) => {
    const fc = getCanvas();
    if (!fc) return;
    fc.set({ width: tpl.width, height: tpl.height });
    fc.clear();
    fc.renderAll();
    saveSnapshot("apply template");
  }, [getCanvas, saveSnapshot]);

  // Select layer by id
  const handleLayerSelect = useCallback((id: string) => {
    const fc = getCanvas();
    if (!fc) return;
    const obj = findById(fc, id);
    if (obj) { fc.setActiveObject(obj); fc.renderAll(); }
  }, [getCanvas]);

  // Manual save: capture thumbnail, persist, mark saved
  const handleSave = useCallback(async () => {
    const thumb = getThumbnail();
    dispatch({ type: "UPDATE_PAGE_THUMB", pageId: state.project.currentPageId, thumbnail: thumb });
    const page = state.project.pages.find(p => p.id === state.project.currentPageId);
    if (page) {
      try {
        const r = await apiFetch("/api/design/canvases", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            design_id:   designIdRef.current,
            name:        state.project.name,
            canvas_json: page.json ?? {},
            thumbnail:   thumb,
            width:       page.width,
            height:      page.height,
          }),
        });
        if (r.ok) {
          const data = await r.json() as { id: string };
          designIdRef.current = data.id;
        }
      } catch { /* persist failure is non-fatal */ }
    }
    dispatch({ type: "MARK_SAVED" });
  }, [dispatch, getThumbnail, state.project]);

  const currentPage = state.project.pages.find(p => p.id === state.project.currentPageId);

  const SIDE_PANELS: { id: PanelId; label: string }[] = [
    { id: "layers",     label: "Layers"    },
    { id: "assets",     label: "Assets"    },
    { id: "templates",  label: "Templates" },
    { id: "pages",      label: "Pages"     },
    { id: "brand",      label: "Brand"     },
    { id: "components", label: "Components"},
    { id: "tokens",     label: "Tokens"    },
    { id: "history",    label: "History"   },
    { id: "ai",         label: "AI"        },
  ];

  return (
    <div className={styles.studio}>
      {/* Top bar */}
      <TopToolbar
        projectName={state.project.name}
        unsaved={state.unsaved}
        historyIndex={state.historyIndex}
        historyLength={state.historyLength}
        zoom={state.viewport.zoom}
        canUndo={canUndo()}
        canRedo={canRedo()}
        onUndo={() => void undo()}
        onRedo={() => void redo()}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onZoomReset={zoomReset}
        onExport={() => setShowExport(true)}
        onSave={handleSave}
      />

      <div className={styles.body}>
        {/* Left tool panel */}
        <LeftToolbar activeTool={state.tool} onToolChange={handleToolChange} />

        {/* Left panel tabs */}
        <div className={styles.leftPanel}>
          <div className={styles.panelTabs} role="tablist" aria-label="Design panels">
            {SIDE_PANELS.map(p => (
              <button
                key={p.id}
                role="tab"
                aria-selected={state.activePanel === p.id}
                className={`${styles.panelTab} ${state.activePanel === p.id ? styles.active : ""}`}
                onClick={() => setPanel(p.id)}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className={styles.panelContent}>
            {state.activePanel === "layers"     && (
              <LayersPanel
                state={state}
                getCanvas={getCanvas}
                onSelect={handleLayerSelect}
              />
            )}
            {state.activePanel === "assets"     && (
              <AssetsPanel onInsert={src => void addImage(src)} />
            )}
            {state.activePanel === "templates"  && (
              <TemplatesPanel onApply={tpl => void handleApplyTemplate(tpl)} />
            )}
            {state.activePanel === "pages"      && <PagesPanel />}
            {state.activePanel === "brand"      && <BrandKitPanel />}
            {state.activePanel === "components" && <ComponentsPanel getCanvas={getCanvas} />}
            {state.activePanel === "tokens"     && <TokensPanel />}
            {state.activePanel === "history"    && <HistoryPanel />}
            {state.activePanel === "ai"         && <AIPanel getCanvas={getCanvas} />}
          </div>
        </div>

        {/* Canvas area */}
        <div className={styles.canvasArea}>
          <CanvasView fabricCanvas={fabricCanvas} state={state} />
        </div>

        {/* Right properties panel */}
        <div className={styles.rightPanel}>
          <div
            className={styles.rightPanelHeader}
            role="heading"
            aria-level={2}
          >Properties</div>
          <PropertiesPanel getCanvas={getCanvas} selectedIds={state.selectedIds} />

          {/* Minimap */}
          <div className={styles.minimapWrap}>
            <CanvasMinimap
              getCanvas={getCanvas}
              viewport={state.viewport}
              canvasWidth={currentPage?.width  ?? 1280}
              canvasHeight={currentPage?.height ?? 720}
            />
          </div>
        </div>
      </div>

      {/* Page strip — quick page switcher at the bottom */}
      <div className={styles.pageStrip} role="navigation" aria-label="Page navigation">
        {state.project.pages.map((page, idx) => (
          <button
            key={page.id}
            className={`${styles.pageThumb} ${page.id === state.project.currentPageId ? styles.activePage : ""}`}
            onClick={() => dispatch({ type: "SET_PAGE", pageId: page.id })}
            title={page.name}
            aria-label={`${page.name} (page ${idx + 1})`}
            aria-current={page.id === state.project.currentPageId ? "page" : undefined}
          >
            {idx + 1}
          </button>
        ))}
        <button
          className={styles.addPage}
          onClick={() => dispatch({ type: "ADD_PAGE", page: { id: `p_${Date.now()}`, name: `Page ${state.project.pages.length + 1}`, width: 1280, height: 720, backgroundColor: "#ffffff", json: { version: "6.6.0", objects: [] }, thumbnail: "" } })}
          title="Add page"
          aria-label="Add new page"
        >
          +
        </button>
      </div>

      {showExport && (
        <ExportModal getCanvas={getCanvas} onClose={() => setShowExport(false)} />
      )}
    </div>
  );
}

export function DesignStudio() {
  return (
    <DesignProvider>
      <DesignStudioInner />
    </DesignProvider>
  );
}
