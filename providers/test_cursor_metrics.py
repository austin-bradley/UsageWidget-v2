"""Regression checks for Cursor meter mapping / percent bases."""
from __future__ import annotations

import unittest

from core.config import _migrate_cursor_percent_slots
from core.models import (
    AccountConfig,
    AppConfig,
    DisplayProfile,
    DisplaySlot,
    IconDisplay,
    Metric,
    TooltipDisplay,
)
from display.format_value import format_slot
from display.icon import _color_for_metric
from providers.cursor import (
    _current_metrics,
    _legacy_metrics,
    _merge_legacy_if_needed,
    _number,
)


class CursorMetricsTests(unittest.TestCase):
    def test_number_accepts_strings_rejects_bool(self) -> None:
        self.assertEqual(_number("7000"), 7000.0)
        self.assertEqual(_number(" 31.9 "), 31.9)
        self.assertIsNone(_number(True))

    def test_included_vs_overall_percent_bases(self) -> None:
        metrics = _current_metrics(
            {
                "planUsage": {
                    "includedSpend": 7000,
                    "limit": 7000,
                    "totalSpend": 8200,
                    "totalPercentUsed": 31.9,
                    "bonusSpend": 0,
                    "remainingBonus": True,
                    "autoPercentUsed": 0,
                    "apiPercentUsed": 0,
                }
            }
        )
        by_id = {m.id: m for m in metrics}
        self.assertEqual(by_id["included"].used_pct, 100)
        self.assertEqual(by_id["included"].used, 70)
        self.assertEqual(by_id["overall"].used_pct, 32)
        self.assertIsNone(by_id["total"].used_pct)
        self.assertEqual(by_id["total"].used, 82)
        self.assertEqual(by_id["bonus"].label, "Bonus available")
        self.assertIsNone(by_id["bonus"].used)
        self.assertEqual(by_id["auto"].used_pct, 0)
        self.assertEqual(by_id["api"].used_pct, 0)

    def test_on_demand_limit_only_no_invented_zero(self) -> None:
        metrics = _current_metrics(
            {"spendLimitUsage": {"individualLimit": 5000}}
        )
        self.assertEqual(len(metrics), 1)
        meter = metrics[0]
        self.assertEqual(meter.id, "on_demand")
        self.assertIsNone(meter.used)
        self.assertEqual(meter.limit, 50)
        self.assertIsNone(meter.used_pct)
        self.assertEqual(format_slot("used_of_limit", meter), "—/$50")

    def test_pooled_limit_only(self) -> None:
        metrics = _current_metrics(
            {"spendLimitUsage": {"pooledLimit": 10000}}
        )
        self.assertEqual([m.id for m in metrics], ["pooled"])
        self.assertIsNone(metrics[0].used)
        self.assertEqual(metrics[0].limit, 100)

    def test_legacy_emits_compat_included_alias(self) -> None:
        metrics = _legacy_metrics(
            {
                "gpt-4": {"numRequests": 10, "maxRequestUsage": 100},
                "startOfMonth": "2026-07-01T00:00:00Z",
            }
        )
        ids = {m.id for m in metrics}
        self.assertEqual(ids, {"included_requests", "included", "overall"})
        by_id = {m.id: m for m in metrics}
        self.assertEqual(by_id["overall"].used_pct, 10)
        self.assertEqual(by_id["overall"].unit, "percent")
        self.assertTrue(
            all(m.unit == "requests" for m in metrics if m.id != "overall")
        )

    def test_sparse_current_merges_legacy_primary(self) -> None:
        sparse = _current_metrics(
            {"planUsage": {"bonusSpend": 0, "remainingBonus": True}}
        )
        self.assertEqual([m.id for m in sparse], ["bonus"])
        legacy = _legacy_metrics(
            {
                "gpt-4": {"numRequests": 10, "maxRequestUsage": 100},
                "startOfMonth": "2026-07-01T00:00:00Z",
            }
        )
        merged = _merge_legacy_if_needed(sparse, legacy)
        ids = [m.id for m in merged]
        self.assertEqual(ids[0], "bonus")
        self.assertIn("included", ids)
        self.assertIn("included_requests", ids)
        self.assertIn("overall", ids)
        # Modern dollars + overall: do not overwrite with legacy included.
        modern = _current_metrics(
            {"planUsage": {"includedSpend": 100, "limit": 200, "totalPercentUsed": 10}}
        )
        same = _merge_legacy_if_needed(modern, legacy)
        self.assertEqual({m.id for m in same}, {m.id for m in modern})
        self.assertEqual(next(m for m in same if m.id == "included").unit, "usd")
        # Hole-fill overall when modern has dollars but no totalPercentUsed.
        dollars_only = _current_metrics(
            {"planUsage": {"includedSpend": 100, "limit": 200}}
        )
        filled = _merge_legacy_if_needed(dollars_only, legacy)
        self.assertEqual(next(m for m in filled if m.id == "included").unit, "usd")
        self.assertEqual(next(m for m in filled if m.id == "overall").used_pct, 10)

    def test_bonus_remaining_pct_is_numeric(self) -> None:
        open_bonus = Metric(
            id="bonus",
            label="Bonus available",
            unit="usd",
            extra={"remaining_bonus": True},
        )
        spent = Metric(
            id="bonus",
            label="Bonus spend",
            used=15.0,
            unit="usd",
            extra={"remaining_bonus": True},
        )
        self.assertEqual(format_slot("remaining_pct", open_bonus), "100")
        self.assertEqual(format_slot("percent", open_bonus), "ok")
        self.assertEqual(format_slot("percent", spent), "?")
        self.assertEqual(format_slot("used_of_limit", spent), "$15")
        green = _color_for_metric(open_bonus, "percent", {"warn": 60, "critical": 85})
        self.assertEqual(green, (52, 199, 89, 255))

    def test_migrate_cursor_included_percent_to_overall(self) -> None:
        cfg = AppConfig(
            accounts=[
                AccountConfig(id="cursor-main", provider="cursor"),
                AccountConfig(id="claude-personal", provider="claude"),
            ],
            profiles={
                "default": DisplayProfile(
                    icon=IconDisplay(
                        slots=[
                            DisplaySlot(ref="cursor-main.included", show="percent"),
                            DisplaySlot(
                                ref="cursor-main.included", show="used_of_limit"
                            ),
                            DisplaySlot(ref="claude-personal.session", show="percent"),
                        ]
                    ),
                    tooltip=TooltipDisplay(
                        slots=[
                            DisplaySlot(
                                ref="cursor-main.included",
                                show="percent_and_reset",
                                label="C",
                            )
                        ]
                    ),
                )
            },
        )
        _migrate_cursor_percent_slots(cfg)
        icon = cfg.profiles["default"].icon.slots
        self.assertEqual(icon[0].ref, "cursor-main.overall")
        self.assertEqual(icon[1].ref, "cursor-main.included")
        self.assertEqual(icon[2].ref, "claude-personal.session")
        tip = cfg.profiles["default"].tooltip.slots[0]
        self.assertEqual(tip.ref, "cursor-main.overall")
        self.assertEqual(tip.show, "percent_and_reset")


if __name__ == "__main__":
    unittest.main()
