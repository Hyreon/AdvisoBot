import sys

import discord
from discord.ext import commands
import os

from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix=".", intents=intents)

bot.config = {}
bot.config["holidays"] = False  # holidays
bot.games = {}  # map of channels to pitboss entities
bot.protogames = {}  # map of channels to string lists (usernames)

if len(sys.argv) > 1:
    bot.load_value = sys.argv[1]
else:
    bot.load_value = None

modules = [
    "pb_commands",
    "pb_pickle",
]

@bot.command()
@commands.is_owner()
async def sync(ctx: commands.Context) -> None:
    """Sync commands"""
    synced = await ctx.bot.tree.sync()
    await ctx.send(f"Synced {len(synced)} commands globally")

@bot.command()
@commands.is_owner()
async def reload_modules(ctx: commands.Context) -> None:
    """Reload modules"""
    for module in modules:
        await bot.reload_extension(module)
    await ctx.send(f"Modules reloaded")

@bot.command()
@commands.is_owner()
async def unload_modules(ctx: commands.Context) -> None:
    """Reload modules"""
    for module in modules:
        await bot.unload_extension(module)
    await ctx.send(f"Modules unloaded")

@bot.command()
@commands.is_owner()
async def load_modules(ctx: commands.Context) -> None:
    """Reload modules"""
    for module in modules:
        await bot.load_extension(module)
    await ctx.send(f"Modules loaded")


@bot.event
async def on_ready():
    print('We have logged in as {0.user}'.format(bot))
    synced = await bot.tree.sync()
    print('Synced {0} commands'.format(len(synced)))

async def main():
    async with bot:
        for module in modules:
            await bot.load_extension(module)
        await bot.start(os.getenv("API_KEY"))

import asyncio
asyncio.run(main())

# @client.event
# async def on_message(message):
#     if message.author == client.user:
#         return
#
#     if message.content.startswith('$hello'):
#         await message.channel.send('Hello!')