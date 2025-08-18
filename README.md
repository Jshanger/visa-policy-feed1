# Auto-Updating Visa Policy News Feed

A lightweight, auto-updating news feed for immigration and visa policy changes across global destinations.

## Features

- 📱 Responsive design matching your template specifications
- 🔍 Real-time search functionality
- ♾️ Infinite scroll with "Load More" 
- 🔄 Daily automatic updates via scheduled script
- 📊 Clean, card-based layout

## Setup Instructions

### 1. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Test the Update Script

```bash
python update_policy_news.py
```

This will create/update `data/policyNews.json` with the latest policy news.

### 3. Serve the Site

```bash
# Simple Python server
python -m http.server 8000

# Or use any web server (Apache, Nginx, etc.)
```

Visit `http://localhost:8000` to see your feed.

### 4. Schedule Daily Updates

**Option A: Cron Job (Linux/Mac)**
```bash
# Edit crontab
crontab -e

# Add this line to run daily at 3 AM
0 3 * * * /path/to/your/venv/bin/python /path/to/update_policy_news.py
```

**Option B: GitHub Actions**
Create `.github/workflows/update-feed.yml`:
```yaml
name: Update Policy Feed
on:
  schedule:
    - cron: '0 3 * * *'  # Daily at 3 AM UTC
jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Update feed
        run: python update_policy_news.py
      - name: Commit changes
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add data/policyNews.json
          git commit -m "Update policy news feed" || exit 0
          git push
```

**Option C: AWS Lambda + EventBridge**
Upload the script as a Lambda function and trigger with EventBridge on a schedule.

## File Structure

```
visa-policy-feed/
├── index.html              # Main page
├── app.js                  # Frontend JavaScript  
├── update_policy_news.py   # Update script
├── requirements.txt        # Python dependencies
├── data/
│   └── policyNews.json    # News data (auto-generated)
└── README.md              # This file
```

## Customization

### Adding News Sources
Edit `FEEDS` in `update_policy_news.py`:
```python
FEEDS = [
    "https://example.gov/news.rss",
    "https://another-source.com/feed.xml",
    # Add more RSS/Atom feeds
]
```

### Adjusting Keywords
Modify `KEYWORDS` tuple to focus on specific policy types:
```python
KEYWORDS = (
    "visa", "immigration", "border", 
    "student pass", "work permit",
    # Add your keywords
)
```

### Styling
The cards use inline styles matching your template. Modify the `createCardHTML()` function in `app.js` to adjust appearance.

## How Auto-Updates Work

1. **Scheduled Script**: `update_policy_news.py` runs on schedule
2. **Data Fetch**: Pulls from RSS feeds of immigration authorities  
3. **Content Filter**: Keeps only visa/immigration-related items
4. **JSON Update**: Overwrites `data/policyNews.json`
5. **Frontend Refresh**: Next page load shows updated content

No server restarts or redeployments needed!

## Troubleshooting

**Feed not updating?**
- Check that `data/policyNews.json` was created
- Verify RSS feeds are accessible
- Check Python script logs for errors

**Cards not showing?**
- Open browser dev tools, check for JavaScript errors
- Verify JSON file exists and is valid
- Check network tab for failed requests

**Search not working?**
- Clear browser cache
- Check that all news items have required fields
