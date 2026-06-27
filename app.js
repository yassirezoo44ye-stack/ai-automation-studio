import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();

const RSS_FEEDS = [
  "https://feeds.bbci.co.uk/news/rss.xml",
  "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
  "https://feeds.reuters.com/reuters/topNews",
  "https://techcrunch.com/feed/",
];

async function fetchRSSFeed(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
  return res.text();
}

function parseRSSItems(xml) {
  const items = [];
  const itemPattern = /<item>([\s\S]*?)<\/item>/g;
  const titlePattern = /<title><!\[CDATA\[(.*?)\]\]><\/title>|<title>(.*?)<\/title>/;
  const descPattern = /<description><!\[CDATA\[(.*?)\]\]><\/description>|<description>(.*?)<\/description>/;

  let match;
  while ((match = itemPattern.exec(xml)) !== null) {
    const block = match[1];
    const titleMatch = titlePattern.exec(block);
    const descMatch = descPattern.exec(block);
    const title = (titleMatch?.[1] ?? titleMatch?.[2] ?? "").trim();
    const description = (descMatch?.[1] ?? descMatch?.[2] ?? "").trim();
    if (title) items.push({ title, description });
  }
  return items;
}

function renderItemSafe(container, item) {
  const article = document.createElement("article");

  const heading = document.createElement("h2");
  heading.textContent = item.title;

  const body = document.createElement("p");
  body.textContent = item.description;

  article.appendChild(heading);
  article.appendChild(body);
  container.appendChild(article);
}

async function summarizeWithClaude(items) {
  const content = items
    .slice(0, 10)
    .map((it, i) => `${i + 1}. ${it.title}: ${it.description}`)
    .join("\n");

  const message = await client.messages.create({
    model: "claude-sonnet-4-6",
    max_tokens: 1024,
    messages: [
      {
        role: "user",
        content: `Summarize the following news items in 3-5 bullet points:\n\n${content}`,
      },
    ],
  });

  return message.content[0].text;
}

async function main() {
  const allItems = [];

  for (const url of RSS_FEEDS) {
    try {
      const xml = await fetchRSSFeed(url);
      const items = parseRSSItems(xml);
      allItems.push(...items);
    } catch (err) {
      console.error(`Error fetching ${url}:`, err.message);
    }
  }

  if (allItems.length === 0) {
    console.log("No items fetched.");
    return;
  }

  const summary = await summarizeWithClaude(allItems);
  console.log("Summary:\n", summary);
}

main();
