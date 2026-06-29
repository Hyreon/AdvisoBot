import datetime
import os
import traceback

from discord.ext import commands
import pickle

class PitbossSaveLoad(commands.Cog):
    def __init__(self, bot, backupname: str = None):
        self.bot = bot

        if backupname:
            self.load_state = self.load_backup(backupname)
        else:
            self.load_state = "No folder provided to load from. Starting from scratch"

        print(self.load_state)

    def save_backup(self, backupname: str = None) -> str:
        try:
            if backupname is None:
                backupname = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            os.mkdir(f"{backupname}")
            os.mkdir(f"{backupname}/games")
            os.mkdir(f"{backupname}/protogames")
            for channel,game in self.bot.games.items():
                with open(f"{backupname}/games/{channel}.pb", "wb") as f:
                    pickle.dump(game, f)
            for channel,protogame in self.bot.protogames.items():
                with open(f"{backupname}/protogames/{channel}.pb", "wb") as f:
                    pickle.dump(protogame, f)
            with open(f"{backupname}/config.pb", "wb") as f:
                pickle.dump(self.bot.config, f)
            self.bot.load_value = backupname
            return f"Files backed up under {backupname}"
        except Exception:
            return f"Something went wrong while making backup {backupname}, {traceback.format_exc()}"

    def load_backup(self, backupname: str) -> str:
        try:
            if not os.path.exists(backupname):
                return "Backup not found: {}".format(backupname)
            for file in os.listdir(f"{backupname}/games"):
                if file.endswith(".pb"):
                    channel_id = int(file.split(".")[0])
                    with open(f"games/{file}", "rb") as f:
                        self.bot.games[channel_id] = pickle.load(f)
            for file in os.listdir(f"{backupname}/protogames"):
                if file.endswith(".pb"):
                    channel_id = int(file.split(".")[0])
                    with open(f"protogames/{file}", "rb") as f:
                        self.bot.protogames[channel_id] = pickle.load(f)
            with open(f"{backupname}/config.pb", "rb") as f:
                self.bot.config = pickle.load(f)
            return "Loaded from backups."
        except Exception as e:
            return f"Something went wrong while loading backup {backupname}, {traceback.format_exc()}"

    @commands.command()
    @commands.is_owner()
    async def pb_backup(self, ctx: commands.Context, backupname: str = None) -> None:
        """Backup all active games and protogames"""
        print("backing up")
        await ctx.send(self.save_backup(backupname))

    @commands.command()
    @commands.is_owner()
    async def pb_load_backup(self, ctx: commands.Context, backupname: str = None) -> None:
        """Load a pitboss backup"""
        print("loading backup")
        await ctx.send(self.load_backup(backupname))


async def setup(bot: commands.Bot):
    await bot.add_cog(PitbossSaveLoad(bot, bot.load_value))