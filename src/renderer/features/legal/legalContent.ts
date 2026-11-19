/**
 * Privacy Policy and Terms of Use content (EN + AR).
 *
 * Kept as data (not i18n JSON) because legal text is long-form and must stay
 * identical in structure across languages. Describes what Flow actually does
 * in this codebase — update it whenever data handling changes.
 *
 * Not legal advice: have the text reviewed before relying on it commercially.
 */
import type { Lang } from "../../contexts/lang";
import type { LegalDoc } from "./legalRoutes";

export type { LegalDoc };

export interface LegalSection {
  heading: string;
  /** Rendered before the bullet list. */
  paragraphs?: string[];
  bullets?: string[];
  /** Rendered after the bullet list. */
  after?: string[];
}

export interface LegalContent {
  title: string;
  updatedLabel: string;
  intro: string;
  sections: LegalSection[];
}

export const LEGAL_LAST_UPDATED = "2026-11-19";

/** Optional public support address, set at build time (VITE_SUPPORT_EMAIL). */
export const SUPPORT_EMAIL: string = (import.meta.env.VITE_SUPPORT_EMAIL ?? "").trim();

function contactLine(lang: Lang): string {
  if (SUPPORT_EMAIL) {
    return lang === "ar"
      ? `للتواصل بخصوص هذه الوثيقة أو بياناتك: ${SUPPORT_EMAIL}`
      : `Questions about this document or your data: ${SUPPORT_EMAIL}`;
  }
  return lang === "ar"
    ? "للتواصل بخصوص هذه الوثيقة أو بياناتك، استخدم قناة الدعم داخل التطبيق."
    : "For questions about this document or your data, use the in-app support channel.";
}

const PRIVACY: Record<Lang, (contact: string) => LegalContent> = {
  en: (contact) => ({
    title: "Privacy Policy",
    updatedLabel: "Last updated",
    intro:
      "This policy explains what information Flow collects, why, and the choices you have. We collect only what is needed to run the service.",
    sections: [
      {
        heading: "1. Information we collect",
        bullets: [
          "Account data: your name, email address and a hashed password (we never store your password in plain text). If you sign in with Google, GitHub or Microsoft, we receive your basic profile and email from that provider.",
          "Content you create: projects, prompts, automations, leads, designs, files and other data you enter or upload.",
          "Connected accounts: if you connect a service such as Gmail or a social media account, we store the access tokens needed to perform the actions you request, and only read or post the data those actions require.",
          "Billing data: payments are processed by Stripe. We do not store full card numbers; we keep the subscription and invoice records Stripe returns.",
          "Usage and technical data: anonymous visit and sign-up events with campaign (UTM) parameters, server logs, and error reports used to keep the service reliable.",
        ],
      },
      {
        heading: "2. How we use information",
        bullets: [
          "To provide, operate and secure the service you signed up for.",
          "To run AI features: prompts and related content are sent to AI providers (such as Anthropic, OpenAI, Google or OpenRouter) only to generate the result you asked for.",
          "To send account emails such as verification and password reset.",
          "To understand which pages and campaigns bring people to Flow, using anonymous events.",
        ],
        after: ["We do not sell your personal information and we do not use your content to train our own AI models."],
      },
      {
        heading: "3. Service providers",
        paragraphs: [
          "We rely on trusted providers to run Flow, including hosting (Render, Vercel), payments (Stripe), AI model providers, and optional error monitoring (Sentry). They process data on our behalf and only as needed to provide their service.",
        ],
      },
      {
        heading: "4. Cookies and local storage",
        paragraphs: [
          "We use essential cookies and browser storage to keep you signed in and remember preferences such as language. Anonymous session identifiers are used for visit statistics. We do not use advertising cookies.",
        ],
      },
      {
        heading: "5. Data retention and deletion",
        paragraphs: [
          "We keep your data while your account is active. You can ask us to delete your account at any time using the contact details below; deletion removes your account and associated data, except records we must keep for legal, security or billing reasons.",
        ],
      },
      {
        heading: "6. Your rights",
        paragraphs: [
          "You can update your profile in the app, and you can request a copy of your personal data, its correction or its deletion using the contact details below. You can withdraw access for connected accounts at any time by disconnecting them.",
        ],
      },
      {
        heading: "7. Security",
        paragraphs: [
          "We use encryption in transit (HTTPS), hashed passwords, rate limiting and access controls. No system is perfectly secure; we will notify affected users of any breach as required by law.",
        ],
      },
      {
        heading: "8. Changes and contact",
        paragraphs: ["We may update this policy and will change the date above when we do. Significant changes will be announced in the app.", contact],
      },
    ],
  }),
  ar: (contact) => ({
    title: "سياسة الخصوصية",
    updatedLabel: "آخر تحديث",
    intro:
      "توضح هذه السياسة المعلومات التي يجمعها Flow وسبب جمعها والخيارات المتاحة لك. نجمع فقط ما يلزم لتشغيل الخدمة.",
    sections: [
      {
        heading: "1. المعلومات التي نجمعها",
        bullets: [
          "بيانات الحساب: اسمك وبريدك الإلكتروني وكلمة مرور مشفّرة (لا نخزّن كلمة المرور كنص واضح أبدًا). عند الدخول عبر Google أو GitHub أو Microsoft نستلم ملفك الأساسي وبريدك من ذلك المزود.",
          "المحتوى الذي تنشئه: المشاريع والطلبات والأتمتة والعملاء المحتملون والتصاميم والملفات وغيرها مما تدخله أو ترفعه.",
          "الحسابات المرتبطة: عند ربط خدمة مثل Gmail أو حساب تواصل اجتماعي، نخزّن رموز الوصول اللازمة لتنفيذ ما تطلبه فقط، ولا نقرأ أو ننشر إلا ما يتطلبه ذلك.",
          "بيانات الدفع: تتم المدفوعات عبر Stripe. لا نخزّن أرقام البطاقات كاملة، بل سجلات الاشتراك والفواتير التي يعيدها Stripe.",
          "بيانات الاستخدام والبيانات التقنية: أحداث زيارة وتسجيل مجهولة الهوية مع معلمات الحملات (UTM)، وسجلات الخادم، وتقارير الأخطاء لضمان استقرار الخدمة.",
        ],
      },
      {
        heading: "2. كيف نستخدم المعلومات",
        bullets: [
          "لتقديم الخدمة التي اشتركت فيها وتشغيلها وحمايتها.",
          "لتشغيل ميزات الذكاء الاصطناعي: تُرسَل الطلبات والمحتوى المرتبط بها إلى مزودي الذكاء الاصطناعي (مثل Anthropic وOpenAI وGoogle وOpenRouter) فقط لتوليد النتيجة التي طلبتها.",
          "لإرسال رسائل الحساب مثل التفعيل واستعادة كلمة المرور.",
          "لمعرفة الصفحات والحملات التي تجلب الزوار إلى Flow باستخدام أحداث مجهولة الهوية.",
        ],
        after: ["لا نبيع معلوماتك الشخصية، ولا نستخدم محتواك لتدريب نماذج ذكاء اصطناعي خاصة بنا."],
      },
      {
        heading: "3. مزودو الخدمات",
        paragraphs: [
          "نعتمد على مزودين موثوقين لتشغيل Flow، منهم الاستضافة (Render وVercel) والمدفوعات (Stripe) ومزودو نماذج الذكاء الاصطناعي ومراقبة الأخطاء الاختيارية (Sentry). يعالجون البيانات نيابةً عنا وبالقدر اللازم لتقديم خدمتهم فقط.",
        ],
      },
      {
        heading: "4. ملفات تعريف الارتباط والتخزين المحلي",
        paragraphs: [
          "نستخدم ملفات تعريف ارتباط أساسية وتخزين المتصفح لإبقائك مسجّل الدخول وتذكّر تفضيلاتك مثل اللغة. تُستخدم معرّفات جلسة مجهولة لإحصاءات الزيارات. لا نستخدم ملفات تعريف ارتباط إعلانية.",
        ],
      },
      {
        heading: "5. الاحتفاظ بالبيانات وحذفها",
        paragraphs: [
          "نحتفظ ببياناتك ما دام حسابك نشطًا. يمكنك طلب حذف حسابك في أي وقت عبر بيانات التواصل أدناه، فيُحذف الحساب والبيانات المرتبطة به، باستثناء السجلات التي يلزمنا الاحتفاظ بها لأسباب قانونية أو أمنية أو محاسبية.",
        ],
      },
      {
        heading: "6. حقوقك",
        paragraphs: [
          "يمكنك تعديل ملفك الشخصي من داخل التطبيق، وطلب نسخة من بياناتك الشخصية أو تصحيحها أو حذفها عبر بيانات التواصل أدناه. ويمكنك سحب الوصول من الحسابات المرتبطة في أي وقت بفصلها.",
        ],
      },
      {
        heading: "7. الأمان",
        paragraphs: [
          "نستخدم التشفير أثناء النقل (HTTPS) وتشفير كلمات المرور وتحديد معدل الطلبات وضوابط الوصول. لا يوجد نظام آمن تمامًا، وسنُبلغ المستخدمين المتأثرين بأي اختراق وفق ما يقتضيه القانون.",
        ],
      },
      {
        heading: "8. التعديلات والتواصل",
        paragraphs: ["قد نحدّث هذه السياسة ونغيّر التاريخ أعلاه عند ذلك، وسنعلن التغييرات الجوهرية داخل التطبيق.", contact],
      },
    ],
  }),
};

const TERMS: Record<Lang, (contact: string) => LegalContent> = {
  en: (contact) => ({
    title: "Terms of Use",
    updatedLabel: "Last updated",
    intro: "By creating an account or using Flow you agree to these terms. If you do not agree, please do not use the service.",
    sections: [
      {
        heading: "1. The service",
        paragraphs: [
          "Flow provides AI-assisted automation, app building and business tools. Features may change as the product evolves; we will try to give notice before removing features you rely on.",
        ],
      },
      {
        heading: "2. Your account",
        bullets: [
          "You must provide accurate information and keep your credentials secure.",
          "You are responsible for activity under your account and your organization.",
          "You must be at least 18 years old, or the age of majority where you live.",
        ],
      },
      {
        heading: "3. Acceptable use",
        paragraphs: ["You agree not to use Flow to:"],
        bullets: [
          "Break any law or infringe anyone's rights, including intellectual property and privacy.",
          "Send spam or unsolicited messages, or post content on connected accounts that violates those platforms' rules.",
          "Attempt to access other users' data, probe or attack the service, or bypass usage limits.",
          "Generate or distribute malware, or content that is abusive, deceptive or harmful.",
        ],
      },
      {
        heading: "4. Your content",
        paragraphs: [
          "You keep ownership of the content you create and upload. You give us permission to store, process and transmit it only as needed to operate the service for you, including sending it to AI providers when you use AI features.",
        ],
      },
      {
        heading: "5. AI output",
        paragraphs: [
          "AI-generated output can be inaccurate or incomplete. Review results — especially code, messages sent to customers, and published content — before relying on or sharing them. You are responsible for how you use the output.",
        ],
      },
      {
        heading: "6. Paid plans",
        paragraphs: [
          "Paid plans, pilots and setup fees are billed as described at purchase or in your written agreement. Subscriptions renew until cancelled; you can cancel at any time and keep access until the end of the paid period. Fees already paid are non-refundable unless required by law or agreed in writing.",
        ],
      },
      {
        heading: "7. Availability and liability",
        paragraphs: [
          "The service is provided \"as is\". We work to keep it available and secure but do not guarantee uninterrupted operation. To the extent permitted by law, our total liability for any claim is limited to the amount you paid us in the three months before the claim, and we are not liable for indirect or consequential losses.",
        ],
      },
      {
        heading: "8. Suspension and termination",
        paragraphs: [
          "You may stop using Flow and delete your account at any time. We may suspend or close accounts that violate these terms or put the service or other users at risk.",
        ],
      },
      {
        heading: "9. Governing law and changes",
        paragraphs: [
          "These terms are governed by the laws of the United Arab Emirates. We may update them and will change the date above; continued use after changes means you accept them.",
          contact,
        ],
      },
    ],
  }),
  ar: (contact) => ({
    title: "شروط الاستخدام",
    updatedLabel: "آخر تحديث",
    intro: "بإنشاء حساب أو استخدام Flow فإنك توافق على هذه الشروط. إذا لم توافق عليها، يُرجى عدم استخدام الخدمة.",
    sections: [
      {
        heading: "1. الخدمة",
        paragraphs: [
          "يقدّم Flow أدوات أتمتة وبناء تطبيقات وأدوات أعمال مدعومة بالذكاء الاصطناعي. قد تتغير الميزات مع تطور المنتج، وسنحاول الإشعار مسبقًا قبل إزالة ميزة تعتمد عليها.",
        ],
      },
      {
        heading: "2. حسابك",
        bullets: [
          "يجب تقديم معلومات صحيحة والحفاظ على سرية بيانات الدخول.",
          "أنت مسؤول عن النشاط الذي يتم عبر حسابك ومؤسستك.",
          "يجب ألا يقل عمرك عن 18 عامًا أو سن الرشد في بلدك.",
        ],
      },
      {
        heading: "3. الاستخدام المقبول",
        paragraphs: ["توافق على عدم استخدام Flow في:"],
        bullets: [
          "مخالفة أي قانون أو التعدي على حقوق الآخرين، ومنها الملكية الفكرية والخصوصية.",
          "إرسال رسائل مزعجة أو غير مرغوبة، أو نشر محتوى على الحسابات المرتبطة يخالف قواعد تلك المنصات.",
          "محاولة الوصول إلى بيانات مستخدمين آخرين أو فحص الخدمة أو مهاجمتها أو تجاوز حدود الاستخدام.",
          "إنشاء برمجيات خبيثة أو نشرها، أو محتوى مسيء أو مضلل أو ضار.",
        ],
      },
      {
        heading: "4. محتواك",
        paragraphs: [
          "تبقى ملكية المحتوى الذي تنشئه وترفعه لك. وتمنحنا الإذن بتخزينه ومعالجته ونقله بالقدر اللازم لتشغيل الخدمة لك فقط، بما في ذلك إرساله إلى مزودي الذكاء الاصطناعي عند استخدامك لميزاته.",
        ],
      },
      {
        heading: "5. مخرجات الذكاء الاصطناعي",
        paragraphs: [
          "قد تكون مخرجات الذكاء الاصطناعي غير دقيقة أو ناقصة. راجع النتائج، خصوصًا الكود والرسائل المرسلة للعملاء والمحتوى المنشور، قبل الاعتماد عليها أو مشاركتها. أنت المسؤول عن طريقة استخدامك لها.",
        ],
      },
      {
        heading: "6. الخطط المدفوعة",
        paragraphs: [
          "تُحتسب رسوم الخطط المدفوعة والتجارب (Pilot) ورسوم الإعداد كما هو موضح عند الشراء أو في اتفاقك المكتوب. تتجدد الاشتراكات حتى إلغائها، ويمكنك الإلغاء في أي وقت مع بقاء الوصول حتى نهاية الفترة المدفوعة. الرسوم المدفوعة غير قابلة للاسترداد إلا إذا اقتضى القانون ذلك أو اتُّفق عليه كتابيًا.",
        ],
      },
      {
        heading: "7. التوفر والمسؤولية",
        paragraphs: [
          "تُقدَّم الخدمة \"كما هي\". نعمل على إبقائها متاحة وآمنة لكننا لا نضمن عملها دون انقطاع. وفي الحدود التي يسمح بها القانون، تقتصر مسؤوليتنا الإجمالية عن أي مطالبة على المبلغ الذي دفعته لنا خلال الأشهر الثلاثة السابقة للمطالبة، ولا نتحمل الخسائر غير المباشرة أو التبعية.",
        ],
      },
      {
        heading: "8. الإيقاف والإنهاء",
        paragraphs: [
          "يمكنك التوقف عن استخدام Flow وحذف حسابك في أي وقت. ويحق لنا إيقاف أو إغلاق الحسابات التي تخالف هذه الشروط أو تعرّض الخدمة أو المستخدمين الآخرين للخطر.",
        ],
      },
      {
        heading: "9. القانون الحاكم والتعديلات",
        paragraphs: [
          "تخضع هذه الشروط لقوانين دولة الإمارات العربية المتحدة. قد نحدّثها ونغيّر التاريخ أعلاه، واستمرارك في الاستخدام بعد التعديل يعني قبولك لها.",
          contact,
        ],
      },
    ],
  }),
};

export function getLegalContent(doc: LegalDoc, lang: Lang): LegalContent {
  const source = doc === "privacy" ? PRIVACY : TERMS;
  return source[lang](contactLine(lang));
}
