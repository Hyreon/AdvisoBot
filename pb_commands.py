import datetime
import traceback

import discord
from discord import app_commands
from discord.ext import commands

import clr

ref = clr.AddReference("Civ3Tools")
from Civ3Tools import PitBossOrganizer


def make_pitboss(file_bytes, names):
    pitboss = PitBossOrganizer(file_bytes, names)
    pitboss.auto_expire = None
    # pitboss.auto_advance = None
    pitboss.expire_task = None
    return pitboss


def current_player(pitboss: PitBossOrganizer):
    return list(pitboss.get_HumanPlayers())[pitboss.get_CurrentPlayer()]


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

async def auto_expire_with_notification(pitboss: PitBossOrganizer, user: discord.User, channel: discord.TextChannel):
    print(f"Scheduled auto expiry in ${pitboss.auto_expire}")
    await asyncio.sleep(pitboss.auto_expire.seconds)
    print("Attempted auto expiry")
    await user.send(f"Your turn in <#{channel.id}> has expired. You are free to take it again.")
    unlock_save(pitboss)

async def claim_for(interaction: discord.Interaction, user: discord.User):
    username = user.name
    pitboss = bot.games.get(interaction.channel_id, None)
    if not pitboss:
        await interaction.response.send_message("There is no game in this channel!")
    else:
        try:
            await interaction.response.defer()
            game = bytes(pitboss.GetConfiguredTurn(username))
            file = discord.File(fp=io.BytesIO(game), filename=get_turn_name(pitboss, interaction.channel.name))

            if pitboss.auto_expire:
                pitboss.expire_task = asyncio.create_task(auto_expire_with_notification(pitboss, user, interaction.channel))
            label = get_claim_label(pitboss)

            await interaction.followup.send(label, files=[file])
        except Exception as e:
            await interaction.followup.send(f"Something went wrong. {e}")
            print(traceback.format_exc())



class PitBossCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # FIXME adding other players ADMIN ONLY
    @bot.tree.command(name="pb-register", description="Sign up for a PitBoss game on this channel.")
    @app_commands.describe(slot="The desired player slot.", player="The player you're adding (leave blank for yourself)")
    async def register(interaction: discord.Interaction, slot: int = 0, player: discord.User = None) -> None:
        value = interaction.user.name
        if player:
            value = player.name
        if not bot.protogames.get(interaction.channel_id):
            bot.protogames[interaction.channel_id] = []
        protogame = bot.protogames[interaction.channel_id]
        while len(protogame)+1 < slot:
            protogame.append(None)
        if slot == 0 or len(protogame) < slot:
            protogame.append(value)
        else:
            protogame[slot] = value
        pitboss = bot.games.get(interaction.channel_id)
        if pitboss:
            existing_players = pitboss.get_HumanPlayers()
            if len(existing_players) == len(protogame):
                pitboss.ChangePlayerOrder(protogame)
            else:
                await interaction.response.send_message(f"Can't join new slots in an ongoing game. Players so far: {protogame}")
                return
        await interaction.response.send_message(f"Updated registry. Players so far: {protogame}")

    # FIXME removing other players ADMIN ONLY
    @app_commands.describe(player="The player that's leaving (leave blank for yourself)")
    @bot.tree.command(name="pb-leave", description="Exit the PitBoss game on this channel.")
    async def leave(interaction: discord.Interaction, player: discord.User = None) -> None:
        value = interaction.user.name
        if player:
            value = player.name
        if not bot.protogames.get(interaction.channel_id):
            bot.protogames[interaction.channel_id] = []
        protogame = bot.protogames[interaction.channel_id]
        found = False
        for i,name in enumerate(protogame):
            if name == value:
                found = True
                protogame[i] = None
                break
        pitboss = bot.games.get(interaction.channel_id)
        if pitboss:
            pitboss.ChangePlayerOrder(protogame)
        else:
            while len(protogame) > 0 and not protogame[-1]:
                protogame.pop()
        if found:
            await interaction.response.send_message(f"Updated registry. Players so far: {protogame}")
        else:
            await interaction.response.send_message(f"You aren't in this game. Players so far: {protogame}")

    @bot.tree.command(name="pb-create", description="Create a new PitBoss server from a game file.")
    @app_commands.describe(game="The game file.")
    async def create(interaction: discord.Interaction, game: discord.Attachment) -> None:
        names = ['hyreon', 'theperezident94', 'pelomcsoy', 'ztatiz']
        file_bytes = await game.read()
        pitboss = make_pitboss(file_bytes, names)
        bot.games[interaction.channel_id] = pitboss
        await interaction.response.send_message(f"Made the pitboss game!! Plays: {list(pitboss.get_TurnTaken())}")

    @bot.tree.command(name="pb-take", description="Get the save file to take your turn!")
    async def take(interaction: discord.Interaction) -> None:
        await claim_for(interaction, interaction.user)


    #FIXME ADMIN ONLY
    @bot.tree.command(name="pb-give", description="Get the save file for someone else's turn!")
    async def give(interaction: discord.Interaction, player: discord.User) -> None:
        await claim_for(interaction, player)


    @bot.tree.command(name="pb-submit", description="Submit your save file.")
    @app_commands.describe(game="The game file.")
    async def submit(interaction: discord.Interaction, game: discord.Attachment) -> None:
        pitboss = bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            await interaction.response.defer()
            try:
                pitboss.ReceiveNewTurn(await game.read())
                await interaction.followup.send(f"Save submitted.")
            except Exception as e:
                await interaction.followup.send(f"Something went wrong. {e}")
                print(traceback.format_exc())


    @bot.tree.command(name="pb-status", description="Get the status of the PBE in this channel.")
    @app_commands.describe()
    async def status(interaction: discord.Interaction) -> None:
        pitboss = bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            await interaction.response.send_message(f"{list(pitboss.get_HumanPlayers())} {list(pitboss.get_TurnTaken())}")


    # FIXME ADMIN ONLY
    @bot.tree.command(name="pb-expire", description="Manually expire the current claim")
    @app_commands.describe()
    async def expire(interaction: discord.Interaction) -> None:
        pitboss = bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            previous_player = current_player(pitboss)
            pitboss.ForceUnlock()
            await interaction.response.send_message(f"The turn of {previous_player} has expired. Anyone may take the turn.")


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


    # FIXME ADMIN ONLY
    @bot.tree.command(name="pb-auto-expire", description="Set the time period for claims to expire")
    @app_commands.describe()
    async def auto_expire(interaction: discord.Interaction,
                          duration: app_commands.Transform[datetime.timedelta, DurationConverter]) -> None:
        pitboss = bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            pitboss.auto_expire = duration
            await interaction.response.send_message(f"Auto-expiry set to: {pitboss.auto_expire}")


    # test commands

    @bot.tree.command(name="file-save", description="Save any file.")
    @app_commands.describe(game="The file to save.")
    async def file_save(interaction: discord.Interaction, game: discord.Attachment) -> None:
        try:
            await game.save(game.filename)
            await interaction.response.send_message(f"File saved.")
        except Exception as e:
            await interaction.response.send_message(f"Something went wrong. {e}")
            print(traceback.format_exc())


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