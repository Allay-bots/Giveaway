from datetime import datetime
from typing import Optional, TypedDict


class GiveawayToSendData(TypedDict):
    "Data for a giveaway instance stored in Firestore"
    id: str
    guild_id: int
    channel_id: int
    name: str
    description: str
    color: int
    max_entries: Optional[int]
    winners_count: int
    ends_at: datetime
    ended: bool

class GiveawayData(TypedDict):
    "Data for a giveaway instance stored in database"
    id: str
    guild_id: int
    channel_id: int
    message_id: int
    name: str
    description: str
    color: int
    max_entries: Optional[int]
    winners_count: int
    ends_at: datetime
    ended: bool

class GiveawayParticipant(TypedDict):
    "Data for a giveaway participant stored in database"
    giveaway_id: int
    user_id: int
    winner: bool
    created_at: datetime
