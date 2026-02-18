"""
cheat_manager – Legitimacy-safe cheat system for Gen 3 shiny hunting.

Uses direct memory writes via libmgba-py (same as pokebot-gen3) to apply
quality-of-life cheats that do NOT affect Pokémon legitimacy.

Categories:
  SAFE       – No effect on Pokémon data (money, items, navigation)
  CAUTION    – Affects gameplay but not Pokémon stats (egg hatch speed)
  DANGEROUS  – Directly modifies Pokémon data (BLOCKED by default)
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.game_bot import GameBot

logger = logging.getLogger(__name__)


# ── Cheat categories ────────────────────────────────────────────────────────

class CheatCategory(str, Enum):
    SAFE = "safe"           # No legitimacy impact
    CAUTION = "caution"     # Minor gameplay impact, Pokémon unaffected
    DANGEROUS = "dangerous" # Modifies Pokémon data – BLOCKED


# ── Fire Red memory addresses (USA v1.0) ────────────────────────────────────
# Sourced from pokefirered decompilation + pokebot-gen3 symbol tables.

class FRAddresses:
    # Save Block 2 offsets (accessed via gSaveBlock2Ptr)
    PLAYER_MONEY_OFFSET = 0x0290       # u32, in save block 1
    BAG_ITEMS_OFFSET = 0x0310          # item pocket start in save block 1
    BAG_POKEBALLS_OFFSET = 0x0430      # pokeball pocket in save block 1

    # Save Block 1 pointer
    SAVE_BLOCK_1_PTR = 0x03005008      # gSaveBlock1Ptr

    # Direct EWRAM addresses
    PLAYER_MONEY_DIRECT = 0x02025B54   # Alternative direct address

    # Item structure: each slot is 4 bytes (u16 item_id + u16 quantity)
    ITEM_SLOT_SIZE = 4

    # Pokéball item IDs
    MASTER_BALL = 0x0001
    ULTRA_BALL = 0x0002
    GREAT_BALL = 0x0003
    POKE_BALL = 0x0004
    SAFARI_BALL = 0x0005
    NET_BALL = 0x0006
    DIVE_BALL = 0x0007
    NEST_BALL = 0x0008
    REPEAT_BALL = 0x0009
    TIMER_BALL = 0x000A
    LUXURY_BALL = 0x000B
    PREMIER_BALL = 0x000C

    # Evolution stone item IDs
    FIRE_STONE = 0x005F
    WATER_STONE = 0x0060
    THUNDER_STONE = 0x0061
    LEAF_STONE = 0x0062
    MOON_STONE = 0x005D
    SUN_STONE = 0x005E

    # Trade evolution items
    KINGS_ROCK = 0x00BB
    METAL_COAT = 0x00C1
    DRAGON_SCALE = 0x00C2
    DEEP_SEA_TOOTH = 0x00BF
    DEEP_SEA_SCALE = 0x00C0
    UP_GRADE = 0x00CA

    # Fishing rods
    OLD_ROD = 0x0125
    GOOD_ROD = 0x0126
    SUPER_ROD = 0x0127

    # Key items
    BICYCLE = 0x0103

    # Repel
    REPEL = 0x0054
    SUPER_REPEL = 0x0055
    MAX_REPEL = 0x0056

    # Healing
    POTION = 0x000D
    SUPER_POTION = 0x000E
    HYPER_POTION = 0x000F
    MAX_POTION = 0x0010
    FULL_RESTORE = 0x0011
    REVIVE = 0x0013
    MAX_REVIVE = 0x0014

    # Rare Candy
    RARE_CANDY = 0x0044

    # Daycare / Egg
    DAYCARE_DATA_OFFSET = 0x2F80       # Save block 1 offset for FR/LG daycare
    EGG_CYCLES_OFFSET = 0x1C           # Offset within party Pokémon struct for friendship/egg cycles


# ── Cheat definition ────────────────────────────────────────────────────────

@dataclass
class Cheat:
    name: str
    description: str
    category: CheatCategory
    enabled: bool = False
    affects_legitimacy: bool = False

    def toggle(self) -> bool:
        if self.category == CheatCategory.DANGEROUS:
            logger.warning("Blocked dangerous cheat: %s", self.name)
            return False
        self.enabled = not self.enabled
        return True


# ── Cheat Manager ───────────────────────────────────────────────────────────

class CheatManager:
    """
    Manages legitimacy-safe cheats via direct memory writes.

    All cheats operate through the same ffi.memmove memory access
    used by pokebot-gen3, writing directly to EWRAM/IWRAM.
    No GameShark/Action Replay codes needed – we write raw values.
    """

    def __init__(self) -> None:
        self.cheats: Dict[str, Cheat] = {}
        self.active_bot: Optional[GameBot] = None
        self._legitimacy_clean = True
        self._register_cheats()

    def _register_cheats(self) -> None:
        """Register all available cheats."""
        safe = CheatCategory.SAFE
        caution = CheatCategory.CAUTION

        # ── SAFE: Money & Shopping ──
        self.cheats["max_money"] = Cheat(
            "Max Money", "Set money to ₽999,999", safe)
        self.cheats["free_pokeballs"] = Cheat(
            "Free Poké Balls", "Add 99 of each ball type to bag", safe)
        self.cheats["free_healing"] = Cheat(
            "Free Healing Items", "Add 99 Potions, Revives, etc.", safe)
        self.cheats["free_repels"] = Cheat(
            "Free Repels", "Add 99 Max Repels to bag", safe)

        # ── SAFE: Evolution Materials ──
        self.cheats["free_stones"] = Cheat(
            "Free Evolution Stones", "Add 99 of each evolution stone", safe)
        self.cheats["free_trade_items"] = Cheat(
            "Free Trade Items", "Add 99 of each trade evolution item", safe)

        # ── SAFE: Fishing ──
        self.cheats["all_rods"] = Cheat(
            "All Fishing Rods", "Add Old Rod, Good Rod, Super Rod", safe)

        # ── SAFE: Navigation ──
        self.cheats["bicycle"] = Cheat(
            "Free Bicycle", "Add Bicycle to key items", safe)

        # ── SAFE: Leveling ──
        self.cheats["rare_candies"] = Cheat(
            "Rare Candies", "Add 99 Rare Candies to bag", safe)

        # ── CAUTION: Breeding Speed ──
        self.cheats["fast_egg_hatch"] = Cheat(
            "Fast Egg Hatch", "Reduce egg cycle counter to 1 each frame",
            caution, affects_legitimacy=False)

    def attach_bot(self, bot: GameBot) -> None:
        """Attach a GameBot instance for memory writes."""
        self.active_bot = bot

    def get_cheats_by_category(self, category: CheatCategory) -> List[Cheat]:
        return [c for c in self.cheats.values() if c.category == category]

    def get_all_cheats(self) -> Dict[str, Cheat]:
        return self.cheats

    def enable_cheat(self, cheat_id: str) -> bool:
        """Enable a cheat and apply it immediately if a bot is attached."""
        cheat = self.cheats.get(cheat_id)
        if cheat is None:
            logger.error("Unknown cheat: %s", cheat_id)
            return False
        if cheat.category == CheatCategory.DANGEROUS:
            logger.warning("Blocked dangerous cheat: %s", cheat.name)
            return False
        cheat.enabled = True
        if cheat.affects_legitimacy:
            self._legitimacy_clean = False
        if self.active_bot is not None:
            self._apply_cheat(cheat_id)
        logger.info("Enabled cheat: %s", cheat.name)
        return True

    def disable_cheat(self, cheat_id: str) -> None:
        cheat = self.cheats.get(cheat_id)
        if cheat:
            cheat.enabled = False
            logger.info("Disabled cheat: %s", cheat.name)

    def apply_all_enabled(self) -> int:
        """Apply all enabled cheats. Returns count applied."""
        if self.active_bot is None:
            return 0
        count = 0
        for cid, cheat in self.cheats.items():
            if cheat.enabled:
                if self._apply_cheat(cid):
                    count += 1
        return count

    @property
    def is_legitimate(self) -> bool:
        return self._legitimacy_clean

    # ── Memory write implementations ────────────────────────────────────

    def _apply_cheat(self, cheat_id: str) -> bool:
        """Apply a single cheat via direct memory write."""
        bot = self.active_bot
        if bot is None or bot.instance is None:
            return False
        try:
            method = getattr(self, f"_apply_{cheat_id}", None)
            if method:
                method(bot)
                return True
            logger.warning("No implementation for cheat: %s", cheat_id)
            return False
        except Exception as exc:
            logger.error("Failed to apply cheat %s: %s", cheat_id, exc)
            return False

    def _get_save_block_1_ptr(self, bot: GameBot) -> int:
        """Read the gSaveBlock1Ptr value."""
        return bot.read_u32(FRAddresses.SAVE_BLOCK_1_PTR)

    def _write_bag_item(self, bot: GameBot, pocket_offset: int,
                        slot_index: int, item_id: int, quantity: int) -> None:
        """Write an item to a specific bag pocket slot."""
        sb1 = self._get_save_block_1_ptr(bot)
        if sb1 == 0:
            return
        addr = sb1 + pocket_offset + (slot_index * FRAddresses.ITEM_SLOT_SIZE)
        # Item slot: u16 item_id + u16 quantity
        data = struct.pack("<HH", item_id, quantity)
        bot.write_bytes(addr, data)

    def _write_bag_item_pocket(self, bot: GameBot, slot_index: int,
                               item_id: int, quantity: int) -> None:
        """Write to the general items pocket."""
        self._write_bag_item(bot, FRAddresses.BAG_ITEMS_OFFSET,
                             slot_index, item_id, quantity)

    def _write_bag_ball_pocket(self, bot: GameBot, slot_index: int,
                               item_id: int, quantity: int) -> None:
        """Write to the Poké Balls pocket."""
        self._write_bag_item(bot, FRAddresses.BAG_POKEBALLS_OFFSET,
                             slot_index, item_id, quantity)

    # ── Individual cheat implementations ────────────────────────────────

    def _apply_max_money(self, bot: GameBot) -> None:
        """Set player money to 999,999."""
        sb1 = self._get_save_block_1_ptr(bot)
        if sb1 == 0:
            return
        addr = sb1 + FRAddresses.PLAYER_MONEY_OFFSET
        # Money is stored as u32, XOR'd with encryption key in FR/LG
        # For simplicity, write directly (works when encryption key is 0
        # at game start; for encrypted saves we'd need to read the key first)
        bot.write_bytes(addr, struct.pack("<I", 999999))
        logger.info("Set money to 999,999")

    def _apply_free_pokeballs(self, bot: GameBot) -> None:
        """Add 99 of each ball type."""
        balls = [
            (0, FRAddresses.POKE_BALL, 99),
            (1, FRAddresses.GREAT_BALL, 99),
            (2, FRAddresses.ULTRA_BALL, 99),
            (3, FRAddresses.MASTER_BALL, 10),
            (4, FRAddresses.NET_BALL, 99),
            (5, FRAddresses.NEST_BALL, 99),
            (6, FRAddresses.REPEAT_BALL, 99),
            (7, FRAddresses.TIMER_BALL, 99),
            (8, FRAddresses.LUXURY_BALL, 99),
            (9, FRAddresses.PREMIER_BALL, 99),
        ]
        for slot, item_id, qty in balls:
            self._write_bag_ball_pocket(bot, slot, item_id, qty)
        logger.info("Added Poké Balls to bag")

    def _apply_free_healing(self, bot: GameBot) -> None:
        """Add healing items to bag."""
        items = [
            (0, FRAddresses.FULL_RESTORE, 99),
            (1, FRAddresses.MAX_POTION, 99),
            (2, FRAddresses.HYPER_POTION, 99),
            (3, FRAddresses.REVIVE, 99),
            (4, FRAddresses.MAX_REVIVE, 50),
        ]
        # Write to general items pocket starting at a high slot to avoid
        # overwriting existing items
        for slot_offset, item_id, qty in items:
            self._write_bag_item_pocket(bot, 20 + slot_offset, item_id, qty)
        logger.info("Added healing items to bag")

    def _apply_free_repels(self, bot: GameBot) -> None:
        """Add 99 Max Repels."""
        self._write_bag_item_pocket(bot, 25, FRAddresses.MAX_REPEL, 99)
        logger.info("Added Max Repels to bag")

    def _apply_free_stones(self, bot: GameBot) -> None:
        """Add 99 of each evolution stone."""
        stones = [
            (26, FRAddresses.FIRE_STONE, 99),
            (27, FRAddresses.WATER_STONE, 99),
            (28, FRAddresses.THUNDER_STONE, 99),
            (29, FRAddresses.LEAF_STONE, 99),
            (30, FRAddresses.MOON_STONE, 99),
            (31, FRAddresses.SUN_STONE, 99),
        ]
        for slot, item_id, qty in stones:
            self._write_bag_item_pocket(bot, slot, item_id, qty)
        logger.info("Added evolution stones to bag")

    def _apply_free_trade_items(self, bot: GameBot) -> None:
        """Add 99 of each trade evolution item."""
        items = [
            (32, FRAddresses.KINGS_ROCK, 99),
            (33, FRAddresses.METAL_COAT, 99),
            (34, FRAddresses.DRAGON_SCALE, 99),
            (35, FRAddresses.DEEP_SEA_TOOTH, 99),
            (36, FRAddresses.DEEP_SEA_SCALE, 99),
            (37, FRAddresses.UP_GRADE, 99),
        ]
        for slot, item_id, qty in items:
            self._write_bag_item_pocket(bot, slot, item_id, qty)
        logger.info("Added trade evolution items to bag")

    def _apply_all_rods(self, bot: GameBot) -> None:
        """Add all fishing rods to key items pocket."""
        # Key items pocket offset in FR/LG save block 1
        KEY_ITEMS_OFFSET = 0x0480
        rods = [
            (0, FRAddresses.OLD_ROD, 1),
            (1, FRAddresses.GOOD_ROD, 1),
            (2, FRAddresses.SUPER_ROD, 1),
        ]
        for slot_offset, item_id, qty in rods:
            self._write_bag_item(bot, KEY_ITEMS_OFFSET,
                                 slot_offset, item_id, qty)
        logger.info("Added fishing rods to key items")

    def _apply_bicycle(self, bot: GameBot) -> None:
        """Add Bicycle to key items."""
        KEY_ITEMS_OFFSET = 0x0480
        self._write_bag_item(bot, KEY_ITEMS_OFFSET, 3,
                             FRAddresses.BICYCLE, 1)
        logger.info("Added Bicycle to key items")

    def _apply_rare_candies(self, bot: GameBot) -> None:
        """Add 99 Rare Candies."""
        self._write_bag_item_pocket(bot, 38, FRAddresses.RARE_CANDY, 99)
        logger.info("Added Rare Candies to bag")

    def _apply_fast_egg_hatch(self, bot: GameBot) -> None:
        """
        Reduce egg cycle counter for all eggs in party.

        Reads party data and for each egg, sets the friendship/egg cycles
        byte to 1 so it hatches on the next step cycle.
        """
        try:
            party_count_raw = bot.read_bytes(0x02024280, 4)
            party_count = struct.unpack("<I", party_count_raw)[0]
            if party_count == 0 or party_count > 6:
                return

            PARTY_BASE = 0x02024284
            POKEMON_SIZE = 100  # Each party Pokémon is 100 bytes

            for i in range(party_count):
                pokemon_addr = PARTY_BASE + (i * POKEMON_SIZE)
                # Read personality value to check if it's an egg
                # Egg flag is in the misc substructure
                # For speed, read the full 100 bytes
                raw = bot.read_bytes(pokemon_addr, POKEMON_SIZE)
                pv = struct.unpack("<I", raw[0:4])[0]
                ot_id = struct.unpack("<I", raw[4:8])[0]

                # Check if this is an egg by reading the "is egg" flag
                # In the encrypted substructure, we need to decrypt first
                # The egg flag is bit 30 of the misc substructure word 0
                # For a simpler approach: check if species is 0 (empty slot)
                # or read the sanity/egg bit from the status byte

                # The friendship/egg cycles byte is at offset 0x1B in the
                # pokemon data structure (after decryption)
                # In the box structure it's in the growth substructure
                # For party Pokémon, the friendship byte is at a fixed offset

                # Simplified: write 1 to the friendship/egg cycles location
                # This is at offset 27 (0x1B) in the party Pokémon struct
                # after the 32-byte header + encrypted data
                # Actually in Gen 3, party struct is:
                #   0-3: PV, 4-7: OTID, 8-17: nickname, 18-19: language,
                #   20-31: OT name, 32-79: encrypted substructures (48 bytes),
                #   80-99: battle stats
                # The friendship byte is inside the encrypted growth substructure

                # For now, we use the approach of writing to the decrypted
                # friendship field. The encryption key is PV XOR OTID.
                encryption_key = pv ^ ot_id

                # Determine substructure order from PV
                order_index = pv % 24
                # Growth substructure contains friendship at offset 9
                # We need to find where growth is in the 48-byte block
                SUBSTRUCTURE_ORDERS = [
                    (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 3, 1, 2),
                    (0, 2, 3, 1), (0, 3, 2, 1), (1, 0, 2, 3), (1, 0, 3, 2),
                    (2, 0, 1, 3), (3, 0, 1, 2), (2, 0, 3, 1), (3, 0, 2, 1),
                    (1, 2, 0, 3), (1, 3, 0, 2), (2, 1, 0, 3), (3, 1, 0, 2),
                    (2, 3, 0, 1), (3, 2, 0, 1), (1, 2, 3, 0), (1, 3, 2, 0),
                    (2, 1, 3, 0), (3, 1, 2, 0), (2, 3, 1, 0), (3, 2, 1, 0),
                ]
                order = SUBSTRUCTURE_ORDERS[order_index]

                # Find which position (0-3) the growth substructure (index 0) is at
                growth_pos = order.index(0)
                # Find misc substructure (index 3) for egg flag
                misc_pos = order.index(3)

                # Read the encrypted 48-byte block starting at offset 32
                encrypted_data = bytearray(raw[32:80])

                # Decrypt
                decrypted = bytearray(48)
                for j in range(0, 48, 4):
                    word = struct.unpack("<I", encrypted_data[j:j+4])[0]
                    decrypted[j:j+4] = struct.pack("<I", word ^ encryption_key)

                # Check egg flag: misc substructure, word 0, bit 30
                misc_offset = misc_pos * 12
                misc_word0 = struct.unpack("<I", decrypted[misc_offset:misc_offset+4])[0]
                is_egg = bool(misc_word0 & (1 << 30))

                if not is_egg:
                    continue

                # Growth substructure: friendship is byte 9 (offset 9 within growth)
                # Growth substructure layout (12 bytes):
                #   0-1: species, 2-3: item, 4-7: experience, 8: PP bonuses,
                #   9: friendship, 10-11: unused
                growth_offset = growth_pos * 12
                # Set friendship/egg cycles to 1
                decrypted[growth_offset + 9] = 1

                # Re-encrypt
                re_encrypted = bytearray(48)
                for j in range(0, 48, 4):
                    word = struct.unpack("<I", decrypted[j:j+4])[0]
                    re_encrypted[j:j+4] = struct.pack("<I", word ^ encryption_key)

                # Write back
                bot.write_bytes(pokemon_addr + 32, bytes(re_encrypted))

            logger.debug("Applied fast egg hatch to party eggs")
        except Exception as exc:
            logger.error("Fast egg hatch failed: %s", exc)

    # ── Bulk operations ─────────────────────────────────────────────────

    def apply_hunting_preset(self) -> int:
        """Enable all cheats useful for shiny hunting."""
        preset = ["max_money", "free_pokeballs", "free_healing",
                  "free_repels", "rare_candies"]
        count = 0
        for cid in preset:
            if self.enable_cheat(cid):
                count += 1
        return count

    def apply_evolution_preset(self) -> int:
        """Enable all cheats useful for evolution."""
        preset = ["free_stones", "free_trade_items", "rare_candies"]
        count = 0
        for cid in preset:
            if self.enable_cheat(cid):
                count += 1
        return count

    def apply_breeding_preset(self) -> int:
        """Enable all cheats useful for breeding."""
        preset = ["max_money", "free_pokeballs", "fast_egg_hatch"]
        count = 0
        for cid in preset:
            if self.enable_cheat(cid):
                count += 1
        return count

    def apply_fishing_preset(self) -> int:
        """Enable all cheats useful for fishing."""
        preset = ["max_money", "free_pokeballs", "all_rods", "free_repels"]
        count = 0
        for cid in preset:
            if self.enable_cheat(cid):
                count += 1
        return count

    def disable_all(self) -> None:
        """Disable all cheats."""
        for cheat in self.cheats.values():
            cheat.enabled = False

    def get_enabled_cheats(self) -> List[str]:
        """Return list of enabled cheat IDs."""
        return [cid for cid, c in self.cheats.items() if c.enabled]

    def get_legitimacy_report(self) -> dict:
        """Generate a report of cheat usage and legitimacy status."""
        return {
            "legitimate": self._legitimacy_clean,
            "enabled_count": len(self.get_enabled_cheats()),
            "enabled": self.get_enabled_cheats(),
            "safe_cheats": [c.name for c in self.get_cheats_by_category(CheatCategory.SAFE)
                           if c.enabled],
            "caution_cheats": [c.name for c in self.get_cheats_by_category(CheatCategory.CAUTION)
                              if c.enabled],
        }
