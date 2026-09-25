import os
import sys
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from agent_client import AgentClient
from treasury import Treasury


def test_agent_client_release_funds():
    client = AgentClient()
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"status": "success", "released_usd": 25.0}

        res = client.release_agent_funds("degen", amount_usd=25.0)
        assert res["status"] == "success"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "/api/release_funds" in args[0]
        assert kwargs["json"] == {"amount_usd": 25.0}


def test_treasury_calls_release_funds_when_usdc_insufficient():
    treasury = Treasury()
    mock_agent_client = MagicMock()
    mock_agent_client.release_agent_funds.return_value = {"status": "success", "released_usd": 30.0}

    # Live trading mock
    with patch.object(config, "PAPER_TRADING", False), \
         patch.object(config, "DRY_RUN", False), \
         patch.object(config, "get_agent_private_key", return_value="0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"), \
         patch.object(treasury, "transfer_usdc", return_value="0x_tx_hash"), \
         patch("time.sleep"):

        # Mock eth gas balance as sufficient
        treasury.w3 = MagicMock()
        treasury.w3.eth.get_balance.return_value = 10**16 # 0.01 ETH

        # Mock balanceOf: first call 1.90 USDC, second call (after release) 31.90 USDC
        treasury.usdc_contract = MagicMock()
        treasury.usdc_contract.functions.balanceOf.return_value.call.side_effect = [
            1_900_000,   # $1.90 initially
            31_900_000,  # $31.90 after release
        ]

        action = {
            "action": "SWEEP_PROFIT",
            "from_agent": "degen",
            "to_agent": "yield",
            "amount_usd": 30.0,
            "reason": "Test sweep"
        }
        agents_status = {
            "yield": {"wallet": "0xYieldWalletAddress"}
        }

        ok = treasury.execute_rebalance_action(action, agents_status, agent_client=mock_agent_client)
        assert ok is True
        mock_agent_client.release_agent_funds.assert_called_once_with("degen", 28.1)
        treasury.transfer_usdc.assert_called_once()
