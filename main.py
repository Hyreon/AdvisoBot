import io

import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix=".", intents=intents)

@bot.event
async def on_ready():
    print('We have logged in as {0.user}'.format(bot))

@bot.command()
@commands.is_owner()
async def sync(ctx: commands.Context) -> None:
    """Sync commands"""
    synced = await ctx.bot.tree.sync()
    await ctx.send(f"Synced {len(synced)} commands globally")

@bot.tree.command(name="register", description="Registers discord users to a save file.")
@app_commands.describe(game="The game file.", players="A list of players.")
async def register(interaction: discord.Interaction, game: discord.Attachment, message: str) -> None:
    names = []
    for player in players:
        names.append(player.name)
    bytes = game.read()
    await interaction.response.send_message(f"Haha you fool! This does nothing! {names}")


@bot.tree.command(name="file-save", description="Saves any file.")
@app_commands.describe(game="The game file.")
async def file_save(interaction: discord.Interaction, game: discord.Attachment) -> None:
    try:
        await game.save(game.filename)
        await interaction.response.send_message(f"File saved as {game.filename}")
    except Exception as e:
        await interaction.response.send_message(f"Something went wrong. {e}")

# @bot.tree.command(name="file-read", description="Reads a game save file.")
# @app_commands.describe(game="The game file.")
# async def file_read(interaction: discord.Interaction, game: discord.Attachment) -> None:
#     try:
#         await game.save(game.filename)
#         await interaction.response.send_message(f"File saved as {game.filename}")
#     except Exception as e:
#         await interaction.response.send_message(f"Something went wrong. {e}")

@bot.tree.command(name="file-load", description="Loads any file.")
@app_commands.describe(game_name="The game file.")
async def file_load(interaction: discord.Interaction, game_name: str) -> None:
    file = discord.File(fp=open(game_name, "rb"), filename=game_name)

    class SingleFileView(discord.ui.LayoutView):
        file_attachment = discord.ui.File["SingleFileView"](media=file)

    view = SingleFileView()
    await interaction.response.send_message(view=view, files=[file])

@bot.tree.command(name="echo", description="Echoes a message.")
@app_commands.describe(message="The message to echo.")
async def echo(interaction: discord.Interaction, message: str) -> None:
    await interaction.response.send_message(message)

@bot.tree.command()
async def ping(inter: discord.Interaction) -> None:
    """Get the bot's latency"""
    await inter.response.send_message(f"Pong! ({round(bot.latency * 1000)}ms)")
    try:
        await inter.response.send_message(f"Trying to send a second message...")
    except discord.InteractionResponded:
        await inter.followup.send(f"Responding again failed, as expected.")

# @client.event
# async def on_message(message):
#     if message.author == client.user:
#         return
#
#     if message.content.startswith('$hello'):
#         await message.channel.send('Hello!')

bot.run(os.getenv("API_KEY"))