"""The caller's book, as the decision agents see it.

Portfolio context is optional: a position, a flat book, and no context at all
are deliberately distinct. The models remain broker-neutral; quantities are
generic units and currency is only a caller-supplied label.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class Position(BaseModel):
    """A caller-supplied position in one instrument."""

    ticker: str = Field(description="Instrument symbol, e.g. AAPL")
    quantity: float = Field(description="Signed units held; negative is short")
    average_price: float | None = Field(
        default=None, description="Average entry price per unit"
    )


class PortfolioContext(BaseModel):
    """Optional cash and positions supplied for a single analysis run."""

    cash: float | None = Field(default=None, description="Free cash available")
    currency: str | None = Field(
        default=None, description="Currency label for cash and prices"
    )
    positions: list[Position] = Field(default_factory=list)

    def position_in(self, ticker: str) -> Position | None:
        """Return the first position matching ``ticker`` case-insensitively."""
        symbol = ticker.strip().upper()
        return next((item for item in self.positions if item.ticker.upper() == symbol), None)

    def render(self, ticker: str) -> str:
        """Render the book in an agent-readable form led by the target instrument."""
        symbol = ticker.strip().upper()
        held = self.position_in(symbol)
        if held is None:
            lines = [f"- No current position in {symbol}"]
        else:
            price = (
                f", average price {held.average_price:,.2f}"
                if held.average_price is not None
                else ""
            )
            lines = [f"- Current position in {symbol}: {held.quantity:,.4g} units{price}"]
        if self.cash is not None:
            currency = f" {self.currency}" if self.currency else ""
            lines.append(f"- Cash available: {self.cash:,.2f}{currency}")
        other_positions = [item for item in self.positions if item is not held]
        if other_positions:
            lines.append(
                "- Other positions: "
                + ", ".join(
                    f"{item.ticker.upper()} {item.quantity:,.4g}" for item in other_positions
                )
            )
        return "Portfolio at the analysis date:\n" + "\n".join(lines)

    def fingerprint(self) -> str:
        """Return a stable digest used to isolate compatible checkpoints."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:12]


def load_portfolio(path: str | Path) -> PortfolioContext:
    """Read and validate a portfolio JSON file before the graph starts."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return PortfolioContext.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"portfolio file {path} is not usable: {exc}") from exc
