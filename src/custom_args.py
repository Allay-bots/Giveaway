import re
from datetime import datetime, timezone
from inspect import signature

import discord
from dateutil.relativedelta import relativedelta
from discord import app_commands


# pylint: disable=abstract-method
class ColorTransformer(app_commands.Transformer):
    """Transform a string into a discord.Color"""

    # pylint: disable=arguments-differ
    async def transform(self, interaction: discord.Interaction, value: str) -> discord.Colour:
        if value == "random":
            return discord.Colour.random()
        try:
            return discord.Colour.from_str(value)
        except ValueError:
            # try to convert it from a color name
            if len(value) < 3:
                raise ValueError("Invalid color name") from None
            if not hasattr(discord.Colour, value) or not callable(getattr(discord.Colour, value)):
                raise ValueError("Invalid color name") from None
            method = getattr(discord.Colour, value)
            if len(signature(method).parameters) != 0:
                raise ValueError("Invalid color name") from None
            return method()

ColorOption = app_commands.Transform[discord.Color, ColorTransformer]


# pylint: disable=abstract-method
class DurationTransformer(app_commands.Transformer):
    """Transform a string into a datetime.timedelta"""

    # pylint: disable=arguments-differ
    async def transform(self, interaction: discord.Interaction, value: str) -> int:
        "Converts a string to a duration in seconds."
        duration = 0
        found = False
        symbols: list[tuple[str, int]] = [
            ('w', 604800),
            ('d', 86400),
            ('h', 3600),
            ('m', 60),
            ('min', 60)
        ]
        for symbol, coef in symbols:
            if match := re.search(r'^(\d+)'+symbol+'$', value):
                duration += int(match.group(1)) * coef
                found = True
        if match := re.search(r'^(\d+)h(\d+)m?$', value):
            duration += int(match.group(1))*3600 + int(match.group(2))*60
            found = True
        if match := re.search(r'^(\d+) ?mo(?:nths?)?$', value):
            now = then = datetime.now(timezone.utc)
            then += relativedelta(months=int(match.group(1)))
            duration += (then - now).total_seconds()
            found = True
        if match := re.search(r'^(\d+) ?y(?:ears?)?$', value):
            now = then = datetime.now(timezone.utc)
            then += relativedelta(years=int(match.group(1)))
            duration += (then - now).total_seconds()
            found = True
        if not found:
            raise ValueError("Invalid duration")
        return round(duration)

DurationOption = app_commands.Transform[int, DurationTransformer]

# pylint: disable=abstract-method
class DateTransformer(app_commands.Transformer):
    """Transform a string into a UTC datetime.datetime"""

    # pylint: disable=arguments-differ
    async def transform(self, interaction: discord.Interaction, value: str) -> datetime:
        "Converts a string to a datetime.datetime."
        try:
            date = datetime.fromisoformat(value)
        except ValueError:
            try:
                date = datetime.strptime(value, "%Y-%m-%d %H:%M")
            except ValueError:
                try:
                    date = datetime.strptime(value, "%d/%m/%Y %H:%M")
                except ValueError:
                    raise ValueError("Invalid date") from None
        if not date.tzinfo:
            date = date.replace(tzinfo=timezone.utc)
        return date

DateOption = app_commands.Transform[datetime, DateTransformer]
