import i18next from "i18next";
import { initReactI18next } from "react-i18next";

import commonEn from "./locales/en/common.json";
import commonAr from "./locales/ar/common.json";
import homeEn from "./locales/en/home.json";
import homeAr from "./locales/ar/home.json";
import settingsEn from "./locales/en/settings.json";
import settingsAr from "./locales/ar/settings.json";
import authEn from "./locales/en/auth.json";
import authAr from "./locales/ar/auth.json";

void i18next.use(initReactI18next).init({
  resources: {
    en: { common: commonEn, home: homeEn, settings: settingsEn, auth: authEn },
    ar: { common: commonAr, home: homeAr, settings: settingsAr, auth: authAr },
  },
  lng: "en",
  fallbackLng: "en",
  defaultNS: "common",
  ns: ["common", "home", "settings", "auth"],
  interpolation: { escapeValue: false },
  returnEmptyString: false,
});

export default i18next;
