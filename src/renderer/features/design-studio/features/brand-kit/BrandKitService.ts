/**
 * BrandKitService — CRUD for FullBrandKit with IndexedDB persistence.
 * Multiple brand kits can exist; one is "active" per project.
 */
import type { FullBrandKit } from "./BrandKit";
import { makeDefaultBrandKit } from "./BrandKit";
import { uid } from "../../utils/geometryUtils";
import { designBus } from "../../core/events/DesignEventBus";

const DB_NAME     = "axon_brand_kits";
const STORE_NAME  = "kits";
const DB_VERSION  = 1;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror   = () => reject(req.error);
  });
}

async function idbGet<T>(db: IDBDatabase, key: string): Promise<T | undefined> {
  return new Promise((resolve, reject) => {
    const tx  = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).get(key);
    req.onsuccess = () => resolve(req.result as T | undefined);
    req.onerror   = () => reject(req.error);
  });
}

async function idbPut(db: IDBDatabase, value: unknown): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx  = db.transaction(STORE_NAME, "readwrite");
    const req = tx.objectStore(STORE_NAME).put(value);
    req.onsuccess = () => resolve();
    req.onerror   = () => reject(req.error);
  });
}

async function idbDelete(db: IDBDatabase, key: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx  = db.transaction(STORE_NAME, "readwrite");
    const req = tx.objectStore(STORE_NAME).delete(key);
    req.onsuccess = () => resolve();
    req.onerror   = () => reject(req.error);
  });
}

async function idbGetAll<T>(db: IDBDatabase): Promise<T[]> {
  return new Promise((resolve, reject) => {
    const tx  = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).getAll();
    req.onsuccess = () => resolve(req.result as T[]);
    req.onerror   = () => reject(req.error);
  });
}

// ── Service ───────────────────────────────────────────────────────────────────

export class BrandKitService {
  private _db: IDBDatabase | null = null;
  private _active: FullBrandKit | null = null;

  async init(): Promise<void> {
    this._db = await openDB();
    // Ensure at least one kit exists
    const all = await this.list();
    if (all.length === 0) {
      const kit = makeDefaultBrandKit();
      await this.save(kit);
      this._active = kit;
    } else {
      this._active = all[0];
    }
  }

  get active(): FullBrandKit {
    return this._active ?? makeDefaultBrandKit();
  }

  async setActive(kitId: string): Promise<void> {
    const kit = await this.get(kitId);
    if (!kit) throw new Error(`Brand kit "${kitId}" not found`);
    this._active = kit;
    designBus.emit("BrandKitChanged", { kitId });
  }

  async list(): Promise<FullBrandKit[]> {
    if (!this._db) return [];
    return idbGetAll<FullBrandKit>(this._db);
  }

  async get(id: string): Promise<FullBrandKit | undefined> {
    if (!this._db) return undefined;
    return idbGet<FullBrandKit>(this._db, id);
  }

  async save(kit: FullBrandKit): Promise<void> {
    if (!this._db) return;
    kit.updatedAt = new Date().toISOString();
    await idbPut(this._db, kit);
    if (this._active?.id === kit.id) this._active = kit;
  }

  async create(name: string): Promise<FullBrandKit> {
    const kit = { ...makeDefaultBrandKit(), id: uid(), name };
    await this.save(kit);
    return kit;
  }

  async delete(kitId: string): Promise<void> {
    if (!this._db) return;
    await idbDelete(this._db, kitId);
    if (this._active?.id === kitId) this._active = null;
  }

  async duplicate(kitId: string): Promise<FullBrandKit> {
    const src = await this.get(kitId);
    if (!src) throw new Error(`Brand kit "${kitId}" not found`);
    const copy = { ...src, id: uid(), name: `${src.name} (Copy)`, createdAt: new Date().toISOString() };
    await this.save(copy);
    return copy;
  }
}

export const brandKitService = new BrandKitService();
