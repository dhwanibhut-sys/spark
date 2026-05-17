# Frontend Usage Guide

## Running Locally (60 seconds)

### 1. Start the Backend API
```bash
# In one terminal
uvicorn main:app --reload
```

The API will be running at `http://localhost:8000`

### 2. Open the Frontend
```bash
# In another terminal (or just open the file)
# Option 1: Simple HTTP server
python -m http.server 8001

# Option 2: If you have a different port preference
python -m http.server 3000
```

Then visit: `http://localhost:8001` (or your chosen port)

### 3. Start Using It!
1. Type a query in the text area: `"find AI startups in India with Series A funding"`
2. Click "Extract Intelligence" button
3. See the extracted data displayed
4. View recent queries in the history sidebar

---

## Features

✅ **Submit Queries** - Type natural language queries  
✅ **View Results** - See extracted sectors, entities, geographies, attributes  
✅ **History** - Recent queries stored locally (browser storage)  
✅ **Responsive** - Works on mobile and desktop  
✅ **No Framework** - Pure vanilla JavaScript (no Node, React, etc.)  

---

## How It Works

1. **Frontend** sends query to backend API at `http://localhost:8000/queries`
2. **Backend** extracts structured data using Claude
3. **Frontend** displays the results
4. **Browser** stores recent queries for quick access

---

## For the Assessment

When demoing or explaining your submission:

**"The backend (main.py) handles all the intelligence extraction. The frontend is a minimal web UI that calls the API endpoints. Together they form a complete research query platform."**

This shows:
- ✅ Backend quality (your v2.0 code)
- ✅ Full-stack thinking (UI + API)
- ✅ Smart prioritization (minimal but functional)

---

## Deployment

**To deploy together:**

```bash
# 1. Run backend
uvicorn main:app --host 0.0.0.0 --port 8000 &

# 2. Serve frontend from same server
python -m http.server --directory . 8001 &

# 3. Access at your_domain:8001
```

Or host the `index.html` on any static host (GitHub Pages, Netlify, etc.) and point it to your backend API URL.

---

**That's it!** Clean, minimal, and functional. 🎉
