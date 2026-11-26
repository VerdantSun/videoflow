# Videoflow

Paste a YouTube link and watch it run as a workflow: transcript, summary, then a chat that answers from what was said.
Stack: FastAPI, vanilla HTML/CSS/JS, Groq free tier. No paid services.

## Run locally
```bash
pip install -r requirements.txt
export GROQ_API_KEY="your-key"      # PowerShell: $env:GROQ_API_KEY="your-key"
uvicorn main:app --reload
```
Open http://127.0.0.1:8000

## Deploy free on Render
Push to GitHub, then Render -> New -> Blueprint (it reads `render.yaml`). Add `GROQ_API_KEY` when asked.
