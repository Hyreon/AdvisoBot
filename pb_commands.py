from __future__ import annotations

import asyncio
import datetime
import io
import traceback
import zipfile
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import has_permissions
from discord.app_commands import default_permissions

from pythonnet import load

load("coreclr")  # or "netfx" for .NET Framework — must be called before import clr

import clr

ref = clr.AddReference("Civ3Tools")
from Civ3Tools import PitBossOrganizer
import typing


def advance_time(pitboss):
    advance_delay = pitboss.advance_delay
    if advance_delay is None:
        advance_delay = datetime.timedelta(seconds=0)
    auto_advance_delay = pitboss.auto_advance_delay
    if auto_advance_delay is None:
        auto_advance_delay = datetime.timedelta(seconds=0)
    return pitboss.last_advance + advance_delay + auto_advance_delay


def any_advance(bot, pitboss):
    # FIXME include a check that all turns are done, which always allows advancing the turn
    if bot.holidays:
        return False
    time_is_up = datetime.datetime.now() > advance_time(pitboss)
    return time_is_up and not pitboss.dummy_is_admin


class MyLayoutView(discord.ui.LayoutView):
    message: discord.Message | None = None

    def expiry_string(self):
        try:
            player_taking_turn = current_player(self.pitboss)
            if player_taking_turn:
                member = self.channel.guild.get_member_named(player_taking_turn)
                if member:
                    base_string = f"{member.display_name} has the game save"
                else:
                    base_string = f"*{player_taking_turn}* has the game save"
                if self.pitboss.auto_expire:
                    return base_string + f", it will expire {discord.utils.format_dt(self.pitboss.expire_task.timeout_datetime, "R")}"
                else:
                    return base_string
            elif any_advance(self.bot, self.pitboss):
                return f"/pb-advance to advance the turn"
            elif self.pitboss.advance_delay or self.pitboss.auto_advance_delay:
                return f"Turn advance unlocked {discord.utils.format_dt(advance_time(self.pitboss), "R")}"
            elif self.bot.holidays:
                return f"Happy holidays!"
            else:
                return f"Turns advanced manually by staff"
        except Exception as e:
            print(traceback.format_exc())
            return str(e)

    container = discord.ui.Container["MyLayoutView"](
        discord.ui.Section(
            "Loading...",
            "...",
            "...",
            accessory=discord.ui.Thumbnail["MyLayoutView"]("https://i.imgur.com/9sDnoUW.jpeg"),
        ),
        accent_color=discord.Color.blurple(),
    )
    row: discord.ui.ActionRow[MyLayoutView] = discord.ui.ActionRow()

    def __init__(self, bot: commands.Bot, user: discord.User | discord.Member, channel, pitboss,
                 timeout: float = 60.0) -> None:
        self.pitboss = pitboss
        self.bot = bot
        self.channel = channel

        super().__init__(timeout=timeout)

        self.user = user

    async def update(self):
        section = self.container.children[0]
        section.children[0].content = f"## Turn {self.pitboss.get_CurrentTurn()}"
        section.children[1].content = "### " + self.expiry_string()
        section.children[2].content = f"{list(self.pitboss.get_HumanPlayers())} {list(self.pitboss.get_TurnTaken())}"
        await self.message.edit(view=self)

    # checks for the view's interactions
    async def interaction_check(self, interaction: discord.Interaction[discord.Client]) -> bool:
        # this method should return True if all checks pass, else False is returned
        # for example, you can check if the interaction was created by the user who
        # ran the command:
        if interaction.user == self.user:
            return True
        # else send a message and return False
        await interaction.response.send_message(f"The command was initiated by {self.user.mention}", ephemeral=True)
        return False

    # do stuff on timeout
    async def on_timeout(self) -> None:
        # this method is called when the period mentioned in timeout kwarg passes.
        # we can do tasks like disabling buttons here.
        for child in self.walk_children():
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        # and update the message with the update View.
        if self.message:
            await self.message.edit(view=self)

    # adding a component using it's decorator
    @row.button(label="Refresh", style=discord.ButtonStyle.green)
    async def counter(self, inter: discord.Interaction, button: discord.ui.Button[MyLayoutView]) -> None:
        # self.count += 1
        # button.label = str(self.count)
        await self.update()
        await inter.response.edit_message(view=self)

    # error handler for the view
    async def on_error(
            self, interaction: discord.Interaction[discord.Client], error: Exception, item: discord.ui.Item[typing.Any]
    ) -> None:
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        message = f"An error occurred while processing the interaction for {str(item)}:\n```py\n{tb}\n```"
        await interaction.response.send_message(message)


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


# returns a copy of the array where None is replaced with '#XX', making CPU players playable with permissions
def adjust_names(names: list[str]) -> list[str]:
    adjusted_names = []
    for i, name in enumerate(names):
        if name:
            adjusted_names.append(name)
        else:
            adjusted_names.append(f"#{i + 1}")
    return adjusted_names


def make_pitboss(file_bytes, names):
    pitboss = PitBossOrganizer(file_bytes, adjust_names(names))
    pitboss.auto_expire = None
    pitboss.expire_task = None
    pitboss.advance_delay = None
    pitboss.auto_advance_delay = datetime.timedelta(days=6, hours=6)
    pitboss.last_advance = datetime.datetime.now()
    pitboss.cpu_is_admin = True
    pitboss.dummy_is_admin = False

    for i,name in names:
        if name is None:
            while not pitboss.ToggleDefaultAI(i):
                pass
    return pitboss


def current_player(pitboss: PitBossOrganizer):
    index = pitboss.get_CurrentPlayer()
    if index is None or index < 0:
        return None
    players = list(pitboss.get_HumanPlayers())
    if index >= len(players):
        return "dummy"
    return players[index]


def get_turn_name(pitboss: PitBossOrganizer, channel_name: str, ext: str = ".SAV") -> str:
    return f"{channel_name}-{pitboss.get_CurrentTurn()}-{current_player(pitboss)}" + ext


def get_claim_label(pitboss: PitBossOrganizer):
    if pitboss.auto_expire:
        timestamp = pitboss.expire_task.timeout_datetime
        auto_expire_dt = discord.utils.format_dt(timestamp, "f")
        return f"{current_player(pitboss)} is taking the turn! This claim will expire if not submitted by {auto_expire_dt}."
    else:
        return f"{current_player(pitboss)} is taking the turn!"


def unlock_save(pitboss: PitBossOrganizer):
    pitboss.ForceUnlock()
    pitboss.active_user = None
    if pitboss.expire_task:
        pitboss.expire_task.cancel()
    pitboss.expire_task = None


async def auto_expire_with_notification(pitboss: PitBossOrganizer, user: discord.User,
                                        interaction: discord.Interaction):
    print(f"Scheduled auto expiry in ${pitboss.auto_expire}")
    await asyncio.sleep(pitboss.auto_expire.seconds)
    print("Attempted auto expiry")
    channel = interaction.channel
    if user:
        await user.send(f"Your turn in <#{channel.id}> has expired. You are free to take it again.")
    await interaction.followup.send("This turn has expired. Another one can be taken.")
    print(channel)
    unlock_save(pitboss)


async def update_pitboss(pitboss, protogame, messages):
    if pitboss:
        existing_players = pitboss.get_HumanPlayers()
        if len(existing_players) == len(protogame):
            set_player_order(pitboss, protogame)
        else:
            protogame = existing_players
            return f"Can't join new slots in an ongoing game. Players so far: {protogame}"
    return f"Updated registry. Players so far: {protogame}"


def set_player_order(pitboss, protogame):
    pitboss.ChangePlayerOrder(adjust_names(protogame))


def clear_pitboss(pitboss):
    task = pitboss.expire_task
    if task:
        task.cancel()
    pitboss.last_advance = datetime.datetime.now()
    pitboss.advance_delay = None
    pitboss.active_user = None


class PitBossCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def claim_for(self, interaction: discord.Interaction, user: discord.User = None, cpu_slot: int = None):
        username = None
        if cpu_slot:
            protogame = self.bot.protogames.get(interaction.channel_id, None)
            if not protogame:
                await interaction.response.send_message("There is no queue in this channel!")
                return
            elif protogame[cpu_slot-1] is None:
                username = f"#{cpu_slot}"
            else:
                await interaction.response.send_message("That's a player, not a CPU.")
                return
        elif user:
            username = user.name
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            game = None
            try:
                await interaction.response.defer()
                if username:
                    game = bytes(pitboss.GetConfiguredTurn(username))
                else:
                    game = bytes(pitboss.GetDummyTurn())

                file = None
                if len(game) >= 10 * 1024 * 1024:  # 10 MiB
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, allowZip64=False) as zf:
                        zf.writestr(get_turn_name(pitboss, interaction.channel.name), game)
                        compressed_bytes = buf.getvalue()
                        file = discord.File(fp=io.BytesIO(compressed_bytes),
                                            filename=get_turn_name(pitboss, interaction.channel.name, ext=".zip"))
                else:
                    file = discord.File(fp=io.BytesIO(game), filename=get_turn_name(pitboss, interaction.channel.name))

                if user:
                    pitboss.active_user = user.id
                else:
                    pitboss.active_user = interaction.user.id

                if pitboss.auto_expire:
                    pitboss.expire_task = asyncio.create_task(
                        auto_expire_with_notification(pitboss, user, interaction))
                    pitboss.expire_task.timeout_datetime = datetime.datetime.now() + pitboss.auto_expire
                label = get_claim_label(pitboss)

                await interaction.followup.send(label, files=[file])
            except Exception as e:
                await interaction.followup.send(f"Something went wrong. {e}")
                print(traceback.format_exc())

                with open("problem_save.SAV", "w+b") as f:
                    f.write(game)

    # FIXME adding other players ADMIN ONLY
    # swapping is a bit suspicious, there's got to be some safeties against it, but for now is fine
    # actually so is joining in whatever slot you like, you can boot someone out of the game that way
    @app_commands.command(name="pb-register",
                          description="Sign up for a PitBoss game on this channel, or switch to a different slot if already signed up")
    @app_commands.describe(slot="The desired player slot.",
                           player="The player you're adding (leave blank for yourself)")
    async def register(self, interaction: discord.Interaction, slot: int = 0, player: discord.User = None) -> None:
        try:
            messages = []
            slot -= 1  # 1 indexed to 0 indexed
            value = interaction.user.name
            if player:
                if interaction.permissions.manage_events:
                    value = player.name
                else:
                    await interaction.response.send_message(
                        f"You're not allowed to register other players! Only hosts can do that.")
                    return
            if not self.bot.protogames.get(interaction.channel_id):
                self.bot.protogames[interaction.channel_id] = []
            protogame = self.bot.protogames[interaction.channel_id]
            pitboss = self.bot.games.get(interaction.channel_id)
            if value in protogame:
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
            # if slot >= 0:
            #     messages.append("Took slot {slot}. Players so far: {protogame}")
            await interaction.response.send_message(await update_pitboss(pitboss, protogame, messages))
        except Exception as e:
            await interaction.followup.send(f"Something went wrong. {e}")
            print(traceback.format_exc())

    # FIXME removing other players ADMIN ONLY
    @app_commands.command(name="pb-leave", description="Exit the PitBoss game on this channel.")
    @app_commands.describe(player="The player that's leaving (leave blank for yourself)")
    async def leave(self, interaction: discord.Interaction, player: discord.User = None) -> None:
        value = interaction.user.name
        if player:
            if interaction.permissions.manage_events:
                value = player.name
            else:
                await interaction.response.send_message(
                    f"You're not allowed to remove other players! Only hosts can do that.")
                return
        if not self.bot.protogames.get(interaction.channel_id):
            self.bot.protogames[interaction.channel_id] = []
        protogame = self.bot.protogames[interaction.channel_id]
        found = False
        for i, name in enumerate(protogame):
            if name == value:
                found = True
                protogame[i] = None
                break
        pitboss = self.bot.games.get(interaction.channel_id)
        if pitboss:
            set_player_order(pitboss, protogame)
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
            await interaction.response.defer()
            try:
                protogame = self.bot.protogames[interaction.channel_id]
                file_bytes = await game.read()
                pitboss = make_pitboss(file_bytes, protogame)
                self.bot.games[interaction.channel_id] = pitboss
                await interaction.followup.send(f"Made the pitboss game!! Plays: {list(pitboss.get_TurnTaken())}")
            except Exception as e:
                await interaction.followup.send(f"Something went wrong. {e}")
                print(traceback.format_exc())

    @has_permissions(manage_events=True)
    @default_permissions(manage_events=True)
    @app_commands.command(name="pb-close", description="Close a PitBoss server in this channel.")
    async def close(self, interaction: discord.Interaction) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            del self.bot.games[interaction.channel_id]
            del self.bot.protogames[interaction.channel_id]
            await interaction.response.send_message("Game closed. See you in the next one!")

    #FIXME special permissions needed, not sure what
    @app_commands.command(name="pb-advance", description="Take the dummy turn")
    @app_commands.describe()
    async def advance_turn(self, interaction: discord.Interaction):
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            if any_advance(self.bot, pitboss) or interaction.permissions.manage_events:
                await self.claim_for(interaction)
            else:
                await interaction.response.send_message(
                    f"You're not allowed to advance the turn at this time")

    @app_commands.command(name="pb-toggle-stick-the-dealer",
                          description="Toggle whether the last player is a dummy or a player that has to go last")
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

    @has_permissions(manage_events=True)
    @default_permissions(manage_events=True)
    @app_commands.command(name="pb-toggle-admin-dummy",
                          description="Toggle whether dummy players require permissions to play")
    @app_commands.describe()
    async def toggle_admin_dummy(self, interaction: discord.Interaction):
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        elif pitboss.get_LastPlayerHuman():
            await interaction.response.send_message("The last player is a human!")
        else:
            pitboss.dummy_is_admin = not pitboss.dummy_is_admin
            if pitboss.dummy_is_admin:
                await interaction.response.send_message("**Admins only** can now play the dummy player")
            else:
                await interaction.response.send_message("**Anyone** can now play the dummy player")

    @has_permissions(manage_events=True)
    @default_permissions(manage_events=True)
    @app_commands.command(name="pb-toggle-admin-cpu",
                          description="Toggle whether CPU players require permissions to play")
    @app_commands.describe()
    async def toggle_admin_cpu(self, interaction: discord.Interaction):
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            pitboss.cpu_is_admin = not pitboss.cpu_is_admin
            if pitboss.cpu_is_admin:
                await interaction.response.send_message("**Admins only** can now play CPUs.")
            else:
                await interaction.response.send_message("**Anyone** can now play CPUs.")


    @app_commands.command(name="pb-take", description="Get the save file to take your turn!")
    async def take(self, interaction: discord.Interaction, cpu_slot: int = None) -> None:

        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            if cpu_slot is None or not pitboss.cpu_is_admin or interaction.permissions.manage_events:
                await self.claim_for(interaction, interaction.user, cpu_slot)
            else:
                await interaction.response.send_message(
                    f"You're not allowed to play CPU turns at this time.")

    @has_permissions(manage_events=True)
    @default_permissions(manage_events=True)
    @app_commands.command(name="pb-give", description="Get the save file for someone else's turn!")
    async def give(self, interaction: discord.Interaction, player: discord.User) -> None:
        await self.claim_for(interaction, player)

    @app_commands.command(name="pb-submit", description="Submit your save file.")
    @app_commands.describe(game="The game file.")
    async def submit(self, interaction: discord.Interaction, game: discord.Attachment) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        elif pitboss.active_user and pitboss.active_user is not interaction.user.id:
            await interaction.response.send_message("You aren't the one with the claim!")
        else:
            await interaction.response.defer()
            try:
                if pitboss.get_CurrentPlayer() == len(pitboss.get_HumanPlayers()):
                    pitboss.ReceiveDummyTurn(await game.read())
                else:
                    pitboss.ReceiveNewTurn(await game.read())
                clear_pitboss(pitboss)
                await interaction.followup.send(f"Save submitted.")
            except Exception as e:
                await interaction.followup.send(f"Something went wrong. {e}")
                print(traceback.format_exc())

    @app_commands.command(name="pb-status", description="Get the status of the PBE in this channel.")
    @app_commands.describe()
    async def status(self, interaction: discord.Interaction) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            protogame = self.bot.protogames.get(interaction.channel_id, None)
            if not protogame:
                await interaction.response.send_message("There is no game in this channel!")
            else:
                await interaction.response.send_message(
                    f"No game in progress. Players in queue: {protogame}")
        else:
            await interaction.response.defer()
            view = MyLayoutView(self.bot, interaction.user, interaction.channel, pitboss)
            view.message = await interaction.followup.send(view=view)
            await view.update()

    @has_permissions(manage_events=True)
    @default_permissions(manage_events=True)
    @app_commands.command(name="pb-expire", description="Manually expire the current claim")
    @app_commands.describe()
    async def expire(self, interaction: discord.Interaction) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            previous_player = current_player(pitboss)
            unlock_save(pitboss)
            await interaction.response.send_message(
                f"The turn of {previous_player} has expired. Anyone may take the turn.")

    @app_commands.command(name="pb-toggle-cpu-sub", description="Toggle whether the default CPU will take your skipped turns")
    @app_commands.describe()
    async def toggle_cpu_sub(self, interaction: discord.Interaction) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            players = pitboss.get_HumanPlayers()
            index = players.index(interaction.user.name)
            result = pitboss.ToggleDefaultAI(index)
            if result:
                await interaction.response.send_message(f"{players[index]} enabled CPU substitutes on their turns.")
            else:
                await interaction.response.send_message(f"{players[index]} disabled CPU substitutes on their turns.")

    @has_permissions(manage_events=True)
    @default_permissions(manage_events=True)
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

    @has_permissions(manage_events=True)
    @default_permissions(manage_events=True)
    @app_commands.command(name="pb-delay-advance", description="Delay the turn advance for just this turn")
    @app_commands.describe()
    async def delay_advance(self, interaction: discord.Interaction,
                            duration: app_commands.Transform[datetime.timedelta, DurationConverter]) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            pitboss.advance_delay = duration
            await interaction.response.send_message(
                f"Last slot unlocked {discord.utils.format_dt(advance_time(pitboss), "R")}, including a break this turn for {duration}")

    @has_permissions(manage_events=True)
    @default_permissions(manage_events=True)
    @app_commands.command(name="pb-auto-delay-advance",
                          description="Set the time period for the last slot to be locked")
    @app_commands.describe()
    async def auto_delay_advance(self, interaction: discord.Interaction,
                                 duration: app_commands.Transform[datetime.timedelta, DurationConverter]) -> None:
        pitboss = self.bot.games.get(interaction.channel_id, None)
        if not pitboss:
            await interaction.response.send_message("There is no game in this channel!")
        else:
            pitboss.auto_advance_delay = duration
            await interaction.response.send_message(
                f"Last slot unlocked {discord.utils.format_dt(advance_time(pitboss), "R")}, players will have {duration} to complete their turn")

    @has_permissions(manage_events=True)
    @default_permissions(manage_events=True)
    @app_commands.command(name="pb-toggle-holiday",
                          description="Disables advancing turns server-wide")
    @app_commands.describe()
    async def toggle_holiday(self, interaction: discord.Interaction) -> None:
        self.bot.holidays = not self.bot.holidays
        if self.bot.holidays:
            await interaction.response.send_message(
                "Holiday mode enabled.\n-# Turns cannot be advanced unless all other players have taken their turns.")
        else:
            await interaction.response.send_message("Holiday mode disabled.")

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
