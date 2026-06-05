# AI-Powered Code Review Bot

An automated tool designed to perform comprehensive code reviews on GitHub Pull Requests. It integrates a **FastAPI backend** (using the Anthropic Claude API) and a **React frontend** to fetch, analyze, and present code quality reviews, potential bugs, security issues, and performance optimizations.

---

## 🚀 Features

- **GitHub PR URL Parsing:** Simply paste any public GitHub Pull Request link (e.g., `https://github.com/owner/repo/pull/123`).
- **AI-Driven Code Review:** Analyzes the differences (diffs) of the changes using Claude models.
- **Categorized Findings:** Automatically categorizes issues into:
  - 🛑 **ERROR:** Critical issues and bugs that must be fixed.
  - ⚠️ **WARNING:** Standard issues, design pattern improvements, or code smells.
  - ℹ️ **INFO:** Suggestions and general comments.
- **Actionable Fixes:** Provides precise descriptions of the problems, side-by-side comparison fixes, and explanation of why the change matters.
- **Sleek UI:** Interactive and responsive interface built with Tailwind CSS/Vanilla utility styling and Phosphor Icons.

---

## 📁 Project Structure

```text
code-review-bot/
├── app/
│   ├── backend/
│   │   ├── server.py          # FastAPI application & Anthropic/GitHub API integration
│   │   ├── requirements.txt   # Python dependencies
│   │   └── .env               # Backend environment variables configuration
│   └── frontend/
│       ├── src/
│       │   └── App.js         # React main page structure and Axios request logic
│       └── ...
└── README.md                  # Project documentation (this file)
```

---

## 🛠️ Prerequisites

Before you start, make sure you have:
1. **Python 3.9+** installed.
2. **Node.js 16+** and **npm** installed.
3. An **Anthropic API Key** (for Claude).
4. *(Optional)* A **GitHub Token** (to avoid rate limits on public repositories).

---

## 🔧 Getting Started

### 1. Backend Setup

1. Navigate to the backend directory:
   ```bash
   cd app/backend
   ```

2. Create a virtual environment and activate it:
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure your `.env` file in `app/backend/` with the following variables:
   ```env
   ANTHROPIC_API_KEY=your_anthropic_api_key_here
   GITHUB_TOKEN=your_optional_github_token_here
   CORS_ORIGINS=*
   ```

5. Run the FastAPI development server:
   ```bash
   uvicorn server:app --reload --port 8000
   ```
   *The backend will be running at `http://localhost:8000`.*

---

### 2. Frontend Setup

1. Navigate to the frontend directory:
   ```bash
   cd app/frontend
   ```

2. Install the frontend dependencies:
   ```bash
   npm install
   ```

3. Configure the frontend environment variable. Create a `.env` file in `app/frontend/` or set it in your environment:
   ```env
   REACT_APP_BACKEND_URL=http://localhost:8000
   ```

4. Start the React development server:
   ```bash
   npm start
   ```
   *The frontend will open in your default browser at `http://localhost:3000`.*

---

## 💡 Usage

1. Open the application at `http://localhost:3000`.
2. Enter a GitHub Pull Request URL into the input field (e.g., `https://github.com/expressjs/express/pull/6098`).
3. Click **Analyze PR**.
4. The AI will retrieve the diffs, process them, and display findings categorized by severity.
