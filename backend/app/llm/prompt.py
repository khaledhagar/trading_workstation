"""Prompt construction: system prompt, portfolio context, history with action summaries (PLAN.md §9)."""

HISTORY_LIMIT = 20

SYSTEM_PROMPT = """You are trading_workstation, an AI trading assistant inside a simulated trading terminal \
(virtual money, market orders only, instant fills at the current price, no fees, fractional shares allowed \
up to 4 decimal places).

You can:
- Analyze the user's portfolio: composition, risk concentration, unrealized P&L.
- Suggest trades with brief, data-driven reasoning.
- Execute trades when the user asks for them or agrees to a suggestion.
- Manage the watchlist (add or remove tickers), proactively when it helps the user.

Rules:
- Be concise and data-driven. Use the numbers in the portfolio context.
- Always respond with valid JSON matching the required schema: "message" (text shown to the user), \
"trades" (list of {ticker, side: "buy"|"sell", quantity > 0}) and "watchlist_changes" \
(list of {ticker, action: "add"|"remove"}). Use empty lists when there is nothing to do.
- Only put a trade in "trades" if the user explicitly asked for it or agreed to it. Suggestions belong in \
"message", not in "trades".
- Your message is written before the actions run, so phrase trades and watchlist changes as actions being \
taken ("Placing an order to buy 10 AAPL..."), never as confirmed results. The real outcomes are shown to the \
user separately, and you will see them in the conversation history as [Actions: ...].
- Tickers are US stock symbols in uppercase, e.g. AAPL or BRK.B.
- Buys need enough cash (quantity x current price); sells need enough shares held."""


def fmt_qty(q: float) -> str:
    """10.0 -> "10", 0.5 -> "0.5", 1.23456 -> "1.2346"."""
    return f"{round(float(q), 4):.4f}".rstrip("0").rstrip(".")


def _money(v: float | None) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def summarize_actions(actions: dict | None) -> str:
    """Compact outcome summary, e.g. "[Actions: buy 10 AAPL @ 190.12 executed; add PYPL failed: Unknown ticker]".
    Empty string when there were no actions."""
    if not actions:
        return ""
    parts: list[str] = []
    for c in actions.get("watchlist_changes") or []:
        parts.append(_outcome(f"{c.get('action')} {c.get('ticker')}", c))
    for t in actions.get("trades") or []:
        desc = f"{t.get('side')} {fmt_qty(t.get('quantity') or 0)} {t.get('ticker')}"
        if t.get("status") == "executed" and t.get("price") is not None:
            desc += f" @ {t['price']:.2f}"
        parts.append(_outcome(desc, t))
    return f"[Actions: {'; '.join(parts)}]" if parts else ""


def _outcome(desc: str, item: dict) -> str:
    if item.get("status") == "executed":
        return f"{desc} executed"
    return f"{desc} failed: {item.get('error') or 'unknown error'}"


def portfolio_context(portfolio: dict, watchlist: list[dict]) -> str:
    lines = [
        "Current portfolio (live):",
        f"- Cash: {_money(portfolio.get('cash_balance'))}",
        f"- Positions value: {_money(portfolio.get('positions_value'))}",
        f"- Total value: {_money(portfolio.get('total_value'))}",
        f"- Unrealized P&L: {_money(portfolio.get('unrealized_pnl'))}",
    ]
    positions = portfolio.get("positions") or []
    total = portfolio.get("total_value") or 0
    if positions:
        lines.append("Positions:")
        for p in positions:
            weight = (p.get("market_value") or 0) / total * 100 if total else 0
            lines.append(
                f"- {p['ticker']}: qty {fmt_qty(p['quantity'])}, avg cost {_money(p.get('avg_cost'))}, "
                f"price {_money(p.get('current_price'))}, value {_money(p.get('market_value'))} "
                f"({weight:.1f}% of portfolio), P&L {_money(p.get('unrealized_pnl'))} "
                f"({p.get('pnl_percent', 0):+.2f}%)"
            )
    else:
        lines.append("Positions: none")
    if watchlist:
        lines.append("Watchlist:")
        for w in watchlist:
            if w.get("price") is None:
                lines.append(f"- {w['ticker']}: no price yet")
            else:
                lines.append(f"- {w['ticker']}: {_money(w['price'])} ({w.get('change_percent') or 0:+.2f}% today)")
    else:
        lines.append("Watchlist: empty")
    return "\n".join(lines)


def history_messages(history: list[dict]) -> list[dict]:
    """Prior chat rows (oldest first) as LLM messages, assistant rows with their action summary appended."""
    out = []
    for row in history[-HISTORY_LIMIT:]:
        content = row.get("content") or ""
        if row.get("role") == "assistant":
            summary = summarize_actions(row.get("actions"))
            if summary:
                content = f"{content}\n{summary}"
            out.append({"role": "assistant", "content": content})
        else:
            out.append({"role": "user", "content": content})
    return out


def build_messages(portfolio: dict, watchlist: list[dict], history: list[dict], user_message: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": portfolio_context(portfolio, watchlist)},
        *history_messages(history),
        {"role": "user", "content": user_message},
    ]

