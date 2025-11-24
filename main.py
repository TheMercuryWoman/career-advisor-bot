#add database to record previous answers and use them to get better answers from gemini


import discord
from discord.ext import commands
import json
import os
from dotenv import load_dotenv
import requests

# ------------ ENV & CONFIG ------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing from .env")

# Gemini v1 model endpoint
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"

# Load only questions.json now
with open("questions.json", "r", encoding="utf-8") as f:
    QUESTIONS = json.load(f)

# ------------ DISCORD BOT ------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# user_id → quiz state
user_states = {}


# ------------------- QUIZ START -------------------
@bot.command(name="kariyer")
async def kariyer(ctx):
    """Kariyer testini başlatır."""
    user_states[ctx.author.id] = {"index": 0, "answers": []}
    await ask_question(ctx.author, ctx.channel)


async def ask_question(user, channel):
    state = user_states[user.id]
    index = state["index"]

    if index >= len(QUESTIONS):
        await finish_quiz(user, channel)
        return

    q = QUESTIONS[index]["question"]
    await channel.send(f"{user.mention}\n📌 **Soru {index+1}: {q}**")


# ------------------- QUIZ ANSWERS -------------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Prevent commands being treated as answers
    if message.content.startswith("!"):
        await bot.process_commands(message)
        return

    await bot.process_commands(message)

    uid = message.author.id
    if uid not in user_states:
        return

    state = user_states[uid]
    state["answers"].append(message.content.strip())

    state["index"] += 1
    await ask_question(message.author, message.channel)


# ------------------- RESULT (GEMINI AI) -------------------
async def finish_quiz(user, channel):
    state = user_states.get(user.id)
    if not state:
        return

    qa_pairs = [
        {"question": QUESTIONS[i]["question"], "answer": state["answers"][i]}
        for i in range(len(QUESTIONS))
    ]

    # 🔥 NEW PROMPT — fully flexible career generation
    prompt = f"""
Aşağıda bir kullanıcının kariyer testi cevapları bulunmaktadır:

{json.dumps(qa_pairs, ensure_ascii=False, indent=2)}

Görevlerin:

1. Kullanıcının kişilik tipini, ilgi alanlarını ve güçlü yönlerini analiz et.
2. Dünya üzerindeki tüm meslekler arasından kullanıcıya EN UYGUN TEK kariyeri seç.
3. Kariyerin neden uygun olduğunu Türkçe ve detaylı açıkla.
4. Bu kariyerde başarılı olmak için gereken becerileri belirt.
5. Aşağıdaki formatta SADECE GEÇERLİ bir JSON döndür:

{{
  "career_name": "Önerilen meslek",
  "reason": "Bu meslek neden uygun?",
  "recommended_skills": ["skill1", "skill2", "skill3"]
}}
"""

    try:
        resp = requests.post(
            GEMINI_URL,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=40
        )

        if resp.status_code != 200:
            await channel.send(
                f"AI analiz hatası: HTTP {resp.status_code}\n```{resp.text[:400]}```"
            )
            user_states.pop(user.id, None)
            return

        data = resp.json()
        ai_output = data["candidates"][0]["content"]["parts"][0]["text"]

        # Extract JSON
        import re, ast
        match = re.search(r"\{(.|\n)*\}", ai_output)
        if match:
            result = ast.literal_eval(match.group())
        else:
            result = {
                "career_name": "Belirlenemedi",
                "reason": ai_output[:500],
                "recommended_skills": []
            }

    except Exception as e:
        await channel.send(f"AI analiz hatası: {e}")
        user_states.pop(user.id, None)
        return

    # ---- SEND RESULT ----
    embed = discord.Embed(
        title=f"🎯 Önerilen Kariyer: {result['career_name']}",
        description=result["reason"],
        color=discord.Color.gold()
    )

    if result.get("recommended_skills"):
        embed.add_field(
            name="Önerilen Beceriler",
            value=", ".join(result["recommended_skills"]),
            inline=False
        )

    await channel.send(embed=embed)

    user_states.pop(user.id, None)


# ------------------- STARTUP -------------------
@bot.event
async def on_ready():
    print(f"Bot giriş yaptı: {bot.user}")


bot.run(TOKEN)
