import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Load database
with open("careers.json", "r", encoding="utf-8") as f:
    CAREERS = json.load(f)

# Set up bot
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# --------------- VIEWS ---------------
class CareerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
        # Dynamically create the category dropdown based on careers.json
        categories = sorted(set(c["category"] for c in CAREERS))
        
        select = discord.ui.Select(
            placeholder="Bir kategori seç...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=category,
                    description=f"{category} alanındaki kariyerleri görüntüle"
                )
                for category in categories
            ]
        )

        async def select_callback(interaction: discord.Interaction):
            category = select.values[0]
            results = [c for c in CAREERS if c["category"] == category]
            if not results:
                await interaction.response.send_message("Bu kategoride henüz öneri yok.", ephemeral=True)
                return

            embeds = []
            for career in results:
                embed = discord.Embed(
                    title=f"💼 {career['name']}",
                    description=career["description"],
                    color=discord.Color.green()
                )
                embed.add_field(name="Beceriler", value=", ".join(career["skills"]), inline=False)
                embed.add_field(name="Kategori", value=career["category"], inline=True)
                embeds.append(embed)

            await interaction.response.send_message(embeds=embeds, ephemeral=True)

        select.callback = select_callback
        self.add_item(select)

# --------------- COMMANDS ---------------
@bot.command(name="kariyer")
async def kariyer(ctx):
    embed = discord.Embed(
        title="🎯 Kariyer Keşif Botu",
        description="Hangi alanda kariyer yollarını keşfetmek istersin?",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=CareerView())

# --------------- STARTUP ---------------
@bot.event
async def on_ready():
    print(f"✅ {bot.user} olarak giriş yapıldı.")
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} komut senkronize edildi.")
    except Exception as e:
        print(f"Hata: {e}")

bot.run(TOKEN)
