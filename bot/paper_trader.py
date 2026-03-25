"""
Paper trading simulator — virtual balance, no real orders.
Tracks open/closed positions, P&L, and trade history.
"""

from __future__ import annotations

import time
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from bot.entry import Signal


class PositionState(Enum):
    OPEN = "open"
    CLOSED_SL = "closed_sl"
    CLOSED_TP = "closed_tp"
    CLOSED_TRAILING = "closed_trailing"


@dataclass
class PaperPosition:
    ticket: int
    symbol: str
    signal: Signal
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    point_size: float
    open_time: str
    close_time: str | None = None
    close_price: float | None = None
    state: PositionState = PositionState.OPEN
    pnl: float = 0.0
    breakeven_applied: bool = False
    max_favorable: float = 0.0   # max favorable excursion in $


@dataclass
class PaperAccount:
    initial_balance: float
    balance: float
    equity: float
    positions: list[PaperPosition] = field(default_factory=list)
    closed_trades: list[PaperPosition] = field(default_factory=list)
    _next_ticket: int = 1

    @property
    def total_trades(self) -> int:
        return len(self.closed_trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.closed_trades if t.pnl > 0)

    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.closed_trades if t.pnl <= 0)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades * 100

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_trades)

    @property
    def largest_win(self) -> float:
        wins = [t.pnl for t in self.closed_trades if t.pnl > 0]
        return max(wins) if wins else 0.0

    @property
    def largest_loss(self) -> float:
        losses = [t.pnl for t in self.closed_trades if t.pnl <= 0]
        return min(losses) if losses else 0.0

    def print_summary(self):
        print("\n" + "=" * 65)
        print("  PAPER TRADING SUMMARY")
        print("=" * 65)
        print(f"  Initial Balance:  ${self.initial_balance:,.2f}")
        print(f"  Current Balance:  ${self.balance:,.2f}")
        print(f"  Total P&L:        ${self.total_pnl:,.2f}")
        print(f"  Return:           {(self.balance / self.initial_balance - 1) * 100:.2f}%")
        print("-" * 65)
        print(f"  Total Trades:     {self.total_trades}")
        print(f"  Wins:             {self.winning_trades}")
        print(f"  Losses:           {self.losing_trades}")
        print(f"  Win Rate:         {self.win_rate:.1f}%")
        if self.total_trades > 0:
            print(f"  Largest Win:      ${self.largest_win:,.2f}")
            print(f"  Largest Loss:     ${self.largest_loss:,.2f}")
            avg_pnl = self.total_pnl / self.total_trades
            print(f"  Avg P&L/trade:    ${avg_pnl:,.2f}")

            # Per-symbol breakdown
            symbols = sorted(set(t.symbol for t in self.closed_trades))
            if len(symbols) > 1:
                print("-" * 65)
                print("  PER SYMBOL:")
                for sym in symbols:
                    sym_trades = [t for t in self.closed_trades if t.symbol == sym]
                    sym_pnl = sum(t.pnl for t in sym_trades)
                    sym_wins = sum(1 for t in sym_trades if t.pnl > 0)
                    sym_wr = sym_wins / len(sym_trades) * 100 if sym_trades else 0
                    arrow = "+" if sym_pnl > 0 else ""
                    print(f"    {sym:8s} | {len(sym_trades)} trades | "
                          f"WR={sym_wr:.0f}% | {arrow}${sym_pnl:,.2f}")

        print("-" * 65)
        print("  TRADE HISTORY:")
        for t in self.closed_trades:
            arrow = "+" if t.pnl > 0 else ""
            print(f"    #{t.ticket:03d} {t.symbol:8s} {t.signal.value:5s} | "
                  f"entry={t.entry_price:.5f} exit={t.close_price:.5f} | "
                  f"{t.state.value:16s} | {arrow}${t.pnl:,.2f}")
        print("=" * 65 + "\n")


class PaperTrader:
    """Simulates order execution and position management with virtual money."""

    def __init__(self, balance: float = 200.0):
        self.account = PaperAccount(
            initial_balance=balance,
            balance=balance,
            equity=balance,
        )

    def open_position(
        self,
        symbol: str,
        signal: Signal,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        lot_size: float,
        point_size: float,
    ) -> PaperPosition:
        """Open a simulated position."""
        ticket = self.account._next_ticket
        self.account._next_ticket += 1

        pos = PaperPosition(
            ticket=ticket,
            symbol=symbol,
            signal=signal,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            lot_size=lot_size,
            point_size=point_size,
            open_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.account.positions.append(pos)

        print(f"  [PAPER] Opened #{ticket} {symbol} {signal.value} {lot_size} lots "
              f"@ {entry_price:.5f} | SL={stop_loss:.5f} TP={take_profit:.5f}")
        return pos

    def update_position(self, pos: PaperPosition, bid: float, ask: float) -> bool:
        """
        Check a single position against current bid/ask.
        Returns True if still open, False if closed.
        """
        ps = pos.point_size

        # Calculate unrealized P&L
        if pos.signal == Signal.LONG:
            pips = (bid - pos.entry_price) / ps
        else:
            pips = (pos.entry_price - ask) / ps

        pip_value = pos.lot_size * 10.0
        unrealized_pnl = pips * pip_value * ps * 10000
        pos.max_favorable = max(pos.max_favorable, unrealized_pnl)

        # Check stop-loss
        if pos.signal == Signal.LONG and bid <= pos.stop_loss:
            self._close_position(pos, pos.stop_loss, PositionState.CLOSED_SL)
            return False
        elif pos.signal == Signal.SHORT and ask >= pos.stop_loss:
            self._close_position(pos, pos.stop_loss, PositionState.CLOSED_SL)
            return False

        # Check take-profit
        if pos.signal == Signal.LONG and bid >= pos.take_profit:
            self._close_position(pos, pos.take_profit, PositionState.CLOSED_TP)
            return False
        elif pos.signal == Signal.SHORT and ask <= pos.take_profit:
            self._close_position(pos, pos.take_profit, PositionState.CLOSED_TP)
            return False

        return True

    def update_all_positions(self, price_feeds: dict[str, tuple[float, float]]) -> None:
        """
        Update all open positions with current prices.
        price_feeds: {symbol: (bid, ask)}
        """
        still_open = []
        for pos in self.account.positions:
            if pos.symbol not in price_feeds:
                still_open.append(pos)
                continue
            bid, ask = price_feeds[pos.symbol]
            if self.update_position(pos, bid, ask):
                still_open.append(pos)
        self.account.positions = still_open

        # Update equity
        total_unrealized = 0.0
        for pos in self.account.positions:
            if pos.symbol not in price_feeds:
                continue
            bid, ask = price_feeds[pos.symbol]
            if pos.signal == Signal.LONG:
                pips = (bid - pos.entry_price) / pos.point_size
            else:
                pips = (pos.entry_price - ask) / pos.point_size
            pip_value = pos.lot_size * 10.0
            total_unrealized += pips * pip_value * pos.point_size * 10000
        self.account.equity = self.account.balance + total_unrealized

    def modify_sl(self, pos: PaperPosition, new_sl: float) -> None:
        """Update stop-loss for an open position."""
        old_sl = pos.stop_loss
        pos.stop_loss = new_sl
        print(f"  [PAPER] #{pos.ticket} {pos.symbol} SL: {old_sl:.5f} -> {new_sl:.5f}")

    def _close_position(self, pos: PaperPosition, close_price: float,
                        state: PositionState) -> None:
        """Close a position and record P&L."""
        if pos.signal == Signal.LONG:
            pnl_pips = (close_price - pos.entry_price) / pos.point_size
        else:
            pnl_pips = (pos.entry_price - close_price) / pos.point_size

        # P&L in dollars
        pip_value = pos.lot_size * 10.0
        pos.pnl = round(pnl_pips * pip_value * pos.point_size * 10000, 2)
        pos.close_price = close_price
        pos.close_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pos.state = state

        self.account.balance += pos.pnl
        self.account.closed_trades.append(pos)

        icon = "WIN" if pos.pnl > 0 else "LOSS"
        print(f"  [PAPER] Closed #{pos.ticket} {pos.symbol} ({state.value}) "
              f"@ {close_price:.5f} | P&L: ${pos.pnl:+.2f} [{icon}] | "
              f"Balance: ${self.account.balance:.2f}")

    @property
    def has_open_positions(self) -> bool:
        return len(self.account.positions) > 0
