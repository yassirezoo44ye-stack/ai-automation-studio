/**
 * Design Event Bus — typed publish/subscribe.
 * All cross-module communication uses this bus.
 * Handlers are isolated: a failing handler never blocks other handlers.
 */
import type { DesignEventMap, DesignEventName } from "./DesignEvents";

type Handler<E> = (payload: E) => void;

export class DesignEventBus {
  private readonly _handlers = new Map<string, Set<Handler<unknown>>>();

  on<K extends DesignEventName>(
    event: K,
    handler: Handler<DesignEventMap[K]>,
  ): () => void {
    if (!this._handlers.has(event)) {
      this._handlers.set(event, new Set());
    }
    this._handlers.get(event)!.add(handler as Handler<unknown>);

    // Return unsubscribe fn
    return () => this.off(event, handler);
  }

  off<K extends DesignEventName>(
    event: K,
    handler: Handler<DesignEventMap[K]>,
  ): void {
    this._handlers.get(event)?.delete(handler as Handler<unknown>);
  }

  emit<K extends DesignEventName>(event: K, payload: DesignEventMap[K]): void {
    const handlers = this._handlers.get(event);
    if (!handlers) return;

    handlers.forEach(h => {
      try {
        h(payload);
      } catch (err) {
        console.error(`[DesignBus] handler error for "${event}":`, err);
      }
    });
  }

  once<K extends DesignEventName>(
    event: K,
    handler: Handler<DesignEventMap[K]>,
  ): () => void {
    const wrapped: Handler<DesignEventMap[K]> = (payload) => {
      handler(payload);
      this.off(event, wrapped);
    };
    return this.on(event, wrapped);
  }

  handlerCount(event: DesignEventName): number {
    return this._handlers.get(event)?.size ?? 0;
  }

  clear(event?: DesignEventName): void {
    if (event) this._handlers.delete(event);
    else this._handlers.clear();
  }
}

/** Module-level singleton */
export const designBus = new DesignEventBus();
