/**
 * TokenRegistry — CRUD store for design tokens with change notifications.
 */
import type { DesignToken, TokenCategory } from "./DesignToken";
import { designBus } from "../events/DesignEventBus";

export class TokenRegistry {
  private readonly _tokens = new Map<string, DesignToken>();

  add(token: DesignToken): void {
    this._tokens.set(token.id, token);
    designBus.emit("TokenCreated", {
      tokenId: token.id,
      name: token.name,
      category: token.category,
    });
  }

  update(id: string, patch: Partial<DesignToken>): boolean {
    const existing = this._tokens.get(id);
    if (!existing) return false;

    const oldValue = existing.value;
    const updated  = { ...existing, ...patch, updatedAt: new Date().toISOString() } as DesignToken;
    this._tokens.set(id, updated);

    designBus.emit("TokenUpdated", { tokenId: id, oldValue, newValue: updated.value });
    return true;
  }

  delete(id: string): boolean {
    if (!this._tokens.has(id)) return false;
    this._tokens.delete(id);
    designBus.emit("TokenDeleted", { tokenId: id });
    return true;
  }

  get(id: string): DesignToken | undefined {
    return this._tokens.get(id);
  }

  all(): DesignToken[] {
    return [...this._tokens.values()];
  }

  byCategory(category: TokenCategory): DesignToken[] {
    return this.all().filter(t => t.category === category);
  }

  colors()      { return this.byCategory("color"); }
  gradients()   { return this.byCategory("gradient"); }
  typography()  { return this.byCategory("typography"); }
  spacing()     { return this.byCategory("spacing"); }
  radii()       { return this.byCategory("radius"); }
  shadows()     { return this.byCategory("shadow"); }
  effects()     { return this.byCategory("effect"); }
  borders()     { return this.byCategory("border"); }

  /** Export as CSS custom properties */
  toCSSVariables(): string {
    return [
      ":root {",
      ...this.all().map(t => `  --token-${t.name.toLowerCase().replace(/\s+/g, "-")}: ${t.value};`),
      "}",
    ].join("\n");
  }

  /** Bulk import (e.g., from JSON file or Brand Kit) */
  importTokens(tokens: DesignToken[]): void {
    tokens.forEach(t => this._tokens.set(t.id, t));
  }

  exportTokens(): DesignToken[] {
    return this.all();
  }

  clear(): void {
    this._tokens.clear();
  }
}

/** Module-level singleton */
export const tokenRegistry = new TokenRegistry();
