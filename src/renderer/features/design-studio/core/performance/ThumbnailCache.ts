/**
 * ThumbnailCache — page thumbnail generation with LRU eviction.
 * Prevents redundant Fabric toDataURL calls on every render.
 */
import type { Canvas as FabricCanvas } from "fabric";
import { generateThumbnail } from "../../utils/fabricUtils";

interface CacheEntry {
  dataUrl:   string;
  version:   number;
  createdAt: number;
}

export class ThumbnailCache {
  private readonly _cache  = new Map<string, CacheEntry>();
  private readonly _maxSize: number;
  private readonly _ttlMs:   number;

  constructor(maxSize = 50, ttlMs = 5 * 60_000) {
    this._maxSize = maxSize;
    this._ttlMs   = ttlMs;
  }

  get(pageId: string, version: number): string | null {
    const entry = this._cache.get(pageId);
    if (!entry) return null;
    if (entry.version !== version) return null;
    if (Date.now() - entry.createdAt > this._ttlMs) {
      this._cache.delete(pageId);
      return null;
    }
    return entry.dataUrl;
  }

  set(pageId: string, version: number, dataUrl: string): void {
    // Evict LRU if full
    if (this._cache.size >= this._maxSize) {
      const oldest = [...this._cache.entries()].sort(([, a], [, b]) => a.createdAt - b.createdAt)[0];
      if (oldest) this._cache.delete(oldest[0]);
    }
    this._cache.set(pageId, { dataUrl, version, createdAt: Date.now() });
  }

  /** Generate and cache a thumbnail, using the cache if version matches */
  generate(
    pageId:  string,
    version: number,
    canvas:  FabricCanvas,
    maxW = 320,
    maxH = 180,
  ): string {
    const cached = this.get(pageId, version);
    if (cached) return cached;

    const dataUrl = generateThumbnail(canvas, maxW, maxH);
    this.set(pageId, version, dataUrl);
    return dataUrl;
  }

  invalidate(pageId: string): void {
    this._cache.delete(pageId);
  }

  invalidateAll(): void {
    this._cache.clear();
  }

  stats(): { size: number; maxSize: number } {
    return { size: this._cache.size, maxSize: this._maxSize };
  }
}

export const thumbnailCache = new ThumbnailCache();
