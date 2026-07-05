import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  type ReactNode,
} from "react";
import type {
  DesignState,
  DesignAction,
  DesignProject,
  CanvasPage,
  Guide,
  PanelId,
  Tool,
  Viewport,
} from "../types/canvas.types";
import { uid } from "../utils/geometryUtils";

// ── Default values ─────────────────────────────────────────────────────────────

function makeBlankPage(overrides?: Partial<CanvasPage>): CanvasPage {
  return {
    id:              uid(),
    name:            "Page 1",
    width:           1280,
    height:          720,
    backgroundColor: "#ffffff",
    json:            { version: "6.6.0", objects: [] },
    thumbnail:       "",
    ...overrides,
  };
}

function makeDefaultProject(): DesignProject {
  const page = makeBlankPage();
  return {
    id:            uid(),
    name:          "Untitled Design",
    description:   "",
    pages:         [page],
    currentPageId: page.id,
    createdAt:     new Date().toISOString(),
    updatedAt:     new Date().toISOString(),
    version:       "1",
  };
}

const DEFAULT_STATE: DesignState = {
  project:       makeDefaultProject(),
  tool:          "select",
  viewport:      { zoom: 1, panX: 0, panY: 0 },
  selectedIds:   [],
  activePanel:   "layers",
  guides:        [],
  showGrid:      false,
  showGuides:    true,
  snapEnabled:   true,
  rulerVisible:  true,
  historyIndex:  0,
  historyLength: 1,
  brandKit:      { colors: [], fonts: [], logos: [] },
  assets:        [],
  unsaved:       false,
};

// ── Reducer ────────────────────────────────────────────────────────────────────

function reducer(state: DesignState, action: DesignAction): DesignState {
  switch (action.type) {
    case "SET_TOOL":
      return { ...state, tool: action.tool };

    case "SET_VIEWPORT":
      return { ...state, viewport: { ...state.viewport, ...action.viewport } };

    case "SET_SELECTED_IDS":
      return { ...state, selectedIds: action.ids };

    case "SET_PANEL":
      return { ...state, activePanel: action.panel };

    case "SET_PROJECT":
      return { ...state, project: action.project, unsaved: false };

    case "UPDATE_PAGE_JSON": {
      const pages = state.project.pages.map(p =>
        p.id === action.pageId ? { ...p, json: action.json } : p
      );
      return {
        ...state,
        unsaved: true,
        project: { ...state.project, pages, updatedAt: new Date().toISOString() },
      };
    }

    case "UPDATE_PAGE_THUMB": {
      const pages = state.project.pages.map(p =>
        p.id === action.pageId ? { ...p, thumbnail: action.thumbnail } : p
      );
      return { ...state, project: { ...state.project, pages } };
    }

    case "ADD_PAGE": {
      const pages = [...state.project.pages, action.page];
      return {
        ...state,
        unsaved: true,
        project: { ...state.project, pages, currentPageId: action.page.id },
      };
    }

    case "REMOVE_PAGE": {
      if (state.project.pages.length <= 1) return state;
      const pages = state.project.pages.filter(p => p.id !== action.pageId);
      const currentPageId =
        state.project.currentPageId === action.pageId
          ? pages[0].id
          : state.project.currentPageId;
      return {
        ...state,
        unsaved: true,
        project: { ...state.project, pages, currentPageId },
      };
    }

    case "SET_PAGE":
      return {
        ...state,
        selectedIds:   [],
        project: { ...state.project, currentPageId: action.pageId },
      };

    case "RENAME_PAGE": {
      const pages = state.project.pages.map(p =>
        p.id === action.pageId ? { ...p, name: action.name } : p
      );
      return {
        ...state,
        unsaved: true,
        project: { ...state.project, pages },
      };
    }

    case "SET_HISTORY":
      return { ...state, historyIndex: action.index, historyLength: action.length };

    case "ADD_GUIDE":
      return { ...state, guides: [...state.guides, action.guide] };

    case "REMOVE_GUIDE":
      return { ...state, guides: state.guides.filter(g => g.id !== action.guideId) };

    case "TOGGLE_GRID":   return { ...state, showGrid:    !state.showGrid    };
    case "TOGGLE_GUIDES": return { ...state, showGuides:  !state.showGuides  };
    case "TOGGLE_SNAP":   return { ...state, snapEnabled: !state.snapEnabled  };
    case "TOGGLE_RULER":  return { ...state, rulerVisible:!state.rulerVisible };

    case "SET_BRAND_KIT":
      return { ...state, brandKit: action.brandKit };

    case "SET_ASSETS":
      return { ...state, assets: action.assets };

    case "ADD_ASSET":
      return { ...state, assets: [action.asset, ...state.assets] };

    case "REMOVE_ASSET":
      return { ...state, assets: state.assets.filter(a => a.id !== action.assetId) };

    case "TOGGLE_ASSET_FAV":
      return {
        ...state,
        assets: state.assets.map(a =>
          a.id === action.assetId ? { ...a, isFavorite: !a.isFavorite } : a
        ),
      };

    case "REORDER_PAGE": {
      const pages = [...state.project.pages];
      const [moved] = pages.splice(action.fromIndex, 1);
      pages.splice(action.toIndex, 0, moved);
      return { ...state, unsaved: true, project: { ...state.project, pages } };
    }

    case "DUPLICATE_PAGE": {
      const src = state.project.pages.find(p => p.id === action.pageId);
      if (!src) return state;
      const copy: CanvasPage = { ...src, id: uid(), name: `${src.name} Copy`, thumbnail: "" };
      const idx = state.project.pages.findIndex(p => p.id === action.pageId);
      const pages = [...state.project.pages];
      pages.splice(idx + 1, 0, copy);
      return { ...state, unsaved: true, project: { ...state.project, pages, currentPageId: copy.id } };
    }

    case "MARK_SAVED":   return { ...state, unsaved: false };
    case "MARK_UNSAVED": return { ...state, unsaved: true  };

    default:
      return state;
  }
}

// ── Context ────────────────────────────────────────────────────────────────────

interface DesignContextType {
  state:    DesignState;
  dispatch: React.Dispatch<DesignAction>;
  // Convenience actions
  setTool:        (tool: Tool) => void;
  setViewport:    (vp: Partial<Viewport>) => void;
  setSelectedIds: (ids: string[]) => void;
  setPanel:       (panel: PanelId) => void;
  addPage:        () => void;
  removePage:     (pageId: string) => void;
  duplicatePage:  (pageId: string) => void;
  reorderPage:    (fromIndex: number, toIndex: number) => void;
  renamePage:     (pageId: string, name: string) => void;
  setPage:        (pageId: string) => void;
  addGuide:       (guide: Omit<Guide, "id">) => void;
  removeGuide:    (id: string) => void;
}

const DesignContext = createContext<DesignContextType | null>(null);

export function DesignProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, DEFAULT_STATE);

  const setTool        = useCallback((tool: Tool)           => dispatch({ type: "SET_TOOL",         tool            }), []);
  const setViewport    = useCallback((viewport: Partial<Viewport>) => dispatch({ type: "SET_VIEWPORT",   viewport        }), []);
  const setSelectedIds = useCallback((ids: string[])        => dispatch({ type: "SET_SELECTED_IDS", ids             }), []);
  const setPanel       = useCallback((panel: PanelId)       => dispatch({ type: "SET_PANEL",        panel           }), []);

  const addPage = useCallback(() => {
    const n = state.project.pages.length + 1;
    dispatch({ type: "ADD_PAGE", page: makeBlankPage({ name: `Page ${n}` }) });
  }, [state.project.pages.length]);

  const removePage    = useCallback((pageId: string) => dispatch({ type: "REMOVE_PAGE",    pageId }), []);
  const duplicatePage = useCallback((pageId: string) => dispatch({ type: "DUPLICATE_PAGE", pageId }), []);
  const reorderPage   = useCallback((fromIndex: number, toIndex: number) => dispatch({ type: "REORDER_PAGE", fromIndex, toIndex }), []);
  const renamePage    = useCallback((pageId: string, name: string) => dispatch({ type: "RENAME_PAGE", pageId, name }), []);
  const setPage       = useCallback((pageId: string) => dispatch({ type: "SET_PAGE", pageId }), []);

  const addGuide = useCallback((g: Omit<Guide, "id">) => {
    dispatch({ type: "ADD_GUIDE", guide: { ...g, id: uid() } });
  }, []);

  const removeGuide = useCallback((guideId: string) => {
    dispatch({ type: "REMOVE_GUIDE", guideId });
  }, []);

  return (
    <DesignContext.Provider value={{
      state, dispatch,
      setTool, setViewport, setSelectedIds, setPanel,
      addPage, removePage, duplicatePage, reorderPage, renamePage, setPage,
      addGuide, removeGuide,
    }}>
      {children}
    </DesignContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useDesign(): DesignContextType {
  const ctx = useContext(DesignContext);
  if (!ctx) throw new Error("useDesign must be used within DesignProvider");
  return ctx;
}

// eslint-disable-next-line react-refresh/only-export-components
export { makeBlankPage, makeDefaultProject };
