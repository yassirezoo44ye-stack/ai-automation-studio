/**
 * BrandKitRepository — raw IndexedDB access for the "kits" object store.
 * No domain logic, no events, no notion of "active" kit — BrandKitService
 * owns all of that. This layer only knows how to open the DB and do
 * get/getAll/put/delete against the one object store.
 */
import type { FullBrandKit } from "./BrandKit";

const DB_NAME    = "axon_brand_kits";
const STORE_NAME = "kits";
const DB_VERSION = 1;

export class BrandKitRepository {
  private _db: IDBDatabase | null = null;

  get isOpen(): boolean {
    return this._db !== null;
  }

  async open(): Promise<void> {
    this._db = await new Promise<IDBDatabase>((resolve, reject) => {
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

  async getAll(): Promise<FullBrandKit[]> {
    if (!this._db) return [];
    const db = this._db;
    return new Promise((resolve, reject) => {
      const tx  = db.transaction(STORE_NAME, "readonly");
      const req = tx.objectStore(STORE_NAME).getAll();
      req.onsuccess = () => resolve(req.result as FullBrandKit[]);
      req.onerror   = () => reject(req.error);
    });
  }

  async get(id: string): Promise<FullBrandKit | undefined> {
    if (!this._db) return undefined;
    const db = this._db;
    return new Promise((resolve, reject) => {
      const tx  = db.transaction(STORE_NAME, "readonly");
      const req = tx.objectStore(STORE_NAME).get(id);
      req.onsuccess = () => resolve(req.result as FullBrandKit | undefined);
      req.onerror   = () => reject(req.error);
    });
  }

  async put(kit: FullBrandKit): Promise<void> {
    if (!this._db) return;
    const db = this._db;
    return new Promise((resolve, reject) => {
      const tx  = db.transaction(STORE_NAME, "readwrite");
      const req = tx.objectStore(STORE_NAME).put(kit);
      req.onsuccess = () => resolve();
      req.onerror   = () => reject(req.error);
    });
  }

  async delete(id: string): Promise<void> {
    if (!this._db) return;
    const db = this._db;
    return new Promise((resolve, reject) => {
      const tx  = db.transaction(STORE_NAME, "readwrite");
      const req = tx.objectStore(STORE_NAME).delete(id);
      req.onsuccess = () => resolve();
      req.onerror   = () => reject(req.error);
    });
  }
}

export const brandKitRepository = new BrandKitRepository();
