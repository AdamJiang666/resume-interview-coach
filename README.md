---
title: Resume Interview Coach Gradio
emoji: 🦀
colorFrom: purple
colorTo: red
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
pinned: false
license: apache-2.0
---
🧠 Resume Interview Coach

Upload your resume PDF(s) and practice personalized interview questions — one at a time — with instant AI feedback and scoring.

🚀 Features

📄 PDF parsing with pdfplumber to extract resume text

🤖 Question generation using OpenAI GPT-4o-mini

🗣️ Real-time answer critique with feedback, 1–5 rating, and sample “strong answer”

💾 Export your entire practice transcript as JSON

🧩 How to Use

Upload one or more resume PDFs.

Click “Generate Interview Question” to build your personalized question bank.

Click “Next question” to receive one question at a time.

Type your answer and click “Submit answer for critique.”

View feedback, rating, and a sample strong answer.

Optionally export the full session transcript.

⚙️ Technical Details

Built with Gradio

Uses OpenAI GPT-4o-mini (or GPT-4.1-mini if available) via API key stored in Space secrets

Lightweight backend: no database, no external storage

Runs entirely within the Hugging Face Space

🧰 Requirements
gradio>=4.44
openai>=1.40
pdfplumber>=0.11
jinja2>=3.1
tqdm>=4.66

🔑 Setup (for your own fork)

Go to Settings → Variables and secrets.

Add a secret:

Key: OPENAI_API_KEY

Value: your API key

Rebuild the Space.
Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference
