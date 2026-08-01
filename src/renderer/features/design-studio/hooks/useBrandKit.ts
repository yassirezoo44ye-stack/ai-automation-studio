import { useEffect } from "react";
import type { FullBrandKit } from "../features/brand-kit/BrandKit";
import { brandKitService } from "../features/brand-kit/BrandKitService";
import { designBus } from "../core/events/DesignEventBus";
import { useDesign } from "../stores/designStore";

/**
 * Brand Kit lifecycle owner — mounted once at DesignStudio. Initializes
 * BrandKitService (loads or creates the active kit from IndexedDB) and keeps
 * designStore's `brandKit` (Presentation State) in sync via BrandKitChanged.
 *
 * Phase A only: read/sync path. BrandKitPanel's writes aren't routed through
 * BrandKitService yet — that lands in Phase B alongside the Actions layer.
 */
export function useBrandKit(): void {
  const { dispatch } = useDesign();

  useEffect(() => {
    const sync = (kit: FullBrandKit) => {
      dispatch({
        type: "SET_BRAND_KIT",
        brandKit: { colors: kit.colors, fonts: kit.fonts, logos: kit.logos },
      });
    };

    // init() is memoized in BrandKitService — safe if this effect runs
    // twice (React Strict Mode), both calls resolve to the same kit.
    void brandKitService.init().then(sync);

    return designBus.on("BrandKitChanged", payload => sync(payload.kit));
  }, [dispatch]);
}
