"""Capital-gains arithmetic shared by analytics, transition estimates and the optimizer.

Netting follows the US rules: ST losses offset ST gains and LT losses offset LT gains first; a net
loss in one bucket then offsets a net gain in the other. Tax = net ST × ST rate + net LT × LT rate.
(Carry-forward of a net loss across years and the $3,000 ordinary-income offset are ignored.)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RealizedGains:
    """Gross realized gains and losses by holding-period bucket. Losses are positive numbers."""

    st_gain: float = 0.0
    st_loss: float = 0.0
    lt_gain: float = 0.0
    lt_loss: float = 0.0

    def __add__(self, other: RealizedGains) -> RealizedGains:
        return RealizedGains(
            self.st_gain + other.st_gain,
            self.st_loss + other.st_loss,
            self.lt_gain + other.lt_gain,
            self.lt_loss + other.lt_loss,
        )

    @property
    def net(self) -> float:
        return self.st_gain - self.st_loss + self.lt_gain - self.lt_loss

    def netted(self) -> tuple[float, float]:
        """(net ST, net LT) after within-bucket then cross-bucket netting; a remaining net loss
        stays negative in its bucket."""
        st = self.st_gain - self.st_loss
        lt = self.lt_gain - self.lt_loss
        if st < 0 < lt:
            lt, st = max(lt + st, 0.0), min(lt + st, 0.0)
        elif lt < 0 < st:
            st, lt = max(st + lt, 0.0), min(st + lt, 0.0)
        return st, lt


def add_realized(acc: RealizedGains, gain: float, term: str) -> RealizedGains:
    """Add one realized ``gain`` (negative = loss) in bucket ``term`` ("ST" | "LT")."""
    if term == "ST":
        return acc + (RealizedGains(st_gain=gain) if gain >= 0 else RealizedGains(st_loss=-gain))
    return acc + (RealizedGains(lt_gain=gain) if gain >= 0 else RealizedGains(lt_loss=-gain))


def tax_on_realized(r: RealizedGains, st_rate: float, lt_rate: float) -> float:
    """Estimated tax due on a set of realized gains/losses (never negative)."""
    st, lt = r.netted()
    return max(st, 0.0) * st_rate + max(lt, 0.0) * lt_rate


def pooled_tax(st: float, lt: float, losses: float, st_rate: float, lt_rate: float) -> float:
    """Tax when losses are not split by term: offset ST gains first, then LT (conservative).

    Used for event history, where harvested losses are recorded as one pooled number.
    """
    st_net = max(st - losses, 0.0)
    remaining = max(losses - st, 0.0)
    lt_net = max(lt - remaining, 0.0)
    return st_net * st_rate + lt_net * lt_rate
