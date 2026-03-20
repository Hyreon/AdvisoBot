import asyncio
import datetime
import io
import traceback
from time import sleep

import discord
from discord import app_commands
from discord.ext import commands

from pythonnet import load
load("coreclr")  # or "netfx" for .NET Framework — must be called before import clr

import clr
ref = clr.AddReference("Civ3Tools")
from Civ3Tools import PitBossOrganizer


class DurationConverter(app_commands.Transformer):
    async def transform(self, inter: discord.Interaction, argument: str) -> datetime.timedelta:
        multipliers = {
            's': 1,  # seconds
            'm': 60,  # minutes
            'h': 3600,  # hours
            'd': 86400,  # days
            'w': 604800  # weeks
        }

        try:
            amount = int(argument[:-1])
            unit = argument[-1]
            seconds = amount * multipliers[unit]
            delta = datetime.timedelta(seconds=seconds)
            return delta
        except (ValueError, KeyError):
            raise commands.BadArgument("Invalid duration provided.")


def make_pitboss(file_bytes, names):
    pitboss = PitBossOrganizer(file_bytes, names)
    pitboss.auto_expire = None
    # pitboss.auto_advance = None
    pitboss.expire_task = None
    return pitboss


def current_player(pitboss: PitBossOrganizer):
    index = pitboss.get_CurrentPlayer()
    players = list(pitboss.get_HumanPlayers())
    if index >= len(players):
        return "dummy"
    if index < 0:
        return None
    return players[index]


def get_turn_name(pitboss: PitBossOrganizer, channel_name: str) -> str:
    return f"{channel_name}-{pitboss.get_CurrentTurn()}-{current_player(pitboss)}.SAV"


def get_claim_label(pitboss: PitBossOrganizer):
    if pitboss.auto_expire:
        timestamp = datetime.datetime.now() + pitboss.auto_expire
        auto_expire_dt = discord.utils.format_dt(timestamp, "f")
        return f"{current_player(pitboss)} is taking the turn! This claim will expire if not submitted by {auto_expire_dt}."
    else:
        return f"{current_player(pitboss)} is taking the turn!"

def unlock_save(pitboss: PitBossOrganizer):
    pitboss.ForceUnlock()
    pitboss.expire_task.cancel()
    pitboss.expire_task = None

async def auto_expire_with_notification(pitboss: PitBossOrganizer, user: discord.User, interaction: discord.Interaction):
    print(f"Scheduled auto expiry in ${pitboss.auto_expire}")
    await asyncio.sleep(pitboss.auto_expire.seconds)
    print("Attempted auto expiry")
    channel = interaction.channel
    if user:
        await user.send(f"Your turn in <#{channel.id}> has expired. You are free to take it again.")
    await interaction.followup.send("This turn has expired. Another one can be taken.")
    print(channel)
    unlock_save(pitboss)


async def update_pitboss(pitboss, protogame):
    if pitboss:
        existing_players = pitboss.get_HumanPlayers()
        if len(existing_players) == len(protogame):
            pitboss.ChangePlayerOrder(protogame)
        else:
            protogame = existing_players
            return f"Can't join new slots in an ongoing game. Players so far: {protogame}"
    return f"Updated registry. Players so far: {protogame}"


class PitBossCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def claim_for(self, interaction: discord.Interaction, user: discord.User = None):
        username = None
        if user:
            username = user.name
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            try:
                await interaction.response.defer()
                if username:
                    game = bytes(pitboss.GetConfiguredTurn(username))
                else:
                    game = bytes(pitboss.GetDummyTurn())
                file = discord.File(fp=io.BytesIO(game), filename=get_turn_name(pitboss, interaction.channel.name))

                if pitboss.auto_expire:
                    pitboss.expire_task = asyncio.create_task(
                        auto_expire_with_notification(pitboss, user, interaction))
                label = get_claim_label(pitboss)

                await interaction.followup.send(label, files=[file])
            except Exception as e:
                await interaction.followup.send(f"Something went wrong. {e}")
                print(traceback.format_exc())

    # FIXME adding other players ADMIN ONLY
    # swapping is a bit suspicious, there's got to be some safeties against it, but for now is fine
    # actually so is joining in whatever slot you like, you can boot someone out of the game that way
    @app_commands.command(name="pb-register", description="Sign up for a PitBoss game on this channel.")
    @app_commands.describe(slot="The desired player slot.", player="The player you're adding (leave blank for yourself)")
    async def register(self, interaction: discord.Interaction, slot: int = 0, player: discord.User = None) -> None:
        slot -= 1  # 1 indexed to 0 indexed
        value = interaction.user.name
        if player:
            value = player.name
        if not self.bot.protogames.get(interaction.channel_id):
            self.bot.protogames[interaction.channel_id] = []
        protogame = self.bot.protogames[interaction.channel_id]
        pitboss = self.bot.games.get(interaction.channel_id)
        if player in protogame:
            if slot < 0:
                await interaction.response.send_message(
                    f"You're already here! Players so far: {protogame}")
                return
            elif slot < len(protogame):  # swap slot mode
                other_slot = protogame.index(value)
                protogame[slot], protogame[other_slot] = protogame[other_slot], protogame[slot]
                if not pitboss:
                    while len(protogame) > 0 and not protogame[-1]:
                        protogame.pop()
                await interaction.response.send_message(await update_pitboss(pitboss, protogame))
                return
            else:  # player still needs to be removed before adding the new slots
                other_slot = protogame.index(value)
                protogame[other_slot] = None
        while len(protogame) <= slot:
            protogame.append(None)
        print(protogame)
        if slot < 0 or len(protogame) < slot:
            protogame.append(value)
        else:
            protogame[slot] = value
        await interaction.response.send_message(await update_pitboss(pitboss, protogame))

    # FIXME removing other players ADMIN ONLY
    @app_commands.command(name="pb-leave", description="Exit the PitBoss game on this channel.")
    @app_commands.describe(player="The player that's leaving (leave blank for yourself)")
    async def leave(self, interaction: discord.Interaction, player: discord.User = None) -> None:
        value = interaction.user.name
        if player:
            value = player.name
        if not self.bot.protogames.get(interaction.channel_id):
            self.bot.protogames[interaction.channel_id] = []
        protogame = self.bot.protogames[interaction.channel_id]
        found = False
        for i,name in enumerate(protogame):
            if name == value:
                found = True
                protogame[i] = None
                break
        pitboss = self.bot.games.get(interaction.channel_id)
        if pitboss:
            pitboss.ChangePlayerOrder(protogame)
        else:
            while len(protogame) > 0 and not protogame[-1]:
                protogame.pop()
        if found:
            await interaction.response.send_message(f"Updated registry. Players so far: {protogame}")
        else:
            await interaction.response.send_message(f"You aren't in this game. Players so far: {protogame}")

    @app_commands.command(name="pb-create", description="Create a new PitBoss server from a game file.")
    @app_commands.describe(game="The game file.")
    async def create(self, interaction: discord.Interaction, game: discord.Attachment) -> None:
        if not self.bot.protogames.get(interaction.channel_id):
            await interaction.response.send_message(f"No players have signed up yet!")
        else:
            protogame = self.bot.protogames[interaction.channel_id]
            file_bytes = await game.read()
            pitboss = make_pitboss(file_bytes, protogame)
            self.bot.games[interaction.channel_id] = pitboss
            await interaction.response.send_message(f"Made the pitboss game!! Plays: {list(pitboss.get_TurnTaken())}")

    #FIXME special permissions needed, not sure what
    @app_commands.command(name="pb-next-turn", description="Take the dummy turn")
    @app_commands.describe()
    async def next_turn(self, interaction: discord.Interaction):
        await self.claim_for(interaction)

    @app_commands.command(name="pb-toggle-stick-the-dealer", description="Toggle whether the last player is a dummy or a player that has to go last")
    @app_commands.describe()
    async def toggle_stick_the_dealer(self, interaction: discord.Interaction):
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            if pitboss.ToggleLastPlayerHuman():
                await interaction.response.send_message("The last player is now a **human** player")
            else:
                await interaction.response.send_message("The last player is now a **dummy** player")

    @app_commands.command(name="pb-take", description="Get the save file to take your turn!")
    async def take(self, interaction: discord.Interaction) -> None:
        await self.claim_for(interaction, interaction.user)


    #FIXME ADMIN ONLY
    @app_commands.command(name="pb-give", description="Get the save file for someone else's turn!")
    async def give(self, interaction: discord.Interaction, player: discord.User) -> None:
        await self.claim_for(interaction, player)


    @app_commands.command(name="pb-submit", description="Submit your save file.")
    @app_commands.describe(game="The game file.")
    async def submit(self, interaction: discord.Interaction, game: discord.Attachment) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            await interaction.response.defer()
            try:
                if pitboss.get_CurrentPlayer() == len(pitboss.get_HumanPlayers()):
                    pitboss.ReceiveDummyTurn(await game.read())
                else:
                    pitboss.ReceiveNewTurn(await game.read())
                task = pitboss.expire_task
                if task:
                    task.cancel()
                await interaction.followup.send(f"Save submitted.")
            except Exception as e:
                await interaction.followup.send(f"Something went wrong. {e}")
                print(traceback.format_exc())


    @app_commands.command(name="pb-status", description="Get the status of the PBE in this channel.")
    @app_commands.describe()
    async def status(self, interaction: discord.Interaction) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            await interaction.response.send_message(f"{list(pitboss.get_HumanPlayers())} {list(pitboss.get_TurnTaken())}")


    # FIXME ADMIN ONLY
    @app_commands.command(name="pb-expire", description="Manually expire the current claim")
    @app_commands.describe()
    async def expire(self, interaction: discord.Interaction) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            previous_player = current_player(pitboss)
            pitboss.ForceUnlock()
            await interaction.response.send_message(f"The turn of {previous_player} has expired. Anyone may take the turn.")


    @app_commands.command(name="pb-toggle-ai", description="Toggle whether the default AI will take your skipped turns")
    @app_commands.describe()
    async def toggle_ai(self, interaction: discord.Interaction) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            players = pitboss.get_HumanPlayers()
            index = players.index(interaction.user.name)
            result = pitboss.ToggleDefaultAI(index)
            if result:
                await interaction.response.send_message(f"{players[index]} enabled AI substitutes on their turns.")
            else:
                await interaction.response.send_message(f"{players[index]} disabled AI substitutes on their turns.")


    # FIXME ADMIN ONLY
    @app_commands.command(name="pb-auto-expire", description="Set the time period for claims to expire")
    @app_commands.describe()
    async def auto_expire(self, interaction: discord.Interaction,
                          duration: app_commands.Transform[datetime.timedelta, DurationConverter]) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            pitboss.auto_expire = duration
            await interaction.response.send_message(f"Auto-expiry set to: {pitboss.auto_expire}")


    # test commands

    @app_commands.command(name="file-save", description="Save any file.")
    @app_commands.describe(game="The file to save.")
    async def file_save(self, interaction: discord.Interaction, game: discord.Attachment) -> None:
        try:
            await game.save(game.filename)
            await interaction.response.send_message(f"File saved.")
        except Exception as e:
            await interaction.response.send_message(f"Something went wrong. {e}")
            print(traceback.format_exc())


    @app_commands.command(name="file-load", description="Loads any file.")
    @app_commands.describe(game_name="The game file.")
    async def file_load(self, interaction: discord.Interaction, game_name: str) -> None:
        file = discord.File(fp=open(game_name, "rb"), filename=game_name)

        class SingleFileView(discord.ui.LayoutView):
            file_attachment = discord.ui.File["SingleFileView"](media=file)

        view = SingleFileView()
        await interaction.response.send_message(view=view, files=[file])


    @app_commands.command(name="echo", description="Echoes a message.")
    @app_commands.describe(message="The message to echo.")
    async def echo(self, interaction: discord.Interaction, message: str) -> None:
        await interaction.response.send_message(message)


    @app_commands.command()
    async def ping(self, inter: discord.Interaction) -> None:
        """Get the bot's latency"""
        await inter.response.send_message(f"Pong! ({round(self.bot.latency * 1000)}ms)")
        try:
            await inter.response.send_message(f"Trying to send a second message...")
        except discord.InteractionResponded:
            await inter.followup.send(f"Responding again failed, as expected.")

async def setup(bot: commands.Bot):
    await bot.add_cog(PitBossCommands(bot))