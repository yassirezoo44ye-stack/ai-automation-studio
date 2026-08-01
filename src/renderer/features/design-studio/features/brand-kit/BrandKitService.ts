/**
 * BrandKitService — CRUD for FullBrandKit, backed by BrandKitRepository.
 * Multiple brand kits can exist; one is "active" per project.
 */
import type { FullBrandKit, BrandColor, BrandFont, BrandLogo } from "./BrandKit";
import { makeDefaultBrandKit } from "./BrandKit";
import { uid } from "../../utils/geometryUtils";
import { designBus } from "../../core/events/DesignEventBus";
import { brandKitRepository } from "./BrandKitRepository";

// ── Service ───────────────────────────────────────────────────────────────────

export class BrandKitService {
  private _active: FullBrandKit | null = null;
  private _initPromise?: Promise<FullBrandKit>;
  private _writeQueue: Promise<unknown> = Promise.resolve();

  /**
   * Memoized: concurrent callers (e.g. React 18 Strict Mode double-invoking
   * an effect) all get the same in-flight promise instead of racing to
   * create two default kits. Resolves to the active kit either way.
   */
  init(): Promise<FullBrandKit> {
    if (!this._initPromise) this._initPromise = this._doInit();
    return this._initPromise;
  }

  private async _doInit(): Promise<FullBrandKit> {
    await brandKitRepository.open();
    // Ensure at least one kit exists
    const all = await this.list();
    if (all.length === 0) {
      const kit = makeDefaultBrandKit();
      // Set _active before save() so BrandKitChanged listeners that read
      // `.active` during the save see the real kit, not the empty-state
      // fallback in the `active` getter below.
      this._active = kit;
      await this.save(kit);
    } else {
      this._active = all[0];
    }
    return this._active;
  }

  get active(): FullBrandKit {
    return this._active ?? makeDefaultBrandKit();
  }

  async setActive(kitId: string): Promise<void> {
    const kit = await this.get(kitId);
    if (!kit) throw new Error(`Brand kit "${kitId}" not found`);
    this._active = kit;
    designBus.emit("BrandKitChanged", { kitId, kit });
  }

  async list(): Promise<FullBrandKit[]> {
    return brandKitRepository.getAll();
  }

  async get(id: string): Promise<FullBrandKit | undefined> {
    return brandKitRepository.get(id);
  }

  async save(kit: FullBrandKit): Promise<void> {
    if (!brandKitRepository.isOpen) return;
    kit.updatedAt = new Date().toISOString();
    await brandKitRepository.put(kit);
    if (this._active?.id === kit.id) this._active = kit;
    designBus.emit("BrandKitChanged", { kitId: kit.id, kit });
  }

  async create(name: string): Promise<FullBrandKit> {
    const kit = { ...makeDefaultBrandKit(), id: uid(), name };
    await this.save(kit);
    return kit;
  }

  async delete(kitId: string): Promise<void> {
    if (!brandKitRepository.isOpen) return;
    await brandKitRepository.delete(kitId);
    if (this._active?.id === kitId) this._active = null;
  }

  async duplicate(kitId: string): Promise<FullBrandKit> {
    const src = await this.get(kitId);
    if (!src) throw new Error(`Brand kit "${kitId}" not found`);
    const copy = { ...src, id: uid(), name: `${src.name} (Copy)`, createdAt: new Date().toISOString() };
    await this.save(copy);
    return copy;
  }

  // ── Write queue ──────────────────────────────────────────────────────────
  // Serializes mutations so concurrent calls (e.g. rapid double-click) always
  // read-modify-write in call order, each starting from the previous one's
  // result — without this, two mutations reading `this.active` before either
  // resolves would race, and the second save() would silently overwrite the
  // first's change. The queue link itself always resolves (never rejects)
  // regardless of whether `mutation` succeeds — otherwise one failed
  // mutation would permanently poison every mutation queued after it. The
  // caller still sees the real success/failure via the returned promise.
  private enqueue<T>(mutation: () => Promise<T>): Promise<T> {
    const result = this._writeQueue.then(mutation);
    this._writeQueue = result.then(() => undefined, () => undefined);
    return result;
  }

  // ── Granular mutations ───────────────────────────────────────────────────
  // Each: init() first (guarantees the repository is open before the
  // read-modify-write cycle), read the current active kit, compute the next
  // kit, persist via save() (repository write + BrandKitChanged emit),
  // return the persisted kit.

  addColor(color: Omit<BrandColor, "id">): Promise<FullBrandKit> {
    return this.enqueue(async () => {
      await this.init();
      const kit = this.active;
      const updated: FullBrandKit = { ...kit, colors: [...kit.colors, { ...color, id: uid() }] };
      await this.save(updated);
      return updated;
    });
  }

  removeColor(id: string): Promise<FullBrandKit> {
    return this.enqueue(async () => {
      await this.init();
      const kit = this.active;
      const updated: FullBrandKit = { ...kit, colors: kit.colors.filter(c => c.id !== id) };
      await this.save(updated);
      return updated;
    });
  }

  addFont(font: Omit<BrandFont, "id">): Promise<FullBrandKit> {
    return this.enqueue(async () => {
      await this.init();
      const kit = this.active;
      const updated: FullBrandKit = { ...kit, fonts: [...kit.fonts, { ...font, id: uid() }] };
      await this.save(updated);
      return updated;
    });
  }

  removeFont(id: string): Promise<FullBrandKit> {
    return this.enqueue(async () => {
      await this.init();
      const kit = this.active;
      const updated: FullBrandKit = { ...kit, fonts: kit.fonts.filter(f => f.id !== id) };
      await this.save(updated);
      return updated;
    });
  }

  addLogo(logo: Omit<BrandLogo, "id" | "variant"> & { variant?: BrandLogo["variant"] }): Promise<FullBrandKit> {
    return this.enqueue(async () => {
      await this.init();
      const kit = this.active;
      const updated: FullBrandKit = {
        ...kit,
        logos: [...kit.logos, { ...logo, id: uid(), variant: logo.variant ?? "primary" }],
      };
      await this.save(updated);
      return updated;
    });
  }

  removeLogo(id: string): Promise<FullBrandKit> {
    return this.enqueue(async () => {
      await this.init();
      const kit = this.active;
      const updated: FullBrandKit = { ...kit, logos: kit.logos.filter(l => l.id !== id) };
      await this.save(updated);
      return updated;
    });
  }
}

export const brandKitService = new BrandKitService();
