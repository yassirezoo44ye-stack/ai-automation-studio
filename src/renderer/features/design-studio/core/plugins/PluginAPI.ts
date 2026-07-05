/**
 * Plugin API — plugins register hooks without modifying the core editor.
 * All extension points flow through PluginHooks.
 */
import type { Canvas as FabricCanvas } from "fabric";
import type { DesignEventMap, DesignEventName } from "../events/DesignEvents";
import type { DesignToken } from "../tokens/DesignToken";

// ── Hook definitions ──────────────────────────────────────────────────────────

export interface ToolbarItem {
  id:      string;
  icon:    string;       // SVG string or emoji
  label:   string;
  tooltip?: string;
  group?:  "left" | "top" | "right" | "bottom";
  onClick: (canvas: FabricCanvas) => void;
}

export interface PanelItem {
  id:       string;
  label:    string;
  icon?:    string;
  position: "left" | "right";
  component: () => React.ReactNode;
}

export interface InspectorItem {
  id:        string;
  label:     string;
  /** Return true if this inspector should show for the current selection */
  matches:   (selectedTypes: string[]) => boolean;
  component: () => React.ReactNode;
}

export interface ExportHook {
  format:   string;
  label:    string;
  extension: string;
  export:   (canvas: FabricCanvas) => Blob | Promise<Blob>;
}

export interface ImportHook {
  accepts:  string[];   // MIME types
  label:    string;
  import:   (file: File, canvas: FabricCanvas) => void | Promise<void>;
}

export interface CommandHook {
  /** Intercept before command executes; return false to cancel */
  beforeExecute?: (description: string) => boolean;
  afterExecute?:  (description: string) => void;
}

// ── Plugin descriptor ─────────────────────────────────────────────────────────

export interface Plugin {
  id:          string;
  name:        string;
  version:     string;
  description?: string;
  author?:     string;

  /** Called once when plugin is registered */
  register(api: PluginContext): void;

  /** Called when plugin is removed */
  unregister?(): void;
}

// ── Context passed to each plugin ─────────────────────────────────────────────

export interface PluginContext {
  /** Subscribe to design events */
  on<K extends DesignEventName>(
    event: K,
    handler: (payload: DesignEventMap[K]) => void,
  ): () => void;

  /** Add toolbar button */
  addToolbarItem(item: ToolbarItem): void;

  /** Add side panel */
  addPanel(item: PanelItem): void;

  /** Add inspector section */
  addInspector(item: InspectorItem): void;

  /** Register export format */
  addExporter(hook: ExportHook): void;

  /** Register import handler */
  addImporter(hook: ImportHook): void;

  /** Register command interceptor */
  addCommandHook(hook: CommandHook): void;

  /** Access and modify design tokens */
  tokens: {
    get(id: string): DesignToken | undefined;
    add(token: DesignToken): void;
    update(id: string, patch: Partial<DesignToken>): void;
  };
}
