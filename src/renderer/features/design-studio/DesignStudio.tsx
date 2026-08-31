/**
 * DesignStudio — now the shell for "Flow App Builder".
 *
 * Phase 1 changes:
 *  - Left panel is now AppTreePanel (App Builder tree: APP/DATA/AI/AUTOMATION/DEPLOY)
 *  - "Insert & Design Tools" button switches back to the original LeftToolbar + panels
 *  - TopToolbar gains mode tabs (Design/Preview/Code/Deploy) and "✦ Build with AI"
 *  - AICommandBar modal opens on "Build with AI"
 *
 * All existing Fabric.js functionality is fully preserved:
 *  - LeftToolbar (Rect/Circle/Text/…) is accessible via Insert mode
 *  - All 9 side panels (Layers/Assets/Templates/Pages/Brand/Components/Tokens/History/AI)
 *    remain available in Insert mode, unchanged
 *  - Canvas, history, keyboard shortcuts, auto-save, brand kit — all untouched
 */
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
import { useBrandKit }               from "./hooks/useBrandKit";
import { CanvasView }                from "./components/Canvas/CanvasView";
import { CanvasMinimap }             from "./components/Canvas/CanvasMinimap";
import { LeftToolbar }               from "./components/Toolbar/LeftToolbar";
import { TopToolbar }                from "./components/Toolbar/TopToolbar";
import type { StudioMode }           from "./components/Toolbar/TopToolbar";
import { AppTreePanel }              from "./components/Panels/AppTreePanel";
import type { AppSection }           from "./components/Panels/AppTreePanel";
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
import { AICommandBar }              from "./components/Modals/AICommandBar";
import { AICommandBarInline }        from "./components/AICommandBarInline";
import type { AICommandResult }      from "./components/AICommandBarInline";
import type { PanelId, Tool }        from "./types/canvas.types";
import type { Template }             from "./types/canvas.types";
import { findById, loadJSONToCanvas } from "./utils/fabricUtils";
import { AIDesignEngine }            from "./features/ai/AIDesignEngine";
import styles                        from "./DesignStudio.module.css";

const _aiEngine = new AIDesignEngine();


function DesignStudioInner() {
  const { t } = useTranslation("designStudio");
  const toast = useToast();
  const { state, dispatch, setTool, setSelectedIds, setPanel } = useDesign();

  // ── App Builder state ─────────────────────────────────────────────────────
  const [studioMode,       setStudioMode]       = useState<StudioMode>("design");
  const [activeSection,    setActiveSection]     = useState<AppSection | null>(null);
  const [showAICommandBar, setShowAICommandBar]  = useState(false);

  // ── Existing state ────────────────────────────────────────────────────────
  const [showExport, setShowExport] = useState(false);
  const designIdRef = useRef<string | null>(null);

  // Brand Kit lifecycle
  useBrandKit();

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

  // Resume last design on mount
  const hasLoadedSavedDesignRef = useRef(false);
  useEffect(() => {
    if (hasLoadedSavedDesignRef.current) return;
    hasLoadedSavedDesignRef.current = true;
    void (async () => {
      try {
        const listRes = await apiFetch("/api/design/canvases?limit=1");
        if (!listRes.ok) return;
        const list = await listRes.json() as { id: string }[];
        if (!list.length) return;
        const detailRes = await apiFetch(`/api/design/canvases/${list[0].id}`);
        if (!detailRes.ok) return;
        const d = await detailRes.json() as {
          id: string; canvas_json: object; width: number; height: number;
        };
        const fc = getCanvas();
        if (!fc) return;
        fc.set({ width: d.width, height: d.height });
        await loadJSONToCanvas(fc, d.canvas_json ?? {});
        designIdRef.current = d.id;
      } catch { /* network unavailable — start blank */ }
    })();
  }, [getCanvas]);

  // History
  const { saveSnapshot, undo, redo, canUndo, canRedo } = useHistory(
    getCanvas,
    useCallback((index: number, length: number) => {
      dispatch({ type: "SET_HISTORY", index, length });
    }, [dispatch]),
  );

  useEffect(() => {
    const fc = getCanvas();
    if (!fc) return;
    const handler = () => saveSnapshot("modify");
    fc.on("object:modified", handler);
    return () => { fc.off("object:modified", handler); };
  }, [getCanvas, saveSnapshot]);

  // Auto-save
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
      } catch { /* non-fatal */ }
    }, [getThumbnail]),
    onSaved: () => dispatch({ type: "MARK_SAVED" }),
    enabled: true,
  });

  // Tool change handler (unchanged from original)
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
    await loadJSONToCanvas(fc, tpl.json);
    saveSnapshot("apply template");
  }, [getCanvas, saveSnapshot]);

  const handleApplyGeneratedDesign = useCallback(async (canvasJson: object, width: number, height: number) => {
    const fc = getCanvas();
    if (!fc) return;
    fc.set({ width, height });
    await loadJSONToCanvas(fc, canvasJson);
    saveSnapshot("ai generate design");
  }, [getCanvas, saveSnapshot]);

  const handleBringForward = useCallback(() => { bringForward(); saveSnapshot("bring forward"); }, [bringForward, saveSnapshot]);
  const handleSendBackward = useCallback(() => { sendBackward(); saveSnapshot("send backward"); }, [sendBackward, saveSnapshot]);

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

  const handleInsertImage = useCallback((src: string) => {
    void addImage(src).then(() => saveSnapshot("insert image"));
  }, [addImage, saveSnapshot]);

  const handleLayerSelect = useCallback((id: string) => {
    const fc = getCanvas();
    if (!fc) return;
    const obj = findById(fc, id);
    if (obj) { fc.setActiveObject(obj); fc.renderAll(); }
  }, [getCanvas]);

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
      } catch { /* non-fatal */ }
    }
    dispatch({ type: "MARK_SAVED" });
  }, [dispatch, getThumbnail, state.project]);

  // AI app ready: store the canvas_id so we can open it
  const handleAppReady = useCallback((_appId: string, canvasId: string | null) => {
    // Phase 1: just close the modal and note the canvas_id.
    // Phase 2 will load the generated canvas JSON onto the Fabric canvas.
    if (canvasId) {
      toast(`App canvas ready (id: ${canvasId})`, "ok");
    }
    setShowAICommandBar(false);
  }, [toast]);

  // ── Persistent AI command bar handler ────────────────────────────────────
  // Executes a free-text design command and applies the result to the canvas.
  const handleAICommand = useCallback(async (
    prompt: string,
    selectedIds: string[],
  ): Promise<AICommandResult> => {
    const contextHint = selectedIds.length > 0
      ? `Selected elements: ${selectedIds.join(", ")}. `
      : "";
    const fullPrompt = contextHint + prompt;

    const result = await _aiEngine.generateDesign({ prompt: fullPrompt });

    // Apply canvas JSON if the AI returned one
    if (result?.canvas_json) {
      const fc = getCanvas();
      if (fc) {
        const currentPage = state.project.pages.find(
          p => p.id === state.project.currentPageId
        );
        if (currentPage) {
          fc.set({ width: currentPage.width, height: currentPage.height });
        }
        await loadJSONToCanvas(fc, result.canvas_json);
        saveSnapshot("ai command");
      }
    }

    return {
      message: t("aiCommandBar.done", { defaultValue: "✓ Done — design updated." }),
    };
  }, [getCanvas, saveSnapshot, state.project, t]);

  const currentPage = state.project.pages.find(p => p.id === state.project.currentPageId);

  // Side-panel list for Insert mode (original set, unchanged)
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

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className={styles.studio}>
      {/* ── Top bar (now with mode tabs + Build with AI) ─────────────────── */}
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
        mode={studioMode}
        onModeChange={setStudioMode}
        onBuildWithAI={() => setShowAICommandBar(true)}
      />

      <div className={styles.body}>
        {/* ── Left column: drawing tools + unified sidebar ─────────────────── */}
        <LeftToolbar activeTool={state.tool} onToolChange={handleToolChange} />
        <div className={styles.leftPanel}>

          {/* Workspace section: APP / DATA / AI / AUTOMATION / DEPLOY tree */}
          <div className={styles.workspaceSection}>
            <AppTreePanel
              activeSection={activeSection}
              onSectionChange={setActiveSection}
            />
          </div>

          {/* Design section: panel nav + panel content */}
          <div className={styles.designSection}>
            <div className={styles.sectionLabel} aria-hidden="true">
              {t("shell.designSectionLabel")}
            </div>

            {/* Vertical panel nav — each item is always visible, no mode toggle */}
            <div
              className={styles.designNav}
              role="tablist"
              aria-label={t("shell.panelTabsAriaLabel")}
            >
              {SIDE_PANELS.map(p => (
                <button
                  key={p.id}
                  role="tab"
                  aria-selected={state.activePanel === p.id}
                  className={`${styles.designNavItem} ${state.activePanel === p.id ? styles.active : ""}`}
                  onClick={() => setPanel(p.id)}
                  title={p.label}
                  aria-label={p.label}
                >
                  {/* Icon slot — Phase 3 will place SVG here */}
                  <span className={styles.navIcon} aria-hidden="true" />
                  <span className={styles.navLabel}>{p.label}</span>
                </button>
              ))}
            </div>

            {/* Active panel content */}
            <div className={styles.panelContent} role="tabpanel">
              {state.activePanel === "layers"     && (
                <LayersPanel state={state} getCanvas={getCanvas} onSelect={handleLayerSelect} />
              )}
              {state.activePanel === "assets"     && <AssetsPanel onInsert={handleInsertImage} />}
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
        </div>

        {/* ── Canvas area (unchanged) ──────────────────────────────────────── */}
        <div className={styles.canvasArea}>
          <CanvasView fabricCanvas={fabricCanvas} state={state} />
        </div>

        {/* ── Right properties panel (unchanged) ──────────────────────────── */}
        <div className={styles.rightPanel}>
          <div
            className={styles.rightPanelHeader}
            role="heading"
            aria-level={2}
          >
            {t("shell.propertiesHeading")}
          </div>
          <PropertiesPanel
            getCanvas={getCanvas}
            selectedIds={state.selectedIds}
            onBringForward={handleBringForward}
            onSendBackward={handleSendBackward}
          />
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

      {/* ── Persistent AI command bar ────────────────────────────────────── */}
      <AICommandBarInline
        selectedIds={state.selectedIds}
        onCommand={handleAICommand}
        className={styles.commandBar}
      />

      {/* ── Page strip (unchanged) ───────────────────────────────────────── */}
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
          onClick={() => dispatch({
            type: "ADD_PAGE",
            page: {
              id: `p_${Date.now()}`,
              name: t("shell.defaultPageName", { num: state.project.pages.length + 1 }),
              width: 1280, height: 720,
              backgroundColor: "#ffffff",
              json: { version: "6.6.0", objects: [] },
              thumbnail: "",
            },
          })}
          title={t("shell.addPage")}
          aria-label={t("shell.addNewPageAriaLabel")}
        >
          +
        </button>
      </div>

      {/* ── Modals ───────────────────────────────────────────────────────── */}
      {showExport && (
        <ExportModal getCanvas={getCanvas} onClose={() => setShowExport(false)} />
      )}

      {showAICommandBar && (
        <AICommandBar
          onClose={() => setShowAICommandBar(false)}
          onAppReady={handleAppReady}
        />
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
