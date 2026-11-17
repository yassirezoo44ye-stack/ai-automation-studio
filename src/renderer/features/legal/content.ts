// Draft legal documents for Flow, in English and Arabic.
//
// DRAFT: written from what the code actually does (see docs/legal/README.md),
// not reviewed by a lawyer. Have a UAE-licensed lawyer review before launch.
// Bump LEGAL_VERSION together with TERMS_VERSION in app/core/legal.py.

export const LEGAL_VERSION = "2026-11-17";

export type LegalDocId = "privacy" | "terms" | "refunds";
export type LegalLang = "en" | "ar";

/** Fill these in before publishing. They appear in all three documents. */
export const LEGAL_ENTITY = {
  name: "[Legal entity name]",
  nameAr: "[الاسم القانوني للمنشأة]",
  address: "[Registered address, Dubai, United Arab Emirates]",
  addressAr: "[العنوان المسجّل، دبي، الإمارات العربية المتحدة]",
  email: "[privacy@your-domain]",
};

export interface LegalSection {
  heading: string;
  paragraphs?: string[];
  bullets?: string[];
}

export interface LegalDoc {
  title: string;
  intro: string;
  sections: LegalSection[];
}

const E = LEGAL_ENTITY;

const en: Record<LegalDocId, LegalDoc> = {
  privacy: {
    title: "Privacy Policy",
    intro: `This policy explains what personal data Flow collects, why, who we share it with, and the choices you have. Flow is operated by ${E.name}, ${E.address} ("we"). For data you put into Flow about yourself, we are the controller. For data your organization collects about other people through Flow (for example leads captured by your forms), your organization is the controller and we process it on its behalf.`,
    sections: [
      {
        heading: "1. Data we collect",
        bullets: [
          "Account data: your name, e-mail address and a one-way hash of your password. If you sign in with Google, GitHub or Microsoft we receive your name, e-mail and profile picture from that provider.",
          "Content you create: projects, workflows, documents, prompts you send to AI features and the answers they return, files you upload, and courses you author.",
          "Connected accounts: when you connect a social account (such as TikTok or YouTube) we store the access tokens, encrypted, to publish on your behalf.",
          "Billing data: your plan, subscription status and invoices. Card details are handled by Stripe (subscriptions) or Payhip (digital products); we never see or store full card numbers.",
          "Technical and security data: IP address, browser user agent, sign-in sessions, and a security log of account events such as sign-ins, password changes and deletions.",
          "Marketing attribution: when you arrive from a link with campaign tags (utm_source and similar), we record those tags and simple page events for our own measurement. We do not use advertising or cross-site tracking cookies.",
          "Data about other people that you bring in, such as leads from your forms or members you invite to your organization.",
        ],
      },
      {
        heading: "2. Why we use it",
        bullets: [
          "To provide the service you signed up for (performance of our contract with you).",
          "To keep accounts and the platform secure, prevent abuse and investigate incidents (our legitimate interest).",
          "To process payments and keep the financial records the law requires (legal obligation).",
          "To send service e-mails such as address verification and password resets. We do not send marketing e-mail without your consent.",
          "To understand which campaigns bring visitors, in aggregate (our legitimate interest).",
        ],
      },
      {
        heading: "3. AI features",
        paragraphs: [
          "When you use an AI feature, the text and files you submit are sent to the AI provider that serves the request, currently one of Anthropic, OpenAI, Google (Gemini), Groq or Mistral. Their answer is returned to you and may be stored in your workspace. The provider processes it under its API terms as our service provider. Do not submit sensitive personal data (such as health data) to AI features unless you need to.",
        ],
      },
      {
        heading: "4. Who we share data with",
        paragraphs: [
          "We do not sell personal data. We share it only with service providers that help us run Flow, under contracts that limit their use of it:",
        ],
        bullets: [
          "Hosting and infrastructure (Render, Vercel and our database provider).",
          "Payments: Stripe and Payhip.",
          "E-mail delivery: our transactional e-mail provider.",
          "AI providers listed in section 3.",
          "Platforms you connect yourself, such as TikTok, YouTube, Google, GitHub and Microsoft.",
          "Authorities, when the law requires it.",
        ],
      },
      {
        heading: "5. International transfers",
        paragraphs: [
          "Several of these providers process data outside the United Arab Emirates, including in the United States and the European Union. When we transfer personal data abroad we rely on the safeguards permitted by UAE Federal Decree-Law No. 45 of 2021 on the Protection of Personal Data and, where it applies, the EU General Data Protection Regulation, such as standard contractual clauses.",
        ],
      },
      {
        heading: "6. How long we keep it",
        bullets: [
          "Account data and content: for as long as your account exists. When you delete your account they are deleted, together with any organization in which you were the only member.",
          "Billing records: for the period required by UAE tax and commercial law (generally five years), even after account deletion.",
          "Security logs: for as long as needed to protect the service and meet legal obligations.",
        ],
      },
      {
        heading: "7. Your rights",
        paragraphs: [
          "Depending on where you live you may have the right to access, correct, delete or download your data, to object to or restrict certain processing, and to withdraw consent. You can do most of this yourself in Settings → Account: \"Download my data\" gives you a copy of your data as a file, and \"Delete account\" erases your account. For anything else, write to us at the address below. You also have the right to complain to the UAE Data Office or, in the EU, to your local data-protection authority.",
        ],
      },
      {
        heading: "8. Storage on your device",
        paragraphs: [
          "Flow stores a small amount of data in your browser that it needs to work: your sign-in session, language and theme. Campaign tags are kept only for the current browser session. We do not use advertising cookies. If we ever add analytics or advertising cookies we will ask for your consent first.",
        ],
      },
      {
        heading: "9. Security",
        paragraphs: [
          "We protect data with encryption in transit, hashed passwords, optional two-factor authentication, encrypted storage of connected-account tokens, and access controls inside organizations. No system is perfectly secure; if a breach affects your data we will tell you and the authorities as the law requires.",
        ],
      },
      {
        heading: "10. Children",
        paragraphs: [
          "Flow is not intended for anyone under 16, and we do not knowingly collect their data. If you believe a child has given us data, contact us and we will delete it.",
        ],
      },
      {
        heading: "11. Changes and contact",
        paragraphs: [
          "If we change this policy in a meaningful way we will notify you in the app or by e-mail before the change takes effect.",
          `Contact: ${E.name}, ${E.address}. E-mail: ${E.email}.`,
        ],
      },
    ],
  },
  terms: {
    title: "Terms of Use",
    intro: `These terms are an agreement between you and ${E.name} ("we") for your use of Flow. By creating an account or using Flow you agree to them. If you use Flow for an organization, you confirm you may bind it to these terms.`,
    sections: [
      {
        heading: "1. Your account",
        bullets: [
          "You must be at least 16, and old enough to enter a contract where you live to buy a paid plan.",
          "Give accurate information, keep your password safe, and tell us about any unauthorized use.",
          "You are responsible for what happens under your account and in organizations you administer.",
        ],
      },
      {
        heading: "2. Acceptable use",
        paragraphs: ["You must not use Flow to:"],
        bullets: [
          "Break any law, including UAE Federal Decree-Law No. 34 of 2021 on Combating Rumours and Cybercrimes.",
          "Access, test, scan or control any system, account or device you do not own or are not explicitly authorized to use. Device control features may only be used on devices you own or manage with the user's permission.",
          "Send spam, publish misleading content, or break the rules of platforms you publish to through Flow.",
          "Upload content that infringes someone else's rights, or that is unlawful, abusive or harmful.",
          "Interfere with Flow, bypass its limits or security, or resell it without our written permission.",
        ],
      },
      {
        heading: "3. AI-generated output",
        paragraphs: [
          "Flow's AI features can make mistakes. Review output before you rely on it, publish it or send it to others. Output is not professional advice (legal, financial, medical or otherwise). You are responsible for how you use it.",
        ],
      },
      {
        heading: "4. Your content",
        paragraphs: [
          "You keep ownership of the content you put into Flow and the output it produces for you. You give us a limited licence to host, process and display that content only to provide the service. You confirm you have the rights needed for content you upload, including personal data about others, and that you have told those people as the law requires.",
        ],
      },
      {
        heading: "5. Courses and learning content",
        paragraphs: [
          "Courses on Flow, including security courses, are for education. Techniques must only be practised on systems you own or have written permission to test. Unauthorized access to systems is a crime in the UAE and most other countries. We are not responsible for misuse of what you learn.",
        ],
      },
      {
        heading: "6. Plans, payment and renewal",
        bullets: [
          "Paid plans are billed in advance through Stripe and renew automatically each billing period until you cancel.",
          "You can cancel any time from Billing. Cancellation stops the next renewal; you keep access until the end of the period you paid for.",
          "Prices are shown before you pay and include or add taxes as required by law. We will give you notice before a price change applies to your plan.",
          "Refunds are covered by our Refund Policy.",
        ],
      },
      {
        heading: "7. Third-party services",
        paragraphs: [
          "Flow connects to services we do not control, such as AI providers, social networks and payment processors. Their terms apply to your use of them, and we are not responsible for their availability or actions.",
        ],
      },
      {
        heading: "8. Suspension and termination",
        paragraphs: [
          "You can stop using Flow and delete your account at any time. We may suspend or close accounts that break these terms or put the service or others at risk; where reasonable we will warn you first and let you export your data.",
        ],
      },
      {
        heading: "9. Disclaimers and liability",
        paragraphs: [
          "Flow is provided \"as is\". To the extent the law allows, we do not guarantee that it will be uninterrupted or error-free, and we are not liable for indirect or consequential losses or lost profits. Our total liability for any claim is limited to the amount you paid us in the twelve months before the claim. Nothing in these terms limits rights you have under consumer-protection law that cannot be waived.",
        ],
      },
      {
        heading: "10. Law and disputes",
        paragraphs: [
          "These terms are governed by the laws of the United Arab Emirates as applied in the Emirate of Dubai, and the courts of Dubai have jurisdiction, unless consumer law where you live gives you the right to bring a claim locally.",
        ],
      },
      {
        heading: "11. Changes and contact",
        paragraphs: [
          "We may update these terms. For meaningful changes we will notify you before they take effect; continuing to use Flow after that means you accept them.",
          `Contact: ${E.name}, ${E.address}. E-mail: ${E.email}.`,
        ],
      },
    ],
  },
  refunds: {
    title: "Refund and Cancellation Policy",
    intro: "This policy explains how cancellations and refunds work for Flow subscriptions and for digital products sold through Flow.",
    sections: [
      {
        heading: "1. Cancelling a subscription",
        paragraphs: [
          "You can cancel at any time from Billing. Your plan stays active until the end of the billing period you already paid for and does not renew after that. Deleting your account cancels your subscription immediately.",
        ],
      },
      {
        heading: "2. Subscription refunds",
        bullets: [
          "First payment: if you are not satisfied, ask for a refund within 7 days of your first payment for a plan and we will refund it in full.",
          "Renewals: renewal payments are not refunded for a partly used period, but you can cancel to stop the next renewal.",
          "Billing errors, such as a duplicate charge or a charge after you cancelled, are always refunded in full.",
        ],
      },
      {
        heading: "3. Digital products (study summaries and similar)",
        paragraphs: [
          "Digital products are delivered immediately. By completing the purchase you ask us to deliver them right away. If a file is faulty or not as described, contact us within 14 days and we will fix it or refund you. A refunded purchase removes access to the product.",
        ],
      },
      {
        heading: "4. How to ask, and timing",
        paragraphs: [
          `E-mail ${E.email} from the address on your account with the date of the charge. Approved refunds go back to the original payment method, usually within 5 to 10 business days depending on your bank.`,
        ],
      },
      {
        heading: "5. Your legal rights",
        paragraphs: [
          "This policy does not limit any right you have under UAE Federal Law No. 15 of 2020 on Consumer Protection or the consumer law of the country where you live.",
        ],
      },
    ],
  },
};

const ar: Record<LegalDocId, LegalDoc> = {
  privacy: {
    title: "سياسة الخصوصية",
    intro: `توضح هذه السياسة البيانات الشخصية التي تجمعها منصة Flow، ولماذا نجمعها، ومع من نشاركها، والخيارات المتاحة لك. تُشغِّل المنصة ${E.nameAr}، ${E.addressAr} ("نحن"). نحن المتحكّم في البيانات التي تُدخلها عن نفسك. أما البيانات التي تجمعها منظمتك عن أشخاص آخرين عبر Flow (مثل العملاء المحتملين من نماذجك)، فمنظمتك هي المتحكّم فيها ونحن نعالجها نيابة عنها.`,
    sections: [
      {
        heading: "1. البيانات التي نجمعها",
        bullets: [
          "بيانات الحساب: اسمك وبريدك الإلكتروني وتجزئة أحادية الاتجاه لكلمة المرور. إذا سجّلت الدخول بحساب Google أو GitHub أو Microsoft نستلم منه اسمك وبريدك وصورتك.",
          "المحتوى الذي تنشئه: المشاريع وسير العمل والمستندات والطلبات التي ترسلها لميزات الذكاء الاصطناعي وإجاباتها، والملفات التي ترفعها، والكورسات التي تؤلفها.",
          "الحسابات المرتبطة: عند ربط حساب تواصل اجتماعي (مثل TikTok أو YouTube) نحفظ رموز الوصول مشفّرة لننشر نيابة عنك.",
          "بيانات الفوترة: خطتك وحالة اشتراكك وفواتيرك. تتولى Stripe (الاشتراكات) أو Payhip (المنتجات الرقمية) بيانات البطاقة، ولا نرى رقم البطاقة كاملاً ولا نحفظه.",
          "البيانات التقنية والأمنية: عنوان IP ونوع المتصفح وجلسات الدخول وسجل أمني لأحداث الحساب مثل الدخول وتغيير كلمة المرور والحذف.",
          "مصدر الزيارة: إذا وصلت عبر رابط يحمل وسوم حملة (مثل utm_source) نسجّل هذه الوسوم وأحداثاً بسيطة في الصفحة لقياس حملاتنا. لا نستخدم ملفات ارتباط إعلانية أو تتبعاً عبر المواقع.",
          "بيانات أشخاص آخرين تُدخلها أنت، مثل العملاء المحتملين من نماذجك أو الأعضاء الذين تدعوهم لمنظمتك.",
        ],
      },
      {
        heading: "2. لماذا نستخدمها",
        bullets: [
          "لتقديم الخدمة التي اشتركت فيها (تنفيذ العقد بيننا).",
          "لحماية الحسابات والمنصة ومنع إساءة الاستخدام والتحقيق في الحوادث (مصلحتنا المشروعة).",
          "لمعالجة المدفوعات والاحتفاظ بالسجلات المالية التي يفرضها القانون (التزام قانوني).",
          "لإرسال رسائل الخدمة مثل تأكيد البريد واستعادة كلمة المرور. لا نرسل بريداً تسويقياً دون موافقتك.",
          "لمعرفة الحملات التي تجلب الزوار بشكل إجمالي (مصلحتنا المشروعة).",
        ],
      },
      {
        heading: "3. ميزات الذكاء الاصطناعي",
        paragraphs: [
          "عند استخدام ميزة ذكاء اصطناعي، يُرسَل النص والملفات التي تقدّمها إلى المزوّد الذي يعالج الطلب، وهو حالياً أحد: Anthropic أو OpenAI أو Google (Gemini) أو Groq أو Mistral. تعود الإجابة إليك وقد تُحفظ في مساحة عملك. ويعالجها المزوّد بصفته مزوّد خدمة لنا وفق شروط واجهته البرمجية. لا ترسل بيانات شخصية حساسة (مثل البيانات الصحية) إلى هذه الميزات إلا عند الحاجة.",
        ],
      },
      {
        heading: "4. مع من نشارك البيانات",
        paragraphs: [
          "لا نبيع البيانات الشخصية. نشاركها فقط مع مزوّدي خدمات يساعدوننا في تشغيل Flow، بموجب عقود تقيّد استخدامهم لها:",
        ],
        bullets: [
          "الاستضافة والبنية التحتية (Render وVercel ومزوّد قاعدة البيانات).",
          "المدفوعات: Stripe وPayhip.",
          "إرسال البريد: مزوّد البريد التشغيلي.",
          "مزوّدو الذكاء الاصطناعي المذكورون في البند 3.",
          "المنصات التي تربطها بنفسك، مثل TikTok وYouTube وGoogle وGitHub وMicrosoft.",
          "الجهات الرسمية عندما يفرض القانون ذلك.",
        ],
      },
      {
        heading: "5. نقل البيانات خارج الدولة",
        paragraphs: [
          "يعالج عدد من هؤلاء المزوّدين البيانات خارج دولة الإمارات، ومنها الولايات المتحدة والاتحاد الأوروبي. عند نقل البيانات للخارج نعتمد الضمانات التي يجيزها المرسوم بقانون اتحادي رقم 45 لسنة 2021 بشأن حماية البيانات الشخصية، واللائحة الأوروبية العامة لحماية البيانات (GDPR) حيث تنطبق، مثل البنود التعاقدية القياسية.",
        ],
      },
      {
        heading: "6. مدة الاحتفاظ",
        bullets: [
          "بيانات الحساب والمحتوى: طوال وجود حسابك. عند حذف الحساب تُحذف، ومعها أي منظمة كنت العضو الوحيد فيها.",
          "سجلات الفوترة: للمدة التي يفرضها قانون الضرائب والقانون التجاري في الإمارات (خمس سنوات عادة)، حتى بعد حذف الحساب.",
          "السجلات الأمنية: للمدة اللازمة لحماية الخدمة والوفاء بالالتزامات القانونية.",
        ],
      },
      {
        heading: "7. حقوقك",
        paragraphs: [
          "حسب مكان إقامتك، قد يحق لك الاطلاع على بياناتك وتصحيحها وحذفها وتنزيل نسخة منها، والاعتراض على بعض المعالجة أو تقييدها، وسحب موافقتك. يمكنك فعل معظم ذلك بنفسك من الإعدادات ← الحساب: زر \"تنزيل بياناتي\" يعطيك نسخة من بياناتك في ملف، وزر \"حذف الحساب\" يمحو حسابك. لأي طلب آخر راسلنا على العنوان أدناه. ويحق لك أيضاً تقديم شكوى إلى مكتب الإمارات للبيانات، أو إلى سلطة حماية البيانات في بلدك إن كنت في الاتحاد الأوروبي.",
        ],
      },
      {
        heading: "8. التخزين على جهازك",
        paragraphs: [
          "تحفظ Flow في متصفحك قدراً صغيراً من البيانات اللازمة لعملها: جلسة الدخول واللغة والمظهر. وتُحفظ وسوم الحملات لجلسة المتصفح الحالية فقط. لا نستخدم ملفات ارتباط إعلانية، وإن أضفنا يوماً أدوات تحليل أو إعلانات فسنطلب موافقتك أولاً.",
        ],
      },
      {
        heading: "9. الأمان",
        paragraphs: [
          "نحمي البيانات بالتشفير أثناء النقل، وتجزئة كلمات المرور، والتحقق الثنائي الاختياري، وتشفير رموز الحسابات المرتبطة، وصلاحيات الوصول داخل المنظمات. لا يوجد نظام آمن تماماً، وإذا تأثرت بياناتك باختراق فسنبلغك ونبلغ الجهات المختصة كما يفرض القانون.",
        ],
      },
      {
        heading: "10. الأطفال",
        paragraphs: [
          "المنصة غير موجهة لمن هم دون 16 عاماً، ولا نجمع بياناتهم عن علم. إن كنت تعتقد أن طفلاً قدّم لنا بيانات فراسلنا لنحذفها.",
        ],
      },
      {
        heading: "11. التعديلات والتواصل",
        paragraphs: [
          "إذا عدّلنا هذه السياسة تعديلاً جوهرياً فسنخبرك داخل المنصة أو بالبريد قبل سريانه.",
          `للتواصل: ${E.nameAr}، ${E.addressAr}. البريد: ${E.email}.`,
        ],
      },
    ],
  },
  terms: {
    title: "شروط الاستخدام",
    intro: `هذه الشروط اتفاق بينك وبين ${E.nameAr} ("نحن") على استخدامك منصة Flow. بإنشاء حساب أو استخدام المنصة فأنت توافق عليها. وإن كنت تستخدمها لصالح منظمة فأنت تؤكد أن لك صلاحية إلزامها بهذه الشروط.`,
    sections: [
      {
        heading: "1. حسابك",
        bullets: [
          "يجب ألا يقل عمرك عن 16 عاماً، وأن تكون بالغاً سن التعاقد في بلدك لشراء خطة مدفوعة.",
          "قدّم معلومات صحيحة، واحفظ كلمة المرور، وأبلغنا بأي استخدام غير مصرّح به.",
          "أنت مسؤول عما يحدث في حسابك وفي المنظمات التي تديرها.",
        ],
      },
      {
        heading: "2. الاستخدام المقبول",
        paragraphs: ["لا يجوز لك استخدام Flow من أجل:"],
        bullets: [
          "مخالفة أي قانون، ومنه المرسوم بقانون اتحادي رقم 34 لسنة 2021 في شأن مكافحة الشائعات والجرائم الإلكترونية.",
          "الدخول إلى أي نظام أو حساب أو جهاز لا تملكه أو لم تحصل على إذن صريح باستخدامه، أو فحصه أو اختباره أو التحكم فيه. ولا تُستخدم ميزات التحكم بالأجهزة إلا على أجهزة تملكها أو تديرها بإذن مستخدمها.",
          "إرسال رسائل مزعجة، أو نشر محتوى مضلّل، أو مخالفة قواعد المنصات التي تنشر عليها عبر Flow.",
          "رفع محتوى يعتدي على حقوق غيرك، أو مخالف للقانون، أو مسيء أو ضار.",
          "تعطيل المنصة، أو تجاوز حدودها أو حمايتها، أو إعادة بيعها دون إذن كتابي منا.",
        ],
      },
      {
        heading: "3. مخرجات الذكاء الاصطناعي",
        paragraphs: [
          "قد تخطئ ميزات الذكاء الاصطناعي. راجع المخرجات قبل الاعتماد عليها أو نشرها أو إرسالها للآخرين. المخرجات ليست استشارة مهنية (قانونية أو مالية أو طبية أو غيرها)، وأنت مسؤول عن طريقة استخدامها.",
        ],
      },
      {
        heading: "4. محتواك",
        paragraphs: [
          "تبقى مالكاً للمحتوى الذي تضعه في Flow وللمخرجات التي تنتجها لك. وتمنحنا ترخيصاً محدوداً لاستضافة هذا المحتوى ومعالجته وعرضه لغرض تقديم الخدمة فقط. وتؤكد أن لديك الحقوق اللازمة للمحتوى الذي ترفعه، ومنه البيانات الشخصية لغيرك، وأنك أبلغت أصحابها كما يفرض القانون.",
        ],
      },
      {
        heading: "5. الكورسات والمحتوى التعليمي",
        paragraphs: [
          "الكورسات على Flow، ومنها كورسات الأمن السيبراني، للتعليم فقط. لا تُطبَّق التقنيات إلا على أنظمة تملكها أو لديك إذن مكتوب باختبارها. الدخول غير المصرّح به إلى الأنظمة جريمة في الإمارات ومعظم الدول، ولسنا مسؤولين عن إساءة استخدام ما تتعلمه.",
        ],
      },
      {
        heading: "6. الخطط والدفع والتجديد",
        bullets: [
          "تُدفع الخطط المدفوعة مقدماً عبر Stripe وتتجدد تلقائياً كل فترة فوترة حتى تلغيها.",
          "يمكنك الإلغاء في أي وقت من صفحة الفوترة. الإلغاء يوقف التجديد القادم، ويبقى وصولك حتى نهاية الفترة المدفوعة.",
          "تظهر الأسعار قبل الدفع، وتشمل الضرائب أو تُضاف إليها كما يفرض القانون. وسنبلغك قبل أن يسري أي تغيير في السعر على خطتك.",
          "تخضع المبالغ المستردة لسياسة الاسترداد.",
        ],
      },
      {
        heading: "7. خدمات الأطراف الأخرى",
        paragraphs: [
          "تتصل Flow بخدمات لا نتحكم فيها، مثل مزوّدي الذكاء الاصطناعي وشبكات التواصل ومعالجي الدفع. تسري شروطها على استخدامك لها، ولسنا مسؤولين عن توفرها أو تصرفاتها.",
        ],
      },
      {
        heading: "8. الإيقاف والإنهاء",
        paragraphs: [
          "يمكنك التوقف عن استخدام Flow وحذف حسابك في أي وقت. ويجوز لنا إيقاف أو إغلاق الحسابات التي تخالف هذه الشروط أو تعرّض الخدمة أو الآخرين للخطر، وسننبهك أولاً ونتيح لك تصدير بياناتك متى كان ذلك معقولاً.",
        ],
      },
      {
        heading: "9. إخلاء المسؤولية وحدودها",
        paragraphs: [
          "تُقدَّم Flow \"كما هي\". وفي الحدود التي يسمح بها القانون، لا نضمن أن تعمل دون انقطاع أو أخطاء، ولسنا مسؤولين عن الخسائر غير المباشرة أو التبعية أو فوات الأرباح. ولا تتجاوز مسؤوليتنا الإجمالية عن أي مطالبة ما دفعته لنا خلال الاثني عشر شهراً السابقة لها. ولا يحدّ شيء في هذه الشروط من حقوقك التي لا يجوز التنازل عنها بموجب قانون حماية المستهلك.",
        ],
      },
      {
        heading: "10. القانون والنزاعات",
        paragraphs: [
          "تخضع هذه الشروط لقوانين دولة الإمارات العربية المتحدة كما تُطبَّق في إمارة دبي، وتختص محاكم دبي بالنظر في النزاعات، ما لم يمنحك قانون المستهلك في بلدك حق التقاضي محلياً.",
        ],
      },
      {
        heading: "11. التعديلات والتواصل",
        paragraphs: [
          "قد نحدّث هذه الشروط، وسنخبرك بالتعديلات الجوهرية قبل سريانها، واستمرارك في استخدام Flow بعد ذلك يعني قبولها.",
          `للتواصل: ${E.nameAr}، ${E.addressAr}. البريد: ${E.email}.`,
        ],
      },
    ],
  },
  refunds: {
    title: "سياسة الاسترداد والإلغاء",
    intro: "توضح هذه السياسة كيف يتم إلغاء اشتراكات Flow واسترداد المبالغ، وكذلك للمنتجات الرقمية التي تُباع عبر المنصة.",
    sections: [
      {
        heading: "1. إلغاء الاشتراك",
        paragraphs: [
          "يمكنك الإلغاء في أي وقت من صفحة الفوترة. تبقى خطتك فعّالة حتى نهاية فترة الفوترة المدفوعة ولا تتجدد بعدها. وحذف الحساب يلغي الاشتراك فوراً.",
        ],
      },
      {
        heading: "2. استرداد مبالغ الاشتراك",
        bullets: [
          "الدفعة الأولى: إن لم تكن راضياً، اطلب الاسترداد خلال 7 أيام من أول دفعة لخطة ما، وسنرد المبلغ كاملاً.",
          "التجديدات: لا تُسترد دفعات التجديد عن فترة استُخدم جزء منها، ويمكنك الإلغاء لإيقاف التجديد القادم.",
          "أخطاء الفوترة، مثل الخصم المكرر أو الخصم بعد الإلغاء، تُسترد كاملة دائماً.",
        ],
      },
      {
        heading: "3. المنتجات الرقمية (الملخصات الدراسية وما يشبهها)",
        paragraphs: [
          "تُسلَّم المنتجات الرقمية فوراً، وبإتمام الشراء تطلب منا تسليمها مباشرة. إذا كان الملف تالفاً أو مخالفاً لوصفه فراسلنا خلال 14 يوماً لنصلحه أو نرد المبلغ. ويُلغى الوصول إلى المنتج عند استرداد ثمنه.",
        ],
      },
      {
        heading: "4. طريقة الطلب والمدة",
        paragraphs: [
          `راسل ${E.email} من البريد المسجّل في حسابك مع تاريخ الخصم. تعود المبالغ المعتمدة إلى وسيلة الدفع الأصلية، عادة خلال 5 إلى 10 أيام عمل حسب البنك.`,
        ],
      },
      {
        heading: "5. حقوقك القانونية",
        paragraphs: [
          "لا تحدّ هذه السياسة من أي حق لك بموجب القانون الاتحادي رقم 15 لسنة 2020 بشأن حماية المستهلك أو قانون المستهلك في بلدك.",
        ],
      },
    ],
  },
};

export const LEGAL_DOCS: Record<LegalLang, Record<LegalDocId, LegalDoc>> = { en, ar };

export const LEGAL_PATHS: Record<LegalDocId, string> = {
  privacy: "/privacy",
  terms: "/terms",
  refunds: "/refunds",
};

export function legalDocFromPath(pathname: string): LegalDocId | null {
  const clean = pathname.replace(/\/+$/, "") || "/";
  const hit = (Object.keys(LEGAL_PATHS) as LegalDocId[]).find(id => LEGAL_PATHS[id] === clean);
  return hit ?? null;
}
