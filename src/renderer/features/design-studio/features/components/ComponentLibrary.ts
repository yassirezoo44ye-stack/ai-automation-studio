/**
 * Component Library — reusable design components.
 * Editing a component definition syncs all linked instances.
 */
import { uid } from "../../utils/geometryUtils";
import { designBus } from "../../core/events/DesignEventBus";

// ── Component types ───────────────────────────────────────────────────────────

export type ComponentCategory =
  | "button"
  | "card"
  | "header"
  | "footer"
  | "social"
  | "chart"
  | "table"
  | "icon"
  | "form"
  | "navigation"
  | "hero"
  | "custom";

export interface ComponentDefinition {
  id:          string;
  name:        string;
  category:    ComponentCategory;
  description?: string;
  thumbnail?:  string;
  /** Fabric.js JSON for the component */
  json:        object;
  /** IDs of canvas objects that are linked instances of this component */
  instances:   string[];
  /** Design tokens this component uses */
  tokenRefs?:  Record<string, string>;  // propName → tokenId
  createdAt:   string;
  updatedAt:   string;
}

export interface ComponentInstance {
  componentId: string;
  instanceId:  string;   // Fabric object ID on canvas
  overrides?:  Record<string, unknown>;  // Local overrides over definition
}

// ── Library class ─────────────────────────────────────────────────────────────

export class ComponentLibrary {
  private readonly _components = new Map<string, ComponentDefinition>();

  add(def: ComponentDefinition): void {
    this._components.set(def.id, def);
    designBus.emit("ComponentCreated", { componentId: def.id, name: def.name });
  }

  update(id: string, patch: Partial<ComponentDefinition>): boolean {
    const existing = this._components.get(id);
    if (!existing) return false;

    const updated = {
      ...existing,
      ...patch,
      id,
      updatedAt: new Date().toISOString(),
    };
    this._components.set(id, updated);
    designBus.emit("ComponentUpdated", { componentId: id });

    // Notify that instances need to be synced
    if (updated.instances.length > 0) {
      designBus.emit("ComponentInstanceSynced", {
        componentId: id,
        instanceIds: updated.instances,
      });
    }

    return true;
  }

  delete(id: string): boolean {
    return this._components.delete(id);
  }

  get(id: string): ComponentDefinition | undefined {
    return this._components.get(id);
  }

  all(): ComponentDefinition[] {
    return [...this._components.values()];
  }

  byCategory(category: ComponentCategory): ComponentDefinition[] {
    return this.all().filter(c => c.category === category);
  }

  /** Register a canvas object as an instance of a component */
  linkInstance(componentId: string, objectId: string): boolean {
    const def = this._components.get(componentId);
    if (!def) return false;
    if (!def.instances.includes(objectId)) {
      def.instances.push(objectId);
      def.updatedAt = new Date().toISOString();
    }
    return true;
  }

  /** Unlink a canvas object from its component */
  unlinkInstance(objectId: string): void {
    for (const def of this._components.values()) {
      const idx = def.instances.indexOf(objectId);
      if (idx !== -1) {
        def.instances.splice(idx, 1);
        def.updatedAt = new Date().toISOString();
      }
    }
  }

  /** Find which component this object is an instance of */
  findByInstance(objectId: string): ComponentDefinition | undefined {
    return this.all().find(c => c.instances.includes(objectId));
  }

  /** Export all definitions as JSON */
  exportAll(): ComponentDefinition[] {
    return this.all();
  }

  /** Import definitions (merge) */
  importAll(defs: ComponentDefinition[]): void {
    defs.forEach(d => this._components.set(d.id, d));
  }
}

// ── Factory helpers ───────────────────────────────────────────────────────────

export function createComponent(
  name: string,
  category: ComponentCategory,
  json: object,
): ComponentDefinition {
  const now = new Date().toISOString();
  return { id: uid(), name, category, json, instances: [], createdAt: now, updatedAt: now };
}

/** Module-level singleton */
export const componentLibrary = new ComponentLibrary();
