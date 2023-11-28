import os

from LRFutils import logs

import allay

version = "0.0.1"
icon = "🎁"
name = "Giveaways"

async def _create_verification_file():
    "Check if the `src/custom_participants_verification.py` file exists and create it if not"
    absolute_dir_path = os.path.dirname(__file__)
    destination_file = os.path.join(absolute_dir_path, "src/custom_participants_verification.py")
    
    # check if required file exists
    if os.path.isfile(destination_file):
        return
    logs.info("The file `src/custom_participants_verification.py` does not exist, creating it...")
    
    # duplicate file from example
    example_file = os.path.join(absolute_dir_path,
                                "src/custom_participants_verification.py.example")
    with open(example_file, "r", encoding="utf8") as origin:
        content = origin.read()
    with open(destination_file, "w", encoding="utf8") as destination:
        destination.write(content)


async def setup(bot: allay.Bot):
    "Load the Giveaways cog"
    logs.info(f"Loading {icon} {name} v{version}...")
    await _create_verification_file()

    from .src.discord_cog import GiveawaysCog # pylint: disable=import-outside-toplevel
    await bot.add_cog(GiveawaysCog(bot), icon=icon, display_name=name)
