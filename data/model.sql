-- Ce programme est régi par la licence CeCILL soumise au droit français et
-- respectant les principes de diffusion des logiciels libres. Vous pouvez
-- utiliser, modifier et/ou redistribuer ce programme sous les conditions
-- de la licence CeCILL diffusée sur le site "http://www.cecill.info".

CREATE TABLE IF NOT EXISTS `giveaways` (
    `id` VARCHAR(50) PRIMARY KEY,
    `guild_id` BIGINT NOT NULL,
    `channel_id` BIGINT NOT NULL,
    `message_id` BIGINT NOT NULL,
    `name` TEXT NOT NULL,
    `description` TEXT NOT NULL,
    `color` INTEGER NOT NULL,
    `max_entries` INTEGER DEFAULT NULL,
    `winners_count` INTEGER NOT NULL,
    `ends_at` DATETIME NOT NULL,
    `ended` BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_giveaways ON `giveaways` (`id`);

CREATE TABLE IF NOT EXISTS `giveaway_entries` (
    `giveaway_id` INTEGER NOT NULL,
    `user_id` BIGINT NOT NULL,
    `winner` BOOLEAN NOT NULL DEFAULT false,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`giveaway_id`, `user_id`)
);
CREATE INDEX IF NOT EXISTS idx_giveaway_entries ON `giveaway_entries` (`giveaway_id`);
CREATE UNIQUE INDEX IF NOT EXISTS idx_giveaway_entries_unique ON `giveaway_entries` (`giveaway_id`, `user_id`);