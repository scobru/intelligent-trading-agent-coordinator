import os
import sys
from unittest.mock import patch
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from capital_allocator import CapitalAllocator


def test_small_portfolio_pruning_neutral_and_lp():
    allocator = CapitalAllocator()

    # Scenario: Small portfolio of $30 total, where Neutral currently holds $29.92 with 0 positions
    agents_status = {
        "neutral": {"equity_usd": 29.92, "balance_usd": 29.92, "positions_count": 0, "online": True},
        "perp": {"equity_usd": 0.0, "positions_count": 0, "online": True},
        "lp": {"equity_usd": 0.0, "positions_count": 0, "online": True},
        "dca": {"equity_usd": 0.0, "positions_count": 0, "online": True},
        "degen": {"equity_usd": 0.0, "positions_count": 0, "online": True},
        "yield": {"equity_usd": 0.0, "positions_count": 0, "online": True},
    }

    plan = allocator.compute_allocation_plan(
        regime="BALANCED",
        agents_status=agents_status,
        treasury_cash_usd=0.08
    )

    assert plan["total_net_worth_usd"] == 30.0

    allocs = plan["allocations"]
    # Neutral requires $150 -> MUST be pruned to 0
    assert allocs["neutral"]["target_pct"] == 0.0
    assert allocs["neutral"]["target_usd"] == 0.0
    assert allocs["neutral"]["pruned"] is True
    assert allocs["neutral"]["min_viable_usd"] == 150.0

    # LP requires $50 -> MUST be pruned to 0
    assert allocs["lp"]["target_pct"] == 0.0
    assert allocs["lp"]["pruned"] is True

    # Viable strategies receive the redistributed capital
    assert allocs["degen"]["target_usd"] > 0.0
    assert allocs["dca"]["target_usd"] > 0.0

    # Verify that an idle capital recovery action was generated for the trapped $29.92 on Neutral
    actions = plan["actions"]
    sweep_actions = [a for a in actions if a["action"] == "SWEEP_IDLE_FUNDS" and a["from_agent"] == "neutral"]
    assert len(sweep_actions) == 1
    assert sweep_actions[0]["amount_usd"] == 29.92
    assert sweep_actions[0]["to_agent"] in ("dca", "degen", "perp")
    assert "Recupero capitale inerte da NEUTRAL" in sweep_actions[0]["reason"]


def test_large_portfolio_funds_neutral():
    allocator = CapitalAllocator()

    agents_status = {
        "neutral": {"equity_usd": 150.0, "positions_count": 1, "online": True},
        "perp": {"equity_usd": 100.0, "positions_count": 1, "online": True},
        "lp": {"equity_usd": 200.0, "positions_count": 1, "online": True},
        "dca": {"equity_usd": 300.0, "positions_count": 0, "online": True},
        "degen": {"equity_usd": 50.0, "positions_count": 0, "online": True},
        "yield": {"equity_usd": 1200.0, "positions_count": 0, "online": True},
    }

    plan = allocator.compute_allocation_plan(
        regime="BALANCED",
        agents_status=agents_status,
        treasury_cash_usd=0.0
    )

    assert plan["total_net_worth_usd"] == 2000.0
    allocs = plan["allocations"]

    # Neutral gets 15% of $2000 = $300 (>= $150), so it is fully viable and NOT pruned
    assert allocs["neutral"]["pruned"] is False
    assert allocs["neutral"]["target_usd"] == 300.0
    assert allocs["neutral"]["is_viable"] is True

    # LP gets 15% of $2000 = $300 (>= $50)
    assert allocs["lp"]["pruned"] is False
    assert allocs["lp"]["target_usd"] == 300.0


def test_pruning_disabled_flag():
    allocator = CapitalAllocator()

    agents_status = {
        "neutral": {"equity_usd": 30.0, "positions_count": 0, "online": True},
        "yield": {"equity_usd": 0.0, "positions_count": 0, "online": True},
    }

    with patch.object(allocator, "enable_pruning", False):
        plan = allocator.compute_allocation_plan(
            regime="BALANCED",
            agents_status=agents_status,
            treasury_cash_usd=0.0
        )
        # Without pruning, base weights apply directly (Neutral gets 15% = $4.50)
        assert plan["allocations"]["neutral"]["target_pct"] == 0.15
        assert plan["allocations"]["neutral"]["target_usd"] == 4.5
        assert plan["allocations"]["neutral"]["pruned"] is False


def test_active_positions_not_swept_as_idle():
    allocator = CapitalAllocator()

    # Agent has equity < min_viable, but HAS 1 active position running.
    # It should NOT be swept as IDLE capital.
    agents_status = {
        "perp": {"equity_usd": 12.0, "positions_count": 1, "online": True},
        "yield": {"equity_usd": 100.0, "positions_count": 0, "online": True},
    }

    plan = allocator.compute_allocation_plan(
        regime="BALANCED",
        agents_status=agents_status,
        treasury_cash_usd=0.0
    )

    sweep_idle = [a for a in plan["actions"] if a["action"] == "SWEEP_IDLE_FUNDS" and a["from_agent"] == "perp"]
    assert len(sweep_idle) == 0


def test_tiny_portfolio_all_parks_in_dca():
    allocator = CapitalAllocator()

    # Extreme scenario: Total portfolio is only $4.00, below all minimums -> DCA has lowest barrier
    agents_status = {
        "neutral": {"equity_usd": 4.0, "positions_count": 0, "online": True},
    }

    plan = allocator.compute_allocation_plan(
        regime="BALANCED",
        agents_status=agents_status,
        treasury_cash_usd=0.0
    )

    assert plan["total_net_worth_usd"] == 4.0
    # Should park 100% in dca (lowest viable barrier)
    assert plan["allocations"]["dca"]["target_pct"] == 1.0
    assert plan["allocations"]["dca"]["target_usd"] == 4.0
