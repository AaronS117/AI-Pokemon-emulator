"""Unit tests for modules.emulator_api – data classes and pure logic."""
import pytest
from modules.emulator_api import (
    PaletteColor, OAMEntry, SaveStateSnapshot,
    GBA_MEMORY_MAP, PALETTE_BG_OFFSET, PALETTE_OBJ_OFFSET,
    OAM_ENTRY_SIZE, OAM_MAX_ENTRIES,
)


class TestPaletteColor:
    def test_from_u16_white(self):
        c = PaletteColor.from_u16(0x7FFF)
        assert c.r == 31
        assert c.g == 31
        assert c.b == 31

    def test_from_u16_black(self):
        c = PaletteColor.from_u16(0x0000)
        assert c.r == 0
        assert c.g == 0
        assert c.b == 0

    def test_from_u16_red(self):
        c = PaletteColor.from_u16(0x001F)
        assert c.r == 31
        assert c.g == 0
        assert c.b == 0

    def test_from_u16_green(self):
        c = PaletteColor.from_u16(0x03E0)
        assert c.r == 0
        assert c.g == 31
        assert c.b == 0

    def test_from_u16_blue(self):
        c = PaletteColor.from_u16(0x7C00)
        assert c.r == 0
        assert c.g == 0
        assert c.b == 31

    def test_to_rgb_white(self):
        c = PaletteColor.from_u16(0x7FFF)
        assert c.to_rgb() == (248, 248, 248)  # 31 << 3 = 248

    def test_to_rgb_black(self):
        c = PaletteColor.from_u16(0x0000)
        assert c.to_rgb() == (0, 0, 0)

    def test_raw_preserved(self):
        c = PaletteColor.from_u16(0x1234)
        assert c.raw == 0x1234


class TestOAMEntry:
    def test_position(self):
        oam = OAMEntry(attr0=0x0050, attr1=0x00A0)
        assert oam.y == 0x50
        assert oam.x == 0xA0

    def test_tile_index(self):
        oam = OAMEntry(attr2=0x0123)
        assert oam.tile_index == 0x123

    def test_palette_num(self):
        oam = OAMEntry(attr2=0xF000)
        assert oam.palette_num == 0xF

    def test_priority(self):
        oam = OAMEntry(attr2=0x0C00)
        assert oam.priority == 3

    def test_h_flip(self):
        oam = OAMEntry(attr1=0x1000)
        assert oam.h_flip is True
        oam2 = OAMEntry(attr1=0x0000)
        assert oam2.h_flip is False

    def test_v_flip(self):
        oam = OAMEntry(attr1=0x2000)
        assert oam.v_flip is True

    def test_disabled(self):
        # Disabled: bit 9 set, bit 8 clear
        oam = OAMEntry(attr0=0x0200)
        assert oam.is_disabled is True
        # Not disabled: both bits set (affine double)
        oam2 = OAMEntry(attr0=0x0300)
        assert oam2.is_disabled is False
        # Not disabled: neither set
        oam3 = OAMEntry(attr0=0x0000)
        assert oam3.is_disabled is False

    def test_shape_size(self):
        oam = OAMEntry(attr0=0xC000, attr1=0xC000)
        assert oam.shape == 3
        assert oam.size == 3


class TestSaveStateSnapshot:
    def test_creation(self):
        snap = SaveStateSnapshot(data=b'\x00' * 100, frame_number=42, label="test")
        assert snap.data == b'\x00' * 100
        assert snap.frame_number == 42
        assert snap.label == "test"

    def test_default_label(self):
        snap = SaveStateSnapshot(data=b'', frame_number=0)
        assert snap.label == ""


class TestGBAMemoryMap:
    def test_all_regions_present(self):
        expected = ["bios", "ewram", "iwram", "io", "palette",
                    "vram", "oam", "rom", "sram"]
        for region in expected:
            assert region in GBA_MEMORY_MAP

    def test_region_tuples(self):
        for name, (offset, size) in GBA_MEMORY_MAP.items():
            assert offset >= 0, f"{name} has negative offset"
            assert size > 0, f"{name} has zero size"

    def test_ewram_size(self):
        assert GBA_MEMORY_MAP["ewram"] == (0x0200_0000, 0x40000)

    def test_iwram_size(self):
        assert GBA_MEMORY_MAP["iwram"] == (0x0300_0000, 0x8000)

    def test_vram_size(self):
        assert GBA_MEMORY_MAP["vram"] == (0x0600_0000, 0x18000)

    def test_oam_size(self):
        assert GBA_MEMORY_MAP["oam"] == (0x0700_0000, 0x400)

    def test_palette_offsets(self):
        assert PALETTE_BG_OFFSET == 0x0500_0000
        assert PALETTE_OBJ_OFFSET == 0x0500_0200

    def test_oam_constants(self):
        assert OAM_ENTRY_SIZE == 8
        assert OAM_MAX_ENTRIES == 128
        assert OAM_ENTRY_SIZE * OAM_MAX_ENTRIES == 1024  # = 0x400 (OAM size)
