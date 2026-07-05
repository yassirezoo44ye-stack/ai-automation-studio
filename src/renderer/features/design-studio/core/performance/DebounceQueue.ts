/**
 * DebounceQueue — coalesces rapid canvas changes before persisting.
 * Prevents flooding the store with a JSON serialization on every mouse move.
 */
export class DebounceQueue {
  private readonly _timers = new Map<string, ReturnType<typeof setTimeout>>();

  schedule(key: string, fn: () => void, delay: number): void {
    const existing = this._timers.get(key);
    if (existing) clearTimeout(existing);
    this._timers.set(key, setTimeout(() => {
      this._timers.delete(key);
      fn();
    }, delay));
  }

  cancel(key: string): void {
    const existing = this._timers.get(key);
    if (existing) {
      clearTimeout(existing);
      this._timers.delete(key);
    }
  }

  cancelAll(): void {
    for (const timer of this._timers.values()) clearTimeout(timer);
    this._timers.clear();
  }

  flush(key: string): void {
    this.cancel(key);
  }
}

export const debounceQueue = new DebounceQueue();
