import os, io, re, json, time, random, pathlib, tempfile
import pdfplumber
import gradio as gr
from openai import OpenAI

# ------------------ Models ------------------
MODEL_QGEN = os.getenv("MODEL_QGEN", "gpt-4o-mini")   # or "gpt-4.1-mini" if enabled
MODEL_CRIT = os.getenv("MODEL_CRIT", "gpt-4o-mini")

# ------------------ OpenAI Client ------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY. Set it in your Space (Settings → Variables and secrets).")
client = OpenAI(api_key=OPENAI_API_KEY)

# ------------------ Section splitter ------------------
HEADERS = [
    ("summary", r"\b(summary|professional summary|profile)\b"),
    ("education", r"\b(education|academics|academic background)\b"),
    ("experience", r"\b(experience|work experience|professional experience|employment)\b"),
    ("projects", r"\b(projects|selected projects|research)\b"),
    ("skills", r"\b(skills|technical skills|core skills)\b"),
    ("certifications", r"\b(certifications|licenses)\b")
]

def clean_text(t: str) -> str:
    t = re.sub(r"\r", "\n", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def split_sections(text: str) -> dict:
    t = clean_text(text)
    found = []
    for key, pat in HEADERS:
        m = re.search(rf"(^|\n)\s*{pat}\s*:?\s*($|\n)", t, flags=re.I)
        if m:
            found.append((m.start(), key))
    if not found:
        return {"summary": t}
    found.sort()
    sections = {}
    for i, (start, key) in enumerate(found):
        end = found[i+1][0] if i+1 < len(found) else len(t)
        sections[key] = t[start:end].strip()
    if "experience" not in sections and len(t) > 800:
        sections.setdefault("experience", t[:1500])
    return sections

# ------------------ Prompts ------------------
SYSTEM_QGEN = (
  "You are an expert interviewer. Generate questions that are specific to the candidate's resume "
  "section text. Do NOT include answers. Return JSON with key 'questions'."
)

USER_QGEN_TMPL = """SECTION: {section}

TEXT
-----
{section_text}

TASK
Generate {k} interview questions grounded ONLY in TEXT. Mix behavioral and technical when relevant.
Return JSON:
{{"questions": ["Q1","Q2", ...]}}
"""

SYSTEM_CRIT = "You are a precise interview coach. Provide constructive feedback and a numeric rating."

USER_CRIT_TMPL = """RESUME SECTION (context)
--------------------------
{section}

QUESTION
--------
{question}

CANDIDATE ANSWER
----------------
{answer}

TASK
1) Give brief, actionable feedback (max 6 bullet points).
2) Give a 1–5 rating using this rubric:
   5=exceptional (specific impact, metrics, clear structure),
   4=strong (clear, mostly specific, minor gaps),
   3=acceptable (some specifics, needs structure/clarity),
   2=weak (vague, missing key details),
   1=poor (off-topic or no evidence).
3) Provide a concise “strong sample answer” that would likely score 5.

Return JSON with keys: feedback (list[str]), rating (int 1-5), sample_answer (str).
"""

# ------------------ Core helpers ------------------
def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    text_pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            content = page.extract_text() or ""
            text_pages.append(content)
    return "\n".join(text_pages).strip()

def build_bank_from_text(text: str) -> list:
    sections = split_sections(text)
    bank = []
    k_map = {"experience": 5, "projects": 5, "skills": 4, "education": 3, "summary": 2, "certifications": 2}
    for sec, body in sections.items():
        if not body or len(body) < 120:
            continue
        k = k_map.get(sec, 2)
        user_prompt = USER_QGEN_TMPL.format(section=sec, section_text=body[:3000], k=k)
        try:
            r = client.chat.completions.create(
                model=MODEL_QGEN,
                response_format={"type": "json_object"},
                messages=[{"role":"system","content":SYSTEM_QGEN},
                          {"role":"user","content":user_prompt}],
                temperature=0.3
            )
            try:
                data = json.loads(r.choices[0].message.content)
            except Exception:
                # fallback if model returns non-strict JSON
                raw = r.choices[0].message.content
                data = {"questions": []}
                for line in raw.splitlines():
                    s = line.strip("-• ").strip()
                    if len(s) > 4:
                        data["questions"].append(s)
            qs = data.get("questions", [])
            for q in qs:
                bank.append({"section": sec, "question": q})
        except Exception as e:
            bank.append({"section": "system", "question": f"[Error creating questions for {sec}: {e}]"})
    random.shuffle(bank)
    return bank

# ------------------ Gradio logic ------------------
def start_session(files):
    """Upload PDFs → build bank (not shown) → ready to ask one-by-one."""
    if not files:
        return "⚠️ Please upload 1+ PDF resumes.", {"bank": [], "asked": set(), "current": None, "transcript": []}

    texts = []
    for f in files:
        if not f.name.lower().endswith(".pdf"):
            continue
        with open(f.name, "rb") as fh:
            texts.append(extract_text_from_pdf_bytes(fh.read()))

    if not texts:
        return "⚠️ No valid PDFs detected.", {"bank": [], "asked": set(), "current": None, "transcript": []}

    combined = "\n\n" + ("\n\n" + ("-"*80) + "\n\n").join(texts)
    bank = build_bank_from_text(combined)
    state = {"bank": bank, "asked": set(), "current": None, "transcript": []}
    return f"✅ Question bank built: **{len(bank)}** questions. Click **Next question** to begin.", state

def next_question(state):
    bank = state.get("bank", [])
    asked = state.get("asked", set())
    candidates = [i for i in range(len(bank)) if i not in asked]
    if not candidates:
        state["current"] = None
        return "🎉 All questions completed. You can export the transcript.", state
    idx = random.choice(candidates)
    state["asked"].add(idx)       # ensure no repeats
    state["current"] = idx
    q = bank[idx]
    return f"**Question ({q['section']}):** {q['question']}", state

def submit_answer(state, answer):
    idx = state.get("current")
    bank = state.get("bank", [])
    if idx is None or idx >= len(bank):
        return "⚠️ Click ‘Next question’ first.", state
    answer = (answer or "").strip()
    if not answer:
        return "⚠️ Type an answer before submitting.", state

    qitem = bank[idx]
    question = qitem["question"]
    section  = qitem["section"]
    user_prompt = USER_CRIT_TMPL.format(section=section, question=question, answer=answer)

    try:
        r = client.chat.completions.create(
            model=MODEL_CRIT,
            response_format={"type":"json_object"},
            messages=[{"role":"system","content":SYSTEM_CRIT},
                      {"role":"user","content":user_prompt}],
            temperature=0.2
        )
        try:
            data = json.loads(r.choices[0].message.content)
        except Exception:
            data = {"feedback": ["(Model returned non-JSON; retry)"], "rating": 0, "sample_answer": ""}

        feedback = data.get("feedback", [])
        rating   = int(data.get("rating", 0))
        sample   = data.get("sample_answer", "")

        state["transcript"].append({
            "ts": time.time(),
            "section": section,
            "question": question,
            "answer": answer,
            "feedback": feedback,
            "rating": rating,
            "sample_answer": sample
        })

        fb_lines = "\n".join([f"- {f}" for f in feedback]) if feedback else "(no feedback)"
        msg = f"**⭐ Rating:** {rating}/5\n\n**Feedback**\n{fb_lines}\n\n**Sample strong answer**\n{sample}"
        return msg, state
    except Exception as e:
        return f"❌ API error: {e}", state

def export_session(state):
    tr = state.get("transcript", [])
    if not tr:
        return None, "⚠️ No transcript yet."
    fp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    with open(fp.name, "w", encoding="utf-8") as f:
        json.dump({"transcript": tr}, f, ensure_ascii=False, indent=2)
    return fp.name, "📁 Export ready."

# ------------------ UI ------------------
with gr.Blocks(title="Resume Interview Coach") as demo:
    gr.Markdown("# 🧠 Resume Interview Coach\nUpload resume PDF(s), then practice one question at a time with AI feedback.")

    files = gr.File(label="Upload 1+ resume PDFs", file_count="multiple", file_types=[".pdf"])
    build_btn = gr.Button("Generate Interview Question", variant="primary")
    status_md = gr.Markdown()

    gr.Markdown("### Practice question)")
    next_btn = gr.Button("Next question ▶️")
    q_md = gr.Markdown("*(no question yet)*")

    answer_tb = gr.Textbox(label="Your answer", lines=6, placeholder="Type here...")
    submit_btn = gr.Button("Submit answer for critique ✅", variant="primary")
    feedback_md = gr.Markdown()

    export_btn = gr.Button("Export transcript (JSON)")
    export_file = gr.File(label="Download", interactive=False)
    export_status = gr.Markdown()

    state = gr.State({"bank": [], "asked": set(), "current": None, "transcript": []})

    build_btn.click(start_session, inputs=[files], outputs=[status_md, state])
    next_btn.click(next_question, inputs=[state], outputs=[q_md, state])
    submit_btn.click(submit_answer, inputs=[state, answer_tb], outputs=[feedback_md, state])
    export_btn.click(export_session, inputs=[state], outputs=[export_file, export_status])

demo.launch()

