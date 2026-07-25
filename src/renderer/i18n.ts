import i18next from "i18next";
import { initReactI18next } from "react-i18next";

import commonEn from "./locales/en/common.json";
import commonAr from "./locales/ar/common.json";

void i18next.use(initReactI18next).init({
  resources: {
    en: { common: commonEn },
    ar: { common: commonAr },
  },
  lng: "en",
  fallbackLng: "en",
  defaultNS: "common",
  ns: ["common"],
  interpolation: { escapeValue: false },
  returnEmptyString: false,
});

export default i18next;
