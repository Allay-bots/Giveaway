# Allay - Giveaway plugin

This plugin allows your Allay bot to run giveaways in your servers.

The `/giveaways` slash command will be added in your servers, and will be restricted by default to users with the `Manage Server` permission. You can change this in your server integrations settings.

## Usage

### Creating a giveaway

To create a giveaway, use the `/giveaways create` slash command.

**Required parameters:**
- name: The name of the giveaway. You may have multiple giveaways with the same name, but their name will be used in lists and command autocompletion.
- description: The description of the giveaway, which will be displayed in the giveaway message.
- duration: The duration of the giveaway, in `3d 4h 5m` format.

**Optional parameters:**
- channel: The channel in which the giveaway will be created. If not specified, the current channel will be used.
- color: The color of the giveaway embed. Must be a valid hex color code, or some default color name supported by discord.py (see the [complete list](https://discordpy.readthedocs.io/en/stable/api.html#colour)).
- max_entries: The maximum number of users that can enter the giveaway. If not specified, there will be no limit.
- winners_count: The number of winners that will be picked. If not specified, there will be only one winner.


### Rerolling a giveaway

To reroll a giveaway, use the `/giveaways reroll` slash command with the giveaway ID as parameter (autocompletion is available).

Rerolling an ended giveaway will pick new winners for it (following the same rules as the original giveaway), and edit the giveaway message to display the new winners.


### Delete a giveaway

Ended giveaways will not automatically be deleted, and will continue to appear in giveaways list and autocompletion.

To delete a giveaway, use the `/giveaways delete` slash command with the giveaway ID as parameter (autocompletion is available).


## Code

### Database

Two new tables will be added to the bot database:
- `giveaways`: Contains the giveaways data (with data such as the giveaway name, description, duration, guild ID, etc.)
- `giveaway_entries`: Contains the giveaway entries data (with data such as the user ID, giveaway ID, and if this user won the giveaway)


### Adding a verification system when picking winners

By default, no verification will be made when picking a giveaway winners. This means for example that if a user leaves the server after entering a giveaway, they will still be able to win it.

You can add your own verification algorithm by editing the `src/custom_participants_verification.py` file. This file must contain a `verify_participants` function, which will be called when picking winners for a giveaway.

The `verify_participants` function takes as third argument a list of GiveawayParticipant objects, which is a fancy name for a dictionnary containing the following data:
- `giveaway`: The ID of the guild
- `user_id`: The ID of the user
- `winner`: A boolean indicating if the user won the giveaway (may be true in case of a reroll)
- `created_at`: The date at which the user entered the giveaway

The function should return a list of user IDs, which will be the potential winners of the giveaway.

The most basic verification function, which won't actually verify anything and will allow everyone to be picked, would look like this:
```py
async def verify_participants(bot: allay.Bot,
                              giveaway: GiveawayData,
                              participants: list[GiveawayParticipant]
                              ) -> list[int]:
    return [participant["user_id"] for participant in participants]
``````