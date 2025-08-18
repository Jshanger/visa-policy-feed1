// Application state
let policyNewsData = [];
let visibleCount = 8;
let filteredData = [];

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    loadPolicyData();
    setupEventListeners();
});

// Set up event listeners
function setupEventListeners() {
    const searchInput = document.getElementById('searchInput');
    const loadMoreBtn = document.getElementById('loadMoreBtn');

    searchInput.addEventListener('input', handleSearch);
    loadMoreBtn.addEventListener('click', handleLoadMore);
}

// Fetch policy news data from JSON file
async function loadPolicyData() {
    const loadingElement = document.getElementById('loading');
    const newsWrapper = document.getElementById('news-wrapper');

    try {
        // Attempt to fetch from external JSON file
        const response = await fetch('data/policyNews.json');

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        policyNewsData = data.policyNews || [];

    } catch (error) {
        console.warn('Could not load from data/policyNews.json, using fallback data:', error.message);

        // Fallback data for demo purposes
        policyNewsData = [
            {
                date: "2025-08-14",
                category: "Immigration Policy",
                headline: "China launches new K-visa for young STEM professionals",
                description: "From October 1, 2025 foreign STEM graduates from renowned universities can apply for streamlined 'young-talent' K-visas without employer sponsorship.",
                source: "South China Morning Post",
                url: "https://www.scmp.com/news/china/politics/article/3321901/china-creates-new-visa-young-science-and-technology-talent"
            },
            {
                date: "2025-07-22",
                category: "Work Visas",
                headline: "UK raises Skilled Worker and Global Mobility salary thresholds",
                description: "Certificates of Sponsorship issued from 22 July 2025 must meet new salary floors – £41,700 for Skilled Worker and £52,500 for Global Business Mobility.",
                source: "Smith Stone Walters",
                url: "https://smithstonewalters.com/news/skilled-worker-2"
            },
            {
                date: "2025-07-14",
                category: "Student Visas",
                headline: "Australia to increase student visa fee to AUD 2,000 from July 2025",
                description: "The 25% hike, confirmed by the Department of Home Affairs, is part of broader reforms to control international education volumes and ensure integrity.",
                source: "Indian Express / Reuters",
                url: "https://indianexpress.com/article/education/study-abroad/australia-student-visa-amount-increase-cost-for-uk-usa-canada-germany-france-new-immigration-rules-10116123/"
            }
        ];
    }

    // Sort by date (newest first)
    policyNewsData.sort((a, b) => new Date(b.date) - new Date(a.date));

    // Hide loading, show content
    loadingElement.classList.add('hidden');

    // Initial render
    filteredData = [...policyNewsData];
    renderCards();
}

// Create HTML for a single news card
function createCardHTML(item) {
    const formattedDate = new Date(item.date).toLocaleDateString('en-GB', {
        day: 'numeric',
        month: 'long', 
        year: 'numeric'
    });

    return `
        <article class="card" style="border:1px solid #e5e7eb;border-radius:12px;padding:24px;margin-bottom:32px;font-family:'Inter',Arial,sans-serif;">
            <span style="display:inline-block;background:#eef4ff;color:#224cc9;padding:4px 12px;font-size:12px;font-weight:600;text-transform:uppercase;border-radius:4px;letter-spacing:0.5px;margin-bottom:12px;">
                ${item.category}
            </span>
            <h2 style="margin:0 0 16px 0;font-size:28px;font-weight:700;line-height:1.3;color:#0a1f44;">
                <a href="${item.url}" target="_blank" rel="noopener" style="color:inherit;text-decoration:none;">
                    ${item.headline}
                </a>
            </h2>
            <p style="margin:0 0 24px 0;font-size:16px;line-height:1.6;color:#374151;">
                ${item.description}
            </p>
            <hr style="border:none;border-top:1px solid #e5e7eb;margin:0 0 16px 0;">
            <div style="display:flex;justify-content:space-between;font-size:14px;color:#6b7280;">
                <span>Source: ${item.source}</span>
                <time datetime="${item.date}">${formattedDate}</time>
            </div>
        </article>
    `;
}

// Render cards to the page
function renderCards() {
    const newsWrapper = document.getElementById('news-wrapper');
    const loadMoreBtn = document.getElementById('loadMoreBtn');
    const noResults = document.getElementById('no-results');

    // Show items up to visibleCount
    const itemsToShow = filteredData.slice(0, visibleCount);

    if (itemsToShow.length === 0) {
        newsWrapper.innerHTML = '';
        noResults.classList.remove('hidden');
        loadMoreBtn.classList.add('hidden');
        return;
    }

    noResults.classList.add('hidden');
    newsWrapper.innerHTML = itemsToShow.map(createCardHTML).join('');

    // Show/hide load more button
    if (visibleCount < filteredData.length) {
        loadMoreBtn.classList.remove('hidden');
    } else {
        loadMoreBtn.classList.add('hidden');
    }
}

// Handle search functionality
function handleSearch(event) {
    const query = event.target.value.toLowerCase().trim();

    if (query === '') {
        filteredData = [...policyNewsData];
    } else {
        filteredData = policyNewsData.filter(item => {
            const searchText = `${item.headline} ${item.description} ${item.category} ${item.source}`.toLowerCase();
            return searchText.includes(query);
        });
    }

    // Reset visible count and re-render
    visibleCount = 8;
    renderCards();
}

// Handle load more functionality
function handleLoadMore() {
    visibleCount += 8;
    renderCards();
}