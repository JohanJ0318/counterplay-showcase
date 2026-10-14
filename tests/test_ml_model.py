"""WinNet's two structural promises (ml/model.py). Skipped where torch is
not installed, which includes CI and the server: ml/ is offline work.

  * the order of players inside a side never matters (a side is a set);
  * an empty slot (nobody played it) changes nothing, while a dead player
    still counts, because where they died is information.
"""
import pytest

torch = pytest.importorskip("torch")

from ml.data import PLAYER_FEATURES  # noqa: E402
from ml.model import GLOBAL, WinNet  # noqa: E402


def inputs(players):
    b = players.shape[0]
    return (players, torch.zeros(b, len(GLOBAL)), torch.zeros(b, dtype=torch.long),
            torch.zeros(b, dtype=torch.long), torch.zeros(b, dtype=torch.long),
            torch.zeros(b, dtype=torch.long))


def test_player_order_within_a_side_does_not_matter():
    torch.manual_seed(0)
    net = WinNet().eval()
    p = torch.randn(1, 10, len(PLAYER_FEATURES))
    shuffled = p[:, torch.tensor([3, 0, 4, 1, 2, 9, 7, 5, 8, 6])]
    with torch.no_grad():
        assert torch.allclose(net(*inputs(p)), net(*inputs(shuffled)), atol=1e-5)


def test_swapping_a_player_across_sides_does_matter():
    torch.manual_seed(0)
    net = WinNet().eval()
    p = torch.randn(1, 10, len(PLAYER_FEATURES))
    swapped = p[:, torch.tensor([5, 1, 2, 3, 4, 0, 6, 7, 8, 9])]
    with torch.no_grad():
        assert not torch.allclose(net(*inputs(p)), net(*inputs(swapped)), atol=1e-4)


def test_an_empty_slot_is_ignored_but_a_dead_player_is_not():
    torch.manual_seed(0)
    net = WinNet().eval()
    p = torch.randn(1, 10, len(PLAYER_FEATURES))
    p[0, 4] = 0.0                                  # four CTs, slot 5 empty
    moved = p[:, torch.tensor([4, 0, 1, 2, 3, 5, 6, 7, 8, 9])]   # empty first
    dead = p.clone()
    dead[0, 4, 0] = 1.5                            # a dead CT lying at x = 1.5
    with torch.no_grad():
        base = net(*inputs(p))
        # Where the empty slot sits makes no difference: it is masked out.
        assert torch.allclose(base, net(*inputs(moved)), atol=1e-5)
        # A dead player in that slot does: a body is not an empty seat.
        assert not torch.allclose(base, net(*inputs(dead)), atol=1e-5)
