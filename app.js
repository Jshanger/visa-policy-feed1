// ---------- Helpers ----------

// Clean excerpt to avoid cutting off mid-sentence
function smartExcerpt(text, limit = 200) {
  if (!text) return "";
  if (text.length <= limit) return text;
  const trimmed = text.slice(0, limit);
  const lastSentence = Math.max(
    trimmed.lastIndexOf(". "),
    trimmed.lastIndexOf("! "),
    trimmed.lastIndexOf("? ")
  );
  if (lastSentence > 50) return trimmed.slice(0, lastSentence + 1) + " …";
  const lastSpace = trimmed.lastIndexOf(" ");
  return (lastSpace > 0 ? trimmed.slice(0, lastSpace) : trimmed) + " …";
}

// Keywords/regexes that indicate student/study-abroad relevance
const STUDENT_TERMS = [
  /student visa/i, /international student/i, /study abroad/i,
  /graduate route|post[- ]study|PSW/i,
  /dependent[s]? visa/i, /work rights|work hours/i,
  /tuition fee[s]?/i, /scholarship[s]?/i,
  /CAS letter/i, /admission[s]?/i,
  /IELTS|TOEFL|PTE|UKVI/i,
  /SEVIS|F[- ]1|J[- ]1/i, /IRCC|USCIS|Home Affairs/i
];

function isStudentRelevant(item) {
  const bag = [
    item.headline,
    item.description,
    item.category,
    item.source
  ].filter(Boolean).join(" ");
  return STUDENT_TERMS.some(rx => rx.test(bag));
}

// ---------- App state ----------
let policyNewsData = [];
let visibleCount = 8;
let filteredData = [];

// ---------- Init ----------
document.addEventListener("DOMContentLoaded", () => {
  loadPolicyData();
  setupEventListeners();
});

// ---------- Events ----------
function setupEventListeners() {
  const searchInput = document.getElementById("searchInput");
  const loadMoreBtn = document.getElementById("loadMoreBtn");
  if (searchInput) searchInput.addEventListener("input", handleSearch);
  if (loadMoreBtn) loadMoreBtn.addEventListener("click", handleLoadMore);
}

// ---------- Data load ----------
async function fetchPolicyJSON() {
  // Try relative path first (works on Netlify root or subpaths), then absolute as a fallback.
  const bust = "?v=" + Date.now();
  const candidates = ["./data/policyNews.json" + bust, "/data/policyNews.json" + bust];

  for (const url of candidates) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (res.ok) return await res.json();
      // If 404 on first candidate, try next one
    } catch (_) {
      // ignore and try next candidate
    }
  }
  throw new Error("Unable to load policyNews.json from ./data/ or /data/");
}

async function loadPolicyData() {
  const loadingElement = document.getElementById("loading");
  const statusEl = document.getElementById("status");

  try {
    const data = await fetchPolicyJSON();
    policyNewsData = Array.isArray(data.policyNews) ? data.policyNews : [];
    if (statusEl) statusEl.textContent = `Loaded ${policyNewsData.length} items`;
  } catch (error) {
    console.warn("Could not load data/policyNews.json, using fallback data:", error.message);
    if (statusEl) statusEl.textContent = "Using fallback sample data (feed not found)";
    // Fallback demo items (optional)
    policyNewsData = [
      {
        date: "2025-08-14",
        category: "Immigration Policy",
        headline: "China launches new K-visa for young STEM professionals",
        description:
          "From October 1, 2025 foreign STEM graduates from renowned universities can apply for streamlined 'young-talent' K-visas without employer sponsorship.",
        source: "South China Morning Post",
        url: "https://www.scmp.com/news/china/politics/article/3321901/china-creates-new-visa-young-science-and-technology-talent"
      },
      {
        date: "2025-07-22",
        category: "Work Visas",
        headline: "UK raises Skilled Worker and Global Mobility salary thresholds",
        description:
          "Certificates of Sponsorship issued from 22 July 2025 must meet new salary floors – £41,700 for Skilled Worker and £52,500 for Global Business Mobility.",
        source: "Smith Stone Walters",
        url: "https://smithstonewalters.com/news/skilled-worker-2"
      },
      {
        date: "2025-07-14",
        category: "Student Visas",
        headline: "Australia to increase student visa fee to AUD 2,000 from July 2025",
        description:
          "The 25% hike, confirmed by the Department of Home Affairs, is part of broader reforms to control international education volumes and ensure integrity.",
        source: "Indian Express / Reuters",
        url: "https://indianexpress.com/article/education/study-abroad/australia-student-visa-amount-increase-cost-for-uk-usa-canada-germany-france-new-immigration-rules-10116123/"
      }
    ];
  }

  // Sort newest first
  policyNewsData.sort((a, b) => new Date(b.date) - new Date(a.date));

  // Hide loading
  if (loadingElement) loadingElement.classList.add("hidden");

  // Default view = student-focused items
  filteredData = policyNewsData.filter(isStudentRelevant);
  if (filteredData.length === 0) filteredData = [...policyNewsData]; // fallback if none match
  renderCards();
}

// ---------- Card render ----------
function createCardHTML(item) {
  const formattedDate = new Date(item.date).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });

  return `
    <article class="card" style="border:1px solid #e5e7eb;border-radius:12px;padding:24px;margin-bottom:32px;font-family:'Inter',Arial,sans-serif;">
      <span style="display:inline-block;background:#eef4ff;color:#224cc9;padding:4px 12px;font-size:12px;font-weight:600;text-transform:uppercase;border-radius:4px;letter-spacing:0.5px;margin-bottom:12px;">
        ${item.category || ""}
      </span>
      <h2 style="margin:0 0 16px 0;font-size:28px;font-weight:700;line-height:1.3;color:#0a1f44;">
        <a href="${item.url}" target="_blank" rel="noopener" style="color:inherit;text-decoration:none;">
          ${item.headline || ""}
        </a>
      </h2>
      <p style="margin:0 0 24px 0;font-size:16px;line-height:1.6;color:#374151;">
        ${smartExcerpt(item.description || "", 200)}
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

  const itemsToShow = filteredData.slice(0, visibleCount);

  if (!newsWrapper || !loadMoreBtn || !noResults) return;

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
  const query = (event.target.value || "").toLowerCase().trim();

  if (!query) {
    // When empty, show student-focused items by default
    filteredData = policyNewsData.filter(isStudentRelevant);
    if (filteredData.length === 0) filteredData = [...policyNewsData];
  } else {
    filteredData = policyNewsData.filter(item => {
      const bag = `${item.headline || ""} ${item.description || ""} ${item.category || ""} ${item.source || ""}`.toLowerCase();
      return bag.includes(query);
    });
  }

  visibleCount = 8;
  renderCards();
}

function handleLoadMore() {
  visibleCount += 8;
  renderCards();
}

