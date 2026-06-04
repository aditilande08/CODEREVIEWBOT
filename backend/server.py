from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
import httpx
import re
import json
from openai import AsyncOpenAI
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from contextlib import asynccontextmanager

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

db_client = None
db = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_client, db
    try:
        db_client = AsyncIOMotorClient(MONGO_URL)
        db = db_client[DB_NAME]
        logger.info(f"Connected to MongoDB at {MONGO_URL}, database: {DB_NAME}")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
    
    yield
    
    if db_client:
        db_client.close()
        logger.info("Closed MongoDB connection")

# Create the main app without a prefix
app = FastAPI(lifespan=lifespan)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Models
class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    severity: str  # WARNING, ERROR, INFO
    problem: str
    fix: str
    why: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None

class PRReviewRequest(BaseModel):
    pr_url: str

class PRReviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    pr_number: int
    pr_title: str
    repository: str
    findings: List[ReviewFinding]
    total_files: int
    files_analyzed: int
    truncated: bool
    review_summary: str
    created_at: Optional[str] = None

# Helper function to parse GitHub PR URL
def parse_github_pr_url(url: str):
    pattern = r'https://github\.com/([^/]+)/([^/]+)/pull/(\d+)'
    match = re.match(pattern, url)
    if not match:
        raise HTTPException(status_code=400, detail="Invalid GitHub PR URL format")
    owner, repo, pr_number = match.groups()
    return owner, repo, int(pr_number)

# Fetch PR data from GitHub
async def fetch_pr_data(owner: str, repo: str, pr_number: int):
    github_token = os.environ.get('GITHUB_TOKEN')
    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    async with httpx.AsyncClient() as client:
        # Fetch PR details
        pr_response = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=headers
        )
        if pr_response.status_code != 200:
            raise HTTPException(status_code=404, detail="PR not found")
        pr_data = pr_response.json()
        
        # Fetch PR files
        files_response = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files",
            headers=headers
        )
        if files_response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch PR files")
        files_data = files_response.json()
        
        return pr_data, files_data

# Generate code review using OpenRouter (Qwen free model)
async def generate_code_review(pr_data: dict, files_data: list) -> dict:
    api_key = os.environ.get('OPENROUTER_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")
    
    # Limit files to avoid token limits
    max_files = 10
    files_to_analyze = files_data[:max_files]
    truncated = len(files_data) > max_files
    
    # Prepare code context for review
    code_context = f"""PR Title: {pr_data['title']}
PR Description: {pr_data.get('body', 'No description provided')}

Files Changed ({len(files_data)} total, analyzing {len(files_to_analyze)} files):
"""
    
    for file in files_to_analyze:
        code_context += f"\n--- File: {file['filename']} ---\n"
        code_context += f"Status: {file['status']}\n"
        code_context += f"Changes: +{file['additions']} -{file['deletions']}\n"
        if 'patch' in file:
            code_context += f"Diff:\n{file['patch']}\n"
    
    system_message = """You are a senior software engineer conducting a comprehensive code review. 
        Analyze the code changes and identify issues related to:
        - Code quality and best practices
        - Potential bugs and edge cases
        - Performance concerns
        - Security vulnerabilities
        - Maintainability and readability
        - Design patterns and architecture
        
        For each issue found, provide:
        1. Severity level: ERROR (critical issues), WARNING (should fix), or INFO (suggestions)
        2. Problem: Clear description of the issue
        3. Fix: Specific solution or code example
        4. Why: Explanation of why this matters
        
        Format your response as a JSON array of findings:
        [
          {
            "severity": "WARNING",
            "problem": "...",
            "fix": "...",
            "why": "...",
            "file_path": "...",
            "line_number": null
          }
        ]
        
        Provide a comprehensive review with at least 3-5 findings per PR if issues exist."""

    # Create OpenRouter client (OpenAI-compatible API)
    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    
    FREE_MODELS = [
        "mistralai/mistral-7b-instruct:free",
        "google/gemma-3-4b-it:free",
        "meta-llama/llama-3.2-3b-instruct:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
    ]

    last_error = None
    completion = None

    for model in FREE_MODELS:
        try:
            logger.info(f"Trying model: {model}")
            completion = await client.chat.completions.create(
                model=model,
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": f"Please review this pull request comprehensively:\n\n{code_context}"}
                ]
            )
            if completion.choices[0].message.content:
                logger.info(f"Success with model: {model}")
                break
        except Exception as e:
            logger.warning(f"Model {model} failed: {str(e)}")
            last_error = e
            continue

    if not completion or not completion.choices[0].message.content:
        raise last_error or Exception("All models failed")

    try:
        response = completion.choices[0].message.content
        
        response = completion.choices[0].message.content
        
        # Handle empty/None responses from free models
        if not response:
            return {
                "findings": [{
                    "severity": "WARNING",
                    "problem": "AI model returned an empty response",
                    "fix": "This is likely due to rate limiting on the free model. Please wait 30 seconds and try again.",
                    "why": "Free AI models have usage limits. If this persists, try a smaller PR or wait a few minutes.",
                    "file_path": None,
                    "line_number": None
                }],
                "summary": "Review could not be completed - model rate limited",
                "files_analyzed": len(files_to_analyze),
                "truncated": truncated
            }
        
        # Parse response - extract JSON from response with improved robustness
        findings_data = []
        
        # Strategy 1: Look for JSON array
        json_match = re.search(r'\[\s*\{.*\}\s*\]', response, re.DOTALL)
        if json_match:
            try:
                findings_data = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        # Strategy 2: Look for code block with JSON
        if not findings_data:
            code_block_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', response, re.DOTALL)
            if code_block_match:
                try:
                    findings_data = json.loads(code_block_match.group(1))
                except json.JSONDecodeError:
                    pass
        
        # Fallback: create findings from the text response
        if not findings_data:
            findings_data = [{
                "severity": "INFO",
                "problem": "Review completed",
                "fix": response[:500] if len(response) > 500 else response,
                "why": "AI-generated comprehensive review",
                "file_path": None,
                "line_number": None
            }]
        
        return {
            "findings": findings_data,
            "summary": f"Reviewed {len(files_to_analyze)} of {len(files_data)} files with {len(findings_data)} findings",
            "files_analyzed": len(files_to_analyze),
            "truncated": truncated
        }
    except Exception as e:
        logging.error(f"Error generating review: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate review: {str(e)}")

@api_router.get("/")
async def root():
    return {"message": "Code Review Bot API"}

@api_router.post("/review", response_model=PRReviewResponse)
async def review_pr(request: PRReviewRequest):
    try:
        # Check cache in MongoDB
        if db is not None:
            try:
                cached_review = await db.reviews.find_one({"pr_url": request.pr_url.strip()})
                if cached_review:
                    logger.info(f"Returning cached review for {request.pr_url}")
                    return PRReviewResponse(
                        id=cached_review["id"],
                        pr_number=cached_review["pr_number"],
                        pr_title=cached_review["pr_title"],
                        repository=cached_review["repository"],
                        findings=[ReviewFinding(**f) for f in cached_review["findings"]],
                        total_files=cached_review["total_files"],
                        files_analyzed=cached_review["files_analyzed"],
                        truncated=cached_review["truncated"],
                        review_summary=cached_review["review_summary"],
                        created_at=cached_review.get("created_at")
                    )
            except Exception as e:
                logger.error(f"Error checking cache: {e}")

        # Parse PR URL
        owner, repo, pr_number = parse_github_pr_url(request.pr_url)
        
        # Fetch PR data
        pr_data, files_data = await fetch_pr_data(owner, repo, pr_number)
        
        # Generate review
        review_result = await generate_code_review(pr_data, files_data)
        
        # Create findings
        findings = [
            ReviewFinding(**finding) for finding in review_result['findings']
        ]
        
        review_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()

        # Save to database
        if db is not None:
            try:
                review_doc = {
                    "id": review_id,
                    "pr_url": request.pr_url.strip(),
                    "pr_number": pr_number,
                    "pr_title": pr_data['title'],
                    "repository": f"{owner}/{repo}",
                    "findings": review_result['findings'],
                    "total_files": len(files_data),
                    "files_analyzed": review_result['files_analyzed'],
                    "truncated": review_result['truncated'],
                    "review_summary": review_result['summary'],
                    "created_at": created_at
                }
                await db.reviews.insert_one(review_doc)
                logger.info(f"Saved review {review_id} to database")
            except Exception as e:
                logger.error(f"Failed to save review to database: {e}")
        
        return PRReviewResponse(
            id=review_id,
            pr_number=pr_number,
            pr_title=pr_data['title'],
            repository=f"{owner}/{repo}",
            findings=findings,
            total_files=len(files_data),
            files_analyzed=review_result['files_analyzed'],
            truncated=review_result['truncated'],
            review_summary=review_result['summary'],
            created_at=created_at
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error reviewing PR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/history")
async def get_history():
    if db is None:
        return []
    try:
        cursor = db.reviews.find(
            {}, 
            {"_id": 0, "id": 1, "pr_url": 1, "pr_title": 1, "repository": 1, "review_summary": 1, "created_at": 1}
        ).sort("created_at", -1).limit(50)
        history = await cursor.to_list(length=50)
        return history
    except Exception as e:
        logger.error(f"Failed to fetch history: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch history")

@api_router.get("/review/{review_id}", response_model=PRReviewResponse)
async def get_review_by_id(review_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection not available")
    try:
        cached_review = await db.reviews.find_one({"id": review_id})
        if not cached_review:
            raise HTTPException(status_code=404, detail="Review not found")
        return PRReviewResponse(
            id=cached_review["id"],
            pr_number=cached_review["pr_number"],
            pr_title=cached_review["pr_title"],
            repository=cached_review["repository"],
            findings=[ReviewFinding(**f) for f in cached_review["findings"]],
            total_files=cached_review["total_files"],
            files_analyzed=cached_review["files_analyzed"],
            truncated=cached_review["truncated"],
            review_summary=cached_review["review_summary"],
            created_at=cached_review.get("created_at")
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch review: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

