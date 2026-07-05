/**
 * ObjectPool — recycles FabricObject instances to reduce GC pressure
 * on large documents with frequent add/remove operations.
 */
import type { FabricObject } from "fabric";

type Factory<T extends FabricObject> = () => T;
type Resetter<T extends FabricObject> = (obj: T) => void;

export class ObjectPool<T extends FabricObject> {
  private readonly _pool: T[]  = [];
  private readonly _factory:   Factory<T>;
  private readonly _resetter?: Resetter<T>;
  private readonly _maxSize:   number;
  private _created = 0;
  private _reused  = 0;

  constructor(factory: Factory<T>, opts: { resetter?: Resetter<T>; maxSize?: number } = {}) {
    this._factory  = factory;
    this._resetter = opts.resetter;
    this._maxSize  = opts.maxSize ?? 200;
  }

  acquire(): T {
    const obj = this._pool.pop();
    if (obj) {
      this._reused++;
      return obj;
    }
    this._created++;
    return this._factory();
  }

  release(obj: T): void {
    if (this._pool.length >= this._maxSize) return; // Pool full — let GC handle it
    this._resetter?.(obj);
    this._pool.push(obj);
  }

  stats(): { pooled: number; created: number; reused: number } {
    return { pooled: this._pool.length, created: this._created, reused: this._reused };
  }

  clear(): void {
    this._pool.length = 0;
  }
}
