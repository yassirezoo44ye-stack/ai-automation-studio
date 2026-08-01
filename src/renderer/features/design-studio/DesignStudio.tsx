import { useState, useCallback, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { DesignProvider, useDesign } from "./stores/designStore";
import { apiFetch } from "../../utils/api";
import { useToast } from "../../contexts/toast";
import { importPipeline } from "./core/import/ImportPipeline";
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
import { findById, loadJSONToCanvas } from "./utils/fabricUtils";
import styles                        from "./DesignStudio.module.css";

function DesignStudioInner() {
  const { t } = useTranslation("designStudio");
  const toast = useToast();
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
          bringForward, sendBackward,
          zoomIn, zoomOut, zoomReset, getThumbnail } = fabricCanvas;

  // History
  const { saveSnapshot, undo, redo, canUndo, canRedo } = useHistory(
    getCanvas,
    useCallback((index: number, length: number) => {
      dispatch({ type: "SET_HISTORY", index, length });
    }, [dispatch]),
  );

  // Direct canvas manipulation (drag / resize / rotate via handles) fires
  // Fabric's "object:modified" only on user interaction, never on
  // programmatic .set() calls — safe to snapshot on every occurrence.
  useEffect(() => {
    const fc = getCanvas();
    if (!fc) return;
    const handler = () => saveSnapshot("modify");
    fc.on("object:modified", handler);
    return () => { fc.off("object:modified", handler); };
  }, [getCanvas, saveSnapshot]);

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
    if (["rect", "circle", "triangle", "line"].includes(tool)) {
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

  // Apply an AI-generated design (full Fabric.js JSON) to the current page
  const handleApplyGeneratedDesign = useCallback(async (canvasJson: object, width: number, height: number) => {
    const fc = getCanvas();
    if (!fc) return;
    fc.set({ width, height });
    await loadJSONToCanvas(fc, canvasJson);
    saveSnapshot("ai generate design");
  }, [getCanvas, saveSnapshot]);

  // Layer ordering
  const handleBringForward = useCallback(() => {
    bringForward();
    saveSnapshot("bring forward");
  }, [bringForward, saveSnapshot]);

  const handleSendBackward = useCallback(() => {
    sendBackward();
    saveSnapshot("send backward");
  }, [sendBackward, saveSnapshot]);

  // Import a Fabric.js JSON design file onto the current page
  const handleImport = useCallback(async (file: File) => {
    const fc = getCanvas();
    if (!fc) return;
    try {
      await importPipeline.import(file, fc);
      saveSnapshot("import");
    } catch {
      toast(t("topToolbar.importFailed"), "err");
    }
  }, [getCanvas, saveSnapshot, toast, t]);

  // Insert an asset image onto the canvas
  const handleInsertImage = useCallback((src: string) => {
    void addImage(src).then(() => saveSnapshot("insert image"));
  }, [addImage, saveSnapshot]);

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
    { id: "layers",     label: t("shell.sidePanels.layers")     },
    { id: "assets",     label: t("shell.sidePanels.assets")     },
    { id: "templates",  label: t("shell.sidePanels.templates")  },
    { id: "pages",      label: t("shell.sidePanels.pages")      },
    { id: "brand",      label: t("shell.sidePanels.brand")      },
    { id: "components", label: t("shell.sidePanels.components") },
    { id: "tokens",     label: t("shell.sidePanels.tokens")     },
    { id: "history",    label: t("shell.sidePanels.history")    },
    { id: "ai",         label: t("shell.sidePanels.ai")         },
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
        onImport={file => void handleImport(file)}
      />

      <div className={styles.body}>
        {/* Left tool panel */}
        <LeftToolbar activeTool={state.tool} onToolChange={handleToolChange} />

        {/* Left panel tabs */}
        <div className={styles.leftPanel}>
          <div className={styles.panelTabs} role="tablist" aria-label={t("shell.panelTabsAriaLabel")}>
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
              <AssetsPanel onInsert={handleInsertImage} />
            )}
            {state.activePanel === "templates"  && (
              <TemplatesPanel onApply={tpl => void handleApplyTemplate(tpl)} />
            )}
            {state.activePanel === "pages"      && <PagesPanel />}
            {state.activePanel === "brand"      && <BrandKitPanel />}
            {state.activePanel === "components" && <ComponentsPanel getCanvas={getCanvas} />}
            {state.activePanel === "tokens"     && <TokensPanel />}
            {state.activePanel === "history"    && <HistoryPanel />}
            {state.activePanel === "ai"         && (
              <AIPanel
                getCanvas={getCanvas}
                onApplyDesign={(json, w, h) => void handleApplyGeneratedDesign(json, w, h)}
              />
            )}
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
          >{t("shell.propertiesHeading")}</div>
          <PropertiesPanel
            getCanvas={getCanvas}
            selectedIds={state.selectedIds}
            onBringForward={handleBringForward}
            onSendBackward={handleSendBackward}
          />

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
      <div className={styles.pageStrip} role="navigation" aria-label={t("shell.pageNavAriaLabel")}>
        {state.project.pages.map((page, idx) => (
          <button
            key={page.id}
            className={`${styles.pageThumb} ${page.id === state.project.currentPageId ? styles.activePage : ""}`}
            onClick={() => dispatch({ type: "SET_PAGE", pageId: page.id })}
            title={page.name}
            aria-label={t("shell.pageAriaLabel", { name: page.name, num: idx + 1 })}
            aria-current={page.id === state.project.currentPageId ? "page" : undefined}
          >
            {idx + 1}
          </button>
        ))}
        <button
          className={styles.addPage}
          onClick={() => dispatch({ type: "ADD_PAGE", page: { id: `p_${Date.now()}`, name: t("shell.defaultPageName", { num: state.project.pages.length + 1 }), width: 1280, height: 720, backgroundColor: "#ffffff", json: { version: "6.6.0", objects: [] }, thumbnail: "" } })}
          title={t("shell.addPage")}
          aria-label={t("shell.addNewPageAriaLabel")}
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
