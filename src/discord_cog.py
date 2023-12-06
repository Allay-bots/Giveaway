import random
from datetime import datetime, timedelta, timezone
from typing import Optional, Union
from uuid import uuid4

import discord
from discord.app_commands import (AppCommandError, Choice, Range,
                                  TransformerError)
from discord.ext import commands, tasks
from LRFutils import logs

import allay
from allay.core.src.discord.utils.views import ConfirmView

# pylint: disable=relative-beyond-top-level
from .custom_args import ColorOption, DateOption, DurationOption
from .custom_participants_verification import verify_participants
from .types import GiveawayData, GiveawayParticipant, GiveawayToSendData
from .views import GiveawayView, ParticipantsPaginator

AcceptableChannel = (
    discord.TextChannel, discord.Thread, discord.StageChannel, discord.VoiceChannel
)
AcceptableChannelType = Union[
    discord.TextChannel, discord.Thread, discord.StageChannel, discord.VoiceChannel
]


class GiveawaysCog(commands.Cog):
    "Handle giveaways"

    def __init__(self, bot: allay.Bot):
        self.bot = bot
        self.embed_color = 0x9933ff

        # we have to register @error this way because it does not support "self" argument
        @self.group.error
        async def _on_command_error(interaction: discord.Interaction, error: AppCommandError):
            await self.on_giveaway_command_error(interaction, error)

    async def cog_load(self):
        """Start the scheduler on cog load"""
        self.schedule_giveaways.start() # pylint: disable=no-member

    async def cog_unload(self):
        """Stop the scheduler on cog unload"""
        self.schedule_giveaways.stop() # pylint: disable=no-member

    @tasks.loop(minutes=1)
    async def schedule_giveaways(self):
        "Check for expired giveaways and schedule their closing"
        now = discord.utils.utcnow()
        for giveaway in await self.db_get_active_giveaways():
            if giveaway["ends_at"] <= now:
                logs.info(f"Closing giveaway {giveaway['id']}")
                await self.close_giveaway(giveaway)

    @schedule_giveaways.before_loop
    async def on_schedule_giveaways_before(self):
        "Wait for the bot to be ready before starting the scheduler"
        await self.bot.wait_until_ready()

    @schedule_giveaways.error
    async def on_schedule_giveaways_error(self, error: BaseException):
        "Log errors from the scheduler"
        self.bot.dispatch("error", error)


    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Called when *any* interaction from the bot is received
        We use it to detect interactions with any giveaway Join button"""
        if not interaction.guild:
            return # ignore DMs
        if interaction.type != discord.InteractionType.component:
            return # ignore non-button interactions
        if not interaction.data or "custom_id" not in interaction.data:
            return
        custom_ids = interaction.data["custom_id"].split('-')
        if len(custom_ids) != 2 or custom_ids[0] != "gaw":
            return # not a giveaway button
        await interaction.response.defer(ephemeral=True)
        gaw_id = custom_ids[1]
        gaw = await self.db_get_giveaway(gaw_id)
        if gaw is None or gaw["ended"] or gaw["ends_at"] < discord.utils.utcnow():
            return # giveaway not found or ended
        await self.register_new_participant(interaction, gaw)


    group = discord.app_commands.Group(
        name="giveaways",
        description="Manage giveaways in your server",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True
    )

    async def on_giveaway_command_error(self, interaction: discord.Interaction,
                                        error: AppCommandError):
        "Handle errors from the /giveaway command"
        if isinstance(error, TransformerError):
            await interaction.response.send_message(error.args[0], ephemeral=True)
            return
        logs.error(f"Error in /giveaway command: {error}")

    @group.command(name="list")
    async def gw_list(self, interaction: discord.Interaction, *, include_stopped: bool=False):
        "List all the giveaways in the server"
        await interaction.response.defer()
        text = ""
        now = discord.utils.utcnow()
        if include_stopped:
            giveaways = await self.db_get_giveaways()
        else:
            giveaways = await self.db_get_active_giveaways()
        for gaw in giveaways:
            name = gaw["name"]
            message_url = f"https://discord.com/channels/{gaw['guild_id']}/{gaw['channel_id']}/{gaw['message_id']}"
            text += f"- **[{name}]({message_url})**  -  "
            if participants := await self.db_get_giveaways_participants(gaw["id"]):
                participants_count = len(participants)
                winners_count = sum(1 for p in participants if p["winner"])
            else:
                participants_count = 0
                winners_count = 0
            if max_entries := gaw.get("max_entries"):
                text += f"{participants_count}/{max_entries} participants - "
            else:
                text += f"{participants_count} participants - "
            max_winners_count = gaw['winners_count']
            if gaw["ended"]:
                text += f"{winners_count}/{max_winners_count} winners - "
            else:
                text += f"max {max_winners_count} winners - "
            end_date = discord.utils.format_dt(gaw["ends_at"], "R")
            if gaw["ends_at"] > now:
                text += f"ends {end_date}\n"
            else:
                text += f"ended {end_date}\n"
        if not text:
            text = "No giveaways" if include_stopped else "No active giveaways"
        embed = discord.Embed(
            title=("List of all giveaways" if include_stopped else "List of active giveaways"),
            description=text,
            color=self.embed_color
        )
        await interaction.followup.send(embed=embed)

    @group.command(name="create")
    async def gw_create(self, interaction: discord.Interaction, *, name: Range[str, 2, 30],
                        description: Range[str, 2, 256], duration: DurationOption,
                        channel: Optional[AcceptableChannelType]=None,
                        color: Optional[ColorOption]=None, max_entries: Optional[int]=None,
                        winners_count: int=1):
        "Create a giveaway"
        if interaction.guild is None:
            return
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, AcceptableChannel):
            await interaction.response.send_message("Giveaways can only be sent in text channels!")
            return
        if target_channel is None:
            return
        bot_perms = target_channel.permissions_for(interaction.guild.me)
        if not (bot_perms.send_messages and bot_perms.embed_links):
            await interaction.response.send_message(
                "I need the permission to send messages and embed links in this channel!"
            )
            return
        await interaction.response.defer()
        ends_date = discord.utils.utcnow() + timedelta(seconds=duration)
        if max_entries is not None and winners_count > max_entries:
            winners_count = max_entries
        data: GiveawayToSendData = {
            "id": uuid4().hex,
            "guild_id": interaction.guild.id,
            "channel_id": target_channel.id,
            "name": name,
            "description": description,
            "color": color.value if color else self.embed_color,
            "max_entries": max_entries,
            "winners_count": winners_count,
            "ends_at": ends_date,
            "ended": False,
        }
        message = await self.send_gaw(target_channel, data)
        await self.db_create_giveaway({
            **data,
            "message_id": message.id,
        })
        await interaction.followup.send(f"Giveaway created at {message.jump_url} !")

    @group.command(name="delete")
    async def gw_delete(self, interaction: discord.Interaction, giveaway: str):
        "Permanently delete a giveaway from the database"
        if interaction.guild is None:
            return
        await interaction.response.defer()
        gaw = await self.db_get_giveaway(giveaway)
        if gaw is None:
            await interaction.followup.send("Giveaway not found!")
            return
        if gaw["guild_id"] != interaction.guild.id:
            await interaction.followup.send("You can only delete giveaways in your own server!")
            return
        if not gaw["ended"]:
            confirm_view = ConfirmView(
                validation=lambda inter: inter.user.id == interaction.user.id,
                send_confirmation=False
            )
            await interaction.followup.send(
                "This giveaway is still ongoing! Are you sure you want to delete it?",
                view=confirm_view)
            await confirm_view.wait()
            if confirm_view.value is None:
                await confirm_view.disable(interaction)
                return
            if not confirm_view.value:
                await confirm_view.disable(interaction)
                return
        await self.db_delete_giveaway(giveaway)
        await interaction.followup.send("Giveaway deleted!")

    async def gw_delete_autocomplete(self, interaction: discord.Interaction, current: str):
        "Autocomplete for the giveaway argument of the delete command"
        if interaction.guild_id is None:
            return []
        current = current.lower()
        choices: list[tuple[bool, str, Choice[str]]] = []
        for gaw in await self.db_get_giveaways():
            if gaw["guild_id"] == interaction.guild_id and current in gaw["name"].lower():
                priority = not gaw["name"].lower().startswith(current)
                choice = Choice(name=gaw["name"], value=gaw["id"])
                choices.append((priority, gaw["name"], choice))
        return [choice for _, _, choice in sorted(choices, key=lambda x: x[0:2])]

    @group.command(name="edit")
    @discord.app_commands.rename(utc_end_date="utc-end-date")
    @discord.app_commands.describe(
        utc_end_date="The end date in UTC timezone, in format dd/mm/yyyy hh:mm or yyyy-mm-dd hh:mm",
        max_entries="The maximum number of participants",
        winners_count="The maximum number of winners to pick"
    )
    async def gw_edit(self, interaction: discord.Interaction, giveaway: str, *,
                      name: Optional[Range[str, 2, 30]]=None,
                      description: Optional[Range[str, 2, 256]]=None,
                      utc_end_date: Optional[DateOption]=None,
                      color: Optional[ColorOption]=None,
                      max_entries: Optional[int]=None,
                      winners_count: Optional[int]=None):
        "Edit an existing giveaway"
        if interaction.guild is None:
            return
        if all(
            arg is None
            for arg in (name, description, utc_end_date, color, max_entries, winners_count)
        ):
            await interaction.response.send_message(
                "You must provide at least one argument to edit!")
            return
        if utc_end_date is not None and utc_end_date < discord.utils.utcnow():
            utc_now = discord.utils.utcnow().strftime("%d/%m/%Y %H:%M")
            await interaction.response.send_message(
                f"The end date must be in the future! (current UTC time: {utc_now})"
            )
            return
        await interaction.response.defer()
        gaw = await self.db_get_giveaway(giveaway)
        if gaw is None:
            await interaction.followup.send("Giveaway not found!")
            return
        # run basic tests
        if gaw["guild_id"] != interaction.guild.id:
            await interaction.followup.send("You can only delete giveaways in your own server!")
            return
        if gaw["ended"]:
            await interaction.followup.send("You can't edit an ended giveaway!")
            return
        # edit original data
        gaw = await self._merge_giveaways_data(
            gaw, name, description, utc_end_date, color, max_entries, winners_count)
        # edit embed
        message = await self.fetch_gaw_message(gaw)
        if message is None:
            await interaction.followup.send("Giveaway message not found!")
            return
        # get participants count
        participants = await self.db_get_giveaways_participants(gaw["id"])
        embed = await self.create_active_gaw_embed(gaw, participants_count=len(participants))
        await message.edit(embed=embed)
        # edit database
        await self.db_edit_giveaway(giveaway, gaw)
        await interaction.followup.send("Giveaway edited!")

    @group.command(name="list-participants")
    async def gw_list_participants(self, interaction: discord.Interaction, giveaway: str):
        "List all participants in a giveaway"
        if interaction.guild is None:
            return
        await interaction.response.defer()
        gaw = await self.db_get_giveaway(giveaway)
        if gaw is None:
            await interaction.followup.send("Giveaway not found!")
            return
        if gaw["guild_id"] != interaction.guild.id:
            await interaction.followup.send(
                "You can only list participants of giveaways in your own server!")
            return
        participants = await self.db_get_giveaways_participants(giveaway)
        if not participants:
            await interaction.followup.send("No participants!")
            return
        view = ParticipantsPaginator(
            self.bot, self.embed_color, interaction.user, gaw,
            [p["user_id"] for p in participants]
        )
        await view.send_init(interaction)

    @gw_list_participants.autocomplete("giveaway")
    @gw_delete.autocomplete("giveaway")
    @gw_edit.autocomplete("giveaway")
    async def gw_command_autocomplete(self, interaction: discord.Interaction, current: str):
        "Autocomplete for the giveaway argument of /giveaway delete, edit, or list-participants"
        if interaction.guild_id is None:
            return []
        current = current.lower()
        choices: list[tuple[bool, str, Choice[str]]] = []
        for gaw in await self.db_get_giveaways():
            if gaw["guild_id"] == interaction.guild_id and current in gaw["name"].lower():
                priority = not gaw["name"].lower().startswith(current)
                choice = Choice(name=gaw["name"], value=gaw["id"])
                choices.append((priority, gaw["name"], choice))
        return [choice for _, _, choice in sorted(choices, key=lambda x: x[0:2])]

    @group.command(name="reroll")
    async def gw_reroll_winners(self, interaction: discord.Interaction, giveaway: str):
        "Reroll winners of a giveaway"
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        gaw = await self.db_get_giveaway(giveaway)
        if gaw is None:
            await interaction.followup.send("Giveaway not found!")
            return
        if gaw["guild_id"] != interaction.guild.id:
            await interaction.followup.send(
                "You can only reroll winners of giveaways in your own server!")
            return
        if not gaw["ended"]:
            await interaction.followup.send("You can only reroll winners of ended giveaways!")
            return
        gaw["ended"] = False
        await self.close_giveaway(gaw)
        participants = await self.db_get_giveaways_participants(gaw["id"])
        winners = [p for p in participants if p["winner"]]
        if len(winners) == 0:
            txt = "No winners picked"
        elif len(winners) == 1:
            txt = f"1 winner picked: <@{winners[0]}>"
        else:
            txt = f"{len(winners)} winners picked: {' '.join(f'<@{winner}>' for winner in winners)}"
        await interaction.followup.send(
            "Giveaway rerolled!\n" + txt,
            allowed_mentions=discord.AllowedMentions.none()
        )

    @gw_reroll_winners.autocomplete("giveaway")
    async def gw_reroll_winners_autocomplete(self, interaction: discord.Interaction, current: str):
        "Autocomplete for the giveaway argument of the reroll command"
        if interaction.guild_id is None:
            return []
        current = current.lower()
        choices: list[tuple[bool, str, Choice[str]]] = []
        for gaw in await self.db_get_giveaways():
            if (
                gaw["guild_id"] == interaction.guild_id
                and gaw["ended"]
                and current in gaw["name"].lower()
            ):
                priority = not gaw["name"].lower().startswith(current)
                choice = Choice(name=gaw["name"], value=gaw["id"])
                choices.append((priority, gaw["name"], choice))
        return [choice for _, _, choice in sorted(choices, key=lambda x: x[0:2])]

    async def create_active_gaw_embed(self, data: GiveawayToSendData, participants_count: int=0):
        "Create a Discord embed for an active giveaway"
        ends_in = discord.utils.format_dt(data["ends_at"], "R")
        description = data["description"] + f"\n\nThis giveaway ends {ends_in}"
        embed = discord.Embed(
            title=data["name"],
            description=description,
            color=data["color"],
            timestamp=data["ends_at"]
        )
        if max_entries := data["max_entries"]:
            embed.add_field(name="Participants", value=f"{participants_count}/{max_entries}")
        else:
            embed.add_field(name="Participants", value=str(participants_count))
        embed.set_footer(text="Ends at")
        return embed

    async def send_gaw(self, channel: AcceptableChannelType, data: GiveawayToSendData):
        "Send a giveaway message in a given channel"
        embed = await self.create_active_gaw_embed(data)
        view = GiveawayView(self.bot, data, "Join the giveaway!")
        msg = await channel.send(embed=embed, view=view)
        return msg

    async def fetch_gaw_message(self, data: GiveawayData):
        "Fetch the Discord message for a giveaway"
        channel = self.bot.get_channel(data["channel_id"])
        if not isinstance(channel, AcceptableChannel):
            return None
        try:
            message = await channel.fetch_message(data["message_id"])
        except discord.NotFound:
            return None
        return message

    async def increase_gaw_embed_participants(self, data: GiveawayData,
                                              participants_count: Optional[int]=None):
        "Fetch the Discord message for a giveaway, parse it and increment the participants count"
        message = await self.fetch_gaw_message(data)
        if message is None:
            return
        embed = message.embeds[0]
        if embed.fields[0].value is None:
            return
        field_value = embed.fields[0].value.split('/')
        if participants_count:
            field_value[0] = str(participants_count)
        else:
            field_value[0] = str(int(field_value[0]) + 1)
        embed.set_field_at(0, name="Participants", value="/".join(field_value))
        await message.edit(embed=embed)

    async def register_new_participant(self, interaction: discord.Interaction,
                                       giveaway: GiveawayData):
        """Register a new participant to a giveaway (when they click on the Join button)"""
        if await self.db_check_giveaway_participant(giveaway["id"], interaction.user.id):
            await interaction.followup.send(
                f"{interaction.user.mention} you already joined the giveaway!", ephemeral=True)
            return
        participants = await self.db_get_giveaways_participants(giveaway["id"])
        if (
            (max_entries := giveaway.get("max_entries"))
            and participants is not None
            and len(participants) >= max_entries
        ):
            await interaction.followup.send(
                f"{interaction.user.mention} the limit of participants for this giveaway has "\
                "been reached! Maybe you'll be luckier next time...",
                ephemeral=True
            )
            return
        await self.db_add_giveaway_participant(giveaway["id"], interaction.user.id)
        await interaction.followup.send(
            f"{interaction.user.mention} you joined the giveaway, good luck!", ephemeral=True)
        participants_count = len(participants) + 1
        await self.increase_gaw_embed_participants(giveaway, participants_count=participants_count)

    async def close_giveaway(self, data: GiveawayData):
        "Close a giveaway and pick the winners"
        if data["ended"]:
            return
        logs.info(f"Closing giveaway {data['id']}")
        message = await self.fetch_gaw_message(data)
        if message is None:
            return
        # edit initial embed
        embed = message.embeds[0]
        embed.set_footer(text="Ended at")
        winners = await self.pick_giveaway_winners(data)
        # remove existing winners field
        while embed.fields and embed.fields[-1].name == "Winners":
            embed.remove_field(-1)
        # add winners field
        if len(winners) == 0:
            embed.add_field(name="Winners", value="No one joined the giveaway...")
        elif len(winners) < 35:
            embed.add_field(name="Winners", value=", ".join(f"<@{winner}>" for winner in winners))
        else:
            embed.add_field(name="Winners", value=f"{len(winners)} winners picked")
        await message.edit(embed=embed, view=None)
        # send a new message mentionning winners
        if len(winners) == 1:
            await message.reply(
                f"The winner of the **{data['name']}** giveaways has been picked!\n"\
                f"Congratulations to <@{winners[0]}>!",
            )
        elif len(winners) != 0:
            winners_mentions = " ".join(f"<@{winner}>" for winner in winners)
            await message.reply(
                f"The winners of the **{data['name']}** giveaways have been picked!\n"\
                f"Congratulations to {winners_mentions}!",
            )
        else:
            await message.reply(
                f"Unfortunately, no one joined the **{data['name']}** giveaways...\n"\
                "Better luck next time!",
            )
        # mark the giveaway as ended in the database
        await self.db_close_giveaway(data["id"], winners)

    async def pick_giveaway_winners(self, data: GiveawayData) -> list[int]:
        "Fetch participants of a giveaway and randomly pick winners"
        participants = await self.db_get_giveaways_participants(data["id"])
        if not participants:
            return []
        filtered_participants_ids = await verify_participants(self.bot, data, participants)
        winners_count = min(data["winners_count"], len(filtered_participants_ids))
        logs.info(f"Giveaways - {len(filtered_participants_ids)}/{len(participants)} \
participants are elligible")
        return random.sample(filtered_participants_ids, winners_count)

    async def _merge_giveaways_data(self, original_data: GiveawayData,
                                    name: Optional[str], description: Optional[str],
                                    utc_end_date: Optional[datetime],
                                    color: Optional[discord.Colour],
                                    max_entries: Optional[int],
                                    winners_count: Optional[int]) -> GiveawayData:
        "Update a given giveaway data with new values"
        if name is not None:
            original_data["name"] = name
        if description is not None:
            original_data["description"] = description
        if utc_end_date is not None:
            original_data["ends_at"] = utc_end_date.astimezone(timezone.utc)
        if color is not None:
            original_data["color"] = color.value
        if max_entries is not None:
            original_data["max_entries"] = max_entries
        if winners_count is not None:
            original_data["winners_count"] = winners_count
        return original_data

    async def db_create_giveaway(self, giveaway: GiveawayData):
        "Add a new giveaway to the database"
        logs.info(f"Creating giveaway {giveaway['id']}")
        allay.Database.query(
            "INSERT INTO `giveaways` VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                giveaway["id"], giveaway["guild_id"], giveaway["channel_id"],
                giveaway["message_id"], giveaway["name"], giveaway["description"],
                giveaway["color"], giveaway["max_entries"], giveaway["winners_count"],
                giveaway["ends_at"], giveaway["ended"]
            )
        )

    async def db_get_giveaways(self) -> list[GiveawayData]:
        """Get a list of all giveaways in the database"""
        result = allay.Database.query("SELECT * FROM `giveaways`", astuple=False)
        for row in result: # pylint: disable=not-an-iterable
            row["ends_at"] = datetime.fromisoformat(row["ends_at"])
        return result # type: ignore

    async def db_get_active_giveaways(self) -> list[GiveawayData]:
        """Get a list of active giveaways (ie. not 'ended')
        Note: this may include giveaways that have a past end date but have not been marked
            as ended yet"""
        result = allay.Database.query("SELECT * FROM `giveaways` WHERE ended = 0", astuple=False)
        for row in result: # pylint: disable=not-an-iterable
            row["ends_at"] = datetime.fromisoformat(row["ends_at"])
        return result # type: ignore

    async def db_get_giveaway(self, giveaway_id: str) -> Optional[GiveawayData]:
        """Get a giveaway from the database"""
        result = allay.Database.query(
            "SELECT * FROM `giveaways` WHERE id = ?",
            (giveaway_id,),
            fetchone=True,
            astuple=False
        )
        # pylint: disable=unsubscriptable-object,unsupported-assignment-operation
        result["ends_at"] = datetime.fromisoformat(result["ends_at"])
        return result # type: ignore

    async def db_get_giveaways_participants(self, giveaway_id: str) -> list[GiveawayParticipant]:
        """Get a list of participants for a giveaway"""
        result = allay.Database.query(
            "SELECT * FROM `giveaway_entries` WHERE giveaway_id = ?",
            (giveaway_id,),
            astuple=False
        )
        return result # type: ignore

    async def db_check_giveaway_participant(self, giveaway_id: str, user_id: int) -> bool:
        """Check if a user is already participating in a giveaway"""
        result = allay.Database.query(
            "SELECT EXISTS \
            (SELECT 1 FROM `giveaway_entries` WHERE giveaway_id = ? AND user_id = ?)",
            (giveaway_id, user_id),
            astuple=True,
            fetchone=True
        )
        return bool(result[0]) # pylint: disable=unsubscriptable-object

    async def db_add_giveaway_participant(self, giveaway_id: str, user_id: int):
        """Add a participant to a giveaway"""
        logs.info(f"Adding participant {user_id} to giveaway {giveaway_id}")
        allay.Database.query(
            "INSERT INTO `giveaway_entries` (`giveaway_id`, `user_id`) VALUES (?, ?)",
            (giveaway_id, user_id)
        )

    async def db_edit_giveaway(self, giveaway_id: str, data: GiveawayData):
        "Edit a giveaway in the database"
        logs.info(f"Editing giveaway {giveaway_id}")
        allay.Database.query(
            "UPDATE `giveaways` SET name = ?, description = ?, color = ?, \
                max_entries = ?, winners_count = ?, ends_at = ? WHERE id = ?",
            (
                data["name"], data["description"], data["color"],
                data["max_entries"], data["winners_count"], data["ends_at"],
                giveaway_id
            )
        )

    async def db_close_giveaway(self, giveaway_id: str, winners: list[int]):
        "Mark a giveaway as ended and register the winners"
        logs.info(f"Closing giveaway {giveaway_id}")
        # mark giveaway as closed
        allay.Database.query(
            "UPDATE `giveaways` SET ended = 1 WHERE id = ?",
            (giveaway_id,)
        )
        # mark winner participants as winners, others and non-winners
        query_users_list = ', '.join('?' for _ in winners)
        allay.Database.query(
            f"UPDATE `giveaway_entries` \
            SET winner = CASE WHEN user_id IN ({query_users_list}) THEN 1 ELSE 0 END \
            WHERE giveaway_id = ?",
            (*winners, giveaway_id)
        )

    async def db_delete_giveaway(self, giveaway_id: str):
        "Permanently delete a giveaway from the database"
        logs.info(f"Deleting giveaway {giveaway_id}")
        allay.Database.query(
            "DELETE FROM `giveaways` WHERE id = ?",
            (giveaway_id,)
        )
        allay.Database.query(
            "DELETE FROM `giveaway_entries` WHERE giveaway_id = ?",
            (giveaway_id,)
        )
