// ---------- Helpers ----------
function stripHtml(html) {
  if (!html) return "";
  const div = document.createElement("div");
  div.innerHTML = html;
  return (div.textContent || div.innerText || "").trim();
}
function cleanSummary(raw) {
  let txt = stripHtml(raw || "");
  // Remove WordPress stub "The post … appeared first on …"
  txt = txt.replace(/The post.*?appeared first on.*$/i, "").trim();
  return txt.replace(/\s+/g, " ").trim();
}
function smartExcerpt(text, limit = 200) {
  if (!text) return "";
  const t = text.length <= limit ? text : text.slice(0, limit);
  if (t.length < limit) return t;
  const lastSentence = Math.max(t.lastIndexOf(". "), t.lastIndexOf("! "), t.lastIndexOf("? "));
  if (lastSentence > 50) return t.slice(0, lastSentence + 1) + " …";
  const lastSpace = t.lastIndexOf(" ");
  return (lastSpace > 0 ? t.slice(0, lastSpace) : t) + " …";
}
function signature(items) {
  try { return JSON.stringify(items.map(i => `${i.date}|${i.url}|${i.headline}`)); }
  catch { return String(Date.now()); }
}

// ---------- State ----------
let policyNewsData = [];
let filteredData = [];
let visibleCount = 8;
let lastSignature = "";

// ---------- Init ----------
document.addEventListener("DOMContentLoaded", () => {
  loadPolicyData();
  setupEventListeners();
  startAutoRefresh();
});

// ---------- Events ----------
function setupEventListeners() {
  const s = document.getElementById("searchInput");
  const more = document.getElementById("loadMoreBtn");
  if (s) s.addEventListener("input", handleSearch);
  if (more) more.addEventListener("click", handleLoadMore);
}

// ---------- Data ----------
async function fetchPolicyJSON() {
  const res = await fetch(`data/policyNews.json?ts=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

async function loadPolicyData() {
  const loading = document.getElementById("loading");
  try {
    const data = await fetchPolicyJSON();
    policyNewsData = Array.isArray(data.policyNews) ? data.policyNews : [];
  } catch (e) {
    console.warn("Could not load policyNews.json:", e.message);
    policyNewsData = [];
  }

  // Sort newest first
  policyNewsData.sort((a, b) => new Date(b.date) - new Date(a.date));

  // Remove unwanted category label if it ever appears in JSON
  policyNewsData = policyNewsData.filter(
    it => (it.category || "").toLowerCase() !== "student / education"
  );

  if (loading) loading.classList.add("hidden");

  filteredData = [...policyNewsData];
  lastSignature = signature(policyNewsData);
  renderCards();
}

// background refresh every 10 minutes
function startAutoRefresh(intervalMs = 10 * 60 * 1000) {
  setInterval(async () => {
    try {
      const data = await fetchPolicyJSON();
      const items = Array.isArray(data.policyNews) ? data.policyNews : [];
      items.sort((a, b) => new Date(b.date) - new Date(a.date));
      const sig = signature(items);
      if (sig !== lastSignature) {
        policyNewsData = items.filter(
          it => (it.category || "").toLowerCase() !== "student / education"
        );
        const q = (document.getElementById("searchInput")?.value || "").toLowerCase().trim();
        filteredData = !q
          ? [...policyNewsData]
          : policyNewsData.filter(it =>
              `${it.headline} ${it.description} ${it.category} ${it.source}`.toLowerCase().includes(q)
            );
        visibleCount = 8;
        lastSignature = sig;
        renderCards();
      }
    } catch (e) {
      console.debug("auto-refresh skipped:", e.message);
    }
  }, intervalMs);
}

// ---------- Render ----------
function createCardHTML(item) {
  const formattedDate = new Date(item.date).toLocaleDateString("en-GB", {
    day: "numeric", month: "long", year: "numeric"
  });
  const desc = smartExcerpt(cleanSummary(item.description || ""), 200);

  return `
    <article class="card" style="border:1px solid #e5e7eb;border-radius:12px;padding:24px;margin-bottom:32px;font-family:'Inter',Arial,sans-serif;">
      <span style="display:inline-block;background:#f3f4f6;color:#4b5563;padding:4px 12px;font-size:12px;font-weight:600;text-transform:uppercase;border-radius:4px;letter-spacing:0.5px;margin-bottom:12px;">
        ${item.category || "Policy Update"}
      </span>
      <h2 style="margin:0 0 16px 0;font-size:28px;font-weight:700;line-height:1.3;color:#0a1f44;">
        <a href="${item.url}" target="_blank" rel="noopener" style="color:inherit;text-decoration:none;">
          ${item.headline || ""}
        </a>
      </h2>
      <p style="margin:0 0 24px 0;font-size:16px;line-height:1.6;color:#374151;">
        ${desc}
      </p>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:0 0 16px 0;">
      <div style="display:flex;justify-content:space-between;font-size:14px;color:#6b7280;">
        <span>Source: ${item.source || ""}</span>
        <time datetime="${item.date}">${formattedDate}</time>
      </div>
    </article>
  `;
}

function renderCards() {
  const newsWrapper = document.getElementById("news-wrapper");
  const loadMoreBtn = document.getElementById("loadMoreBtn");
  const noResults = document.getElementById("no-results");
  if (!newsWrapper || !loadMoreBtn || !noResults) return;

  const itemsToShow = filteredData.slice(0, visibleCount);

  if (itemsToShow.length === 0) {
    newsWrapper.innerHTML = "";
    noResults.classList.remove("hidden");
    loadMoreBtn.classList.add("hidden");
    return;
  }

  noResults.classList.add("hidden");
  newsWrapper.innerHTML = itemsToShow.map(createCardHTML).join("");
  if (visibleCount < filteredData.length) loadMoreBtn.classList.remove("hidden");
  else loadMoreBtn.classList.add("hidden");
}

// ---------- Search & pagination ----------
function handleSearch(event) {
  const q = (event.target.value || "").toLowerCase().trim();
  filteredData = !q
    ? [...policyNewsData]
    : policyNewsData.filter(it =>
        `${it.headline} ${it.description} ${it.category} ${it.source}`.toLowerCase().includes(q)
      );
  visibleCount = 8;
  renderCards();
}
function handleLoadMore() {
  visibleCount += 8;
  renderCards();
}

