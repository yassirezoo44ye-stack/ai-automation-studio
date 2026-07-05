/**
 * PluginRegistry — manages plugin lifecycle and aggregates all contributed items.
 */
import type { Plugin, PluginContext, ToolbarItem, PanelItem, InspectorItem, ExportHook, ImportHook, CommandHook } from "./PluginAPI";
import { designBus } from "../events/DesignEventBus";
import type { DesignEventName, DesignEventMap } from "../events/DesignEvents";
import { tokenRegistry } from "../tokens/TokenRegistry";
import type { DesignToken } from "../tokens/DesignToken";

export class PluginRegistry {
  private readonly _plugins  = new Map<string, Plugin>();
  private readonly _cleanup  = new Map<string, Array<() => void>>();

  // Contributed items
  private _toolbarItems: ToolbarItem[]  = [];
  private _panels:       PanelItem[]    = [];
  private _inspectors:   InspectorItem[] = [];
  private _exporters:    ExportHook[]   = [];
  private _importers:    ImportHook[]   = [];
  private _cmdHooks:     CommandHook[]  = [];

  register(plugin: Plugin): void {
    if (this._plugins.has(plugin.id)) {
      console.warn(`[PluginRegistry] Plugin "${plugin.id}" already registered`);
      return;
    }

    const unsubscribes: Array<() => void> = [];

    const context: PluginContext = {
      on: <K extends DesignEventName>(event: K, handler: (payload: DesignEventMap[K]) => void) => {
        const unsub = designBus.on(event, handler);
        unsubscribes.push(unsub);
        return unsub;
      },
      addToolbarItem: (item) => { this._toolbarItems.push(item); },
      addPanel:       (item) => { this._panels.push(item); },
      addInspector:   (item) => { this._inspectors.push(item); },
      addExporter:    (hook) => { this._exporters.push(hook); },
      addImporter:    (hook) => { this._importers.push(hook); },
      addCommandHook: (hook) => { this._cmdHooks.push(hook); },
      tokens: {
        get:    (id) => tokenRegistry.get(id),
        add:    (t: DesignToken) => tokenRegistry.add(t),
        update: (id, patch) => tokenRegistry.update(id, patch as Partial<DesignToken>),
      },
    };

    plugin.register(context);
    this._plugins.set(plugin.id, plugin);
    this._cleanup.set(plugin.id, unsubscribes);

    designBus.emit("PluginRegistered", { pluginId: plugin.id, name: plugin.name });
    console.info(`[PluginRegistry] Registered plugin "${plugin.name}" v${plugin.version}`);
  }

  unregister(pluginId: string): void {
    const plugin = this._plugins.get(pluginId);
    if (!plugin) return;

    plugin.unregister?.();

    // Clean up event subscriptions
    const subs = this._cleanup.get(pluginId) ?? [];
    subs.forEach(fn => fn());

    // Remove contributed items
    this._toolbarItems = this._toolbarItems.filter(i => !i.id.startsWith(pluginId));
    this._panels       = this._panels.filter(i => !i.id.startsWith(pluginId));
    this._inspectors   = this._inspectors.filter(i => !i.id.startsWith(pluginId));
    this._exporters    = this._exporters.filter(i => !i.format.startsWith(pluginId));
    this._importers    = this._importers.filter(() => true); // importers don't have ids

    this._plugins.delete(pluginId);
    this._cleanup.delete(pluginId);

    designBus.emit("PluginUnregistered", { pluginId });
  }

  // ── Accessors ─────────────────────────────────────────────────────────────

  getPlugin(id: string): Plugin | undefined { return this._plugins.get(id); }
  all(): Plugin[] { return [...this._plugins.values()]; }
  toolbarItems(): ToolbarItem[] { return [...this._toolbarItems]; }
  panels(): PanelItem[] { return [...this._panels]; }
  inspectors(): InspectorItem[] { return [...this._inspectors]; }
  exporters(): ExportHook[] { return [...this._exporters]; }
  importers(): ImportHook[] { return [...this._importers]; }
  commandHooks(): CommandHook[] { return [...this._cmdHooks]; }
}

/** Module-level singleton */
export const pluginRegistry = new PluginRegistry();
