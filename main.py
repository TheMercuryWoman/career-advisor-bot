import discord
from discord.ext import commands
import json
import os
import sqlite3
from dotenv import load_dotenv
import requests

# ------------ ENV & CONFIG ------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing from .env")

# Gemini model endpoint
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"

# Load questions from JSON
with open("questions.json", "r", encoding="utf-8") as f:
    QUESTIONS = json.load(f)

# ------------ DATABASE ------------
DB = "career_data.db"


def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # Users
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Test sessions
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP
        )
    """)

    # Questions asked in each session
    c.execute("""
        CREATE TABLE IF NOT EXISTS session_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            question TEXT,
            question_order INTEGER
        )
    """)

    # Answers for each question in each session
    c.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            user_id INTEGER,
            question TEXT,
            answer TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Career result for each session
    c.execute("""
        CREATE TABLE IF NOT EXISTS career_results (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            career_name TEXT,
            reason TEXT,
            recommended_skills TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def register_user(user):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users (user_id, username)
        VALUES (?, ?)
    """, (user.id, str(user)))
    conn.commit()
    conn.close()


def create_session(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO sessions (user_id) VALUES (?)", (user_id,))
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return session_id


def save_session_questions(session_id, questions):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    for index, q in enumerate(questions):
        c.execute("""
            INSERT INTO session_questions (session_id, question, question_order)
            VALUES (?, ?, ?)
        """, (session_id, q, index))
    conn.commit()
    conn.close()


def save_answer(session_id, user_id, question, answer):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO answers (session_id, user_id, question, answer)
        VALUES (?, ?, ?, ?)
    """, (session_id, user_id, question, answer))
    conn.commit()
    conn.close()


def save_career_result(session_id, career_name, reason, skills):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO career_results (session_id, career_name, reason, recommended_skills)
        VALUES (?, ?, ?, ?)
    """, (session_id, career_name, reason, json.dumps(skills, ensure_ascii=False)))
    conn.commit()
    conn.close()


def get_all_user_answers(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT question, answer, created_at
        FROM answers
        WHERE user_id = ?
        ORDER BY created_at ASC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()

    return [{"question": q, "answer": a, "time": str(t)} for q, a, t in rows]


# ------------ DISCORD BOT ------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Stores active quiz progress per user
user_states = {}  # {user_id: {"index": int, "answers": [], "session_id": int}}


# ------------------- START QUIZ -------------------
@bot.command(name="kariyer")
async def kariyer(ctx):
    user = ctx.author
    register_user(user)

    # Create new test session
    session_id = create_session(user.id)

    # Save all questions for this session
    save_session_questions(session_id, [q["question"] for q in QUESTIONS])

    # Initialize quiz state
    user_states[user.id] = {"index": 0, "answers": [], "session_id": session_id}

    await ctx.send("🎯 Kariyer testi başladı! Soruları dürüstçe cevapla.")
    await ask_question(user, ctx.channel)


async def ask_question(user, channel):
    state = user_states.get(user.id)
    if not state:
        return

    index = state["index"]
    if index >= len(QUESTIONS):
        await finish_quiz(user, channel)
        return

    q = QUESTIONS[index]["question"]
    await channel.send(f"{user.mention}\n📌 **Soru {index + 1}: {q}**")


# ------------------- PROCESS ANSWERS -------------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Allow commands
    if message.content.startswith("!"):
        await bot.process_commands(message)
        return

    uid = message.author.id
    if uid not in user_states:
        return

    state = user_states[uid]
    index = state["index"]
    session_id = state["session_id"]

    if index >= len(QUESTIONS):
        return

    question_text = QUESTIONS[index]["question"]
    answer_text = message.content.strip()

    # Save into memory & database
    state["answers"].append(answer_text)
    save_answer(session_id, uid, question_text, answer_text)

    # Move to next question
    state["index"] += 1
    await ask_question(message.author, message.channel)


# ------------------- FINISH QUIZ (GEMINI ANALYSIS) -------------------
async def finish_quiz(user, channel):
    state = user_states.get(user.id)
    if not state:
        return

    session_id = state["session_id"]

    qa_pairs = [
        {"question": QUESTIONS[i]["question"], "answer": state["answers"][i]}
        for i in range(len(state["answers"]))
    ]

    past_answers = get_all_user_answers(user.id)

    # Gemini prompt
    prompt = f"""
Kullanıcının tüm geçmiş cevapları:
{json.dumps(past_answers, ensure_ascii=False, indent=2)}

Bu testte verdiği cevaplar:
{json.dumps(qa_pairs, ensure_ascii=False, indent=2)}

Görevlerin:
1. Kullanıcının güçlü yönlerini analiz et.
2. En uygun tek kariyeri seç.
3. JSON formatında döndür:

{{
  "career_name": "",
  "reason": "",
  "recommended_skills": []
}}
"""

    try:
        resp = requests.post(
            GEMINI_URL,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=40,
        )

        data = resp.json()
        ai_output = data["candidates"][0]["content"]["parts"][0]["text"]

        import re, ast
        match = re.search(r"\{(.|\n)*\}", ai_output)

        if match:
            result = ast.literal_eval(match.group())
        else:
            result = {"career_name": "Belirlenemedi", "reason": ai_output, "recommended_skills": []}

    except Exception as e:
        await channel.send(f"AI hata: {e}")
        return

    # Save result in DB
    save_career_result(
        session_id,
        result.get("career_name", "Belirlenemedi"),
        result.get("reason", ""),
        result.get("recommended_skills", [])
    )

    # Send to Discord
    embed = discord.Embed(
        title=f"🎯 Önerilen Kariyer: {result['career_name']}",
        description=result["reason"],
        color=discord.Color.gold(),
    )
    if result.get("recommended_skills"):
        embed.add_field(
            name="Gerekli Beceriler",
            value=", ".join(result["recommended_skills"]),
            inline=False
        )

    await channel.send(embed=embed)

    user_states.pop(user.id, None)


# ------------------- STARTUP -------------------
@bot.event
async def on_ready():
    init_db()
    print(f"Bot giriş yaptı: {bot.user}")


bot.run(TOKEN)
