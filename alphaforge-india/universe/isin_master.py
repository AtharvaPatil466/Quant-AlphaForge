"""ISIN master loader and symbol rename graph.

Per research/INDIA_DESIGN.md §2.4, reads EQUITY_L.csv and symbolchange.csv
to build a robust rename graph and ISIN mapping.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
import pandas as pd

log = logging.getLogger("india.universe.isin_master")


class ISINMaster:
    """Securities master and symbol rename resolver."""

    def __init__(
        self,
        equity_l_path: str | Path = "EQUITY_L.csv",
        symbolchange_path: str | Path = "symbolchange.csv",
    ) -> None:
        self.equity_l_path = Path(equity_l_path)
        self.symbolchange_path = Path(symbolchange_path)

        # Mappings built from files
        self.symbol_to_isin: dict[str, str] = {}
        self.symbol_to_name: dict[str, str] = {}
        self.name_to_symbol: dict[str, str] = {}

        # Rename graph edges: symbol_old -> (symbol_new, change_date)
        self.forward_renames: dict[str, tuple[str, date]] = {}
        # Rename graph edges: symbol_new -> (symbol_old, change_date)
        self.backward_renames: dict[str, tuple[str, date]] = {}

        self._load_data()

    def _load_data(self) -> None:
        """Load securities master and rename events."""
        # 1. Load EQUITY_L.csv
        if self.equity_l_path.exists():
            df_eq = pd.read_csv(self.equity_l_path)
            # Strip column whitespaces
            df_eq.columns = df_eq.columns.str.strip()
            
            for _, row in df_eq.iterrows():
                symbol = str(row["SYMBOL"]).strip()
                name = str(row["NAME OF COMPANY"]).strip()
                isin = str(row["ISIN NUMBER"]).strip()
                
                self.symbol_to_isin[symbol] = isin
                self.symbol_to_name[symbol] = name
                self.name_to_symbol[self._normalize_name(name)] = symbol
        else:
            log.warning("EQUITY_L.csv not found at %s", self.equity_l_path)

        # 2. Load symbolchange.csv
        if self.symbolchange_path.exists():
            # No header: company_name, symbol_old, symbol_new, date_change
            df_sym = pd.read_csv(
                self.symbolchange_path,
                header=None,
                names=["company_name", "symbol_old", "symbol_new", "date_change"],
            )
            
            for _, row in df_sym.iterrows():
                if pd.isna(row["symbol_old"]) or pd.isna(row["symbol_new"]):
                    continue
                old = str(row["symbol_old"]).strip()
                new = str(row["symbol_new"]).strip()
                comp_name = str(row["company_name"]).strip()
                
                # Parse date
                date_str = str(row["date_change"]).strip()
                try:
                    dt = pd.to_datetime(date_str, format="%d-%b-%Y").date()
                except Exception:
                    try:
                        dt = pd.to_datetime(date_str, dayfirst=True).date()
                    except Exception as e:
                        log.warning("Failed to parse date %r for rename %s -> %s: %r", date_str, old, new, e)
                        continue
                
                self.forward_renames[old] = (new, dt)
                self.backward_renames[new] = (old, dt)
                self.name_to_symbol[self._normalize_name(comp_name)] = new
        else:
            log.warning("symbolchange.csv not found at %s", self.symbolchange_path)

    def _normalize_name(self, name: str) -> str:
        """Helper to normalize company names for lookup."""
        if not isinstance(name, str):
            return ""
        name = name.upper().strip()
        name = name.replace("LIMITED", "LTD")
        name = name.replace("LTD.", "LTD")
        import re
        name = re.sub(r"[^A-Z0-9\s]", "", name)
        return " ".join(name.split())

    def get_active_symbol(self, symbol: str, as_of_date: date | str) -> str:
        """Resolve the active ticker symbol as of a specific date.

        Traces both forward and backward through the rename graph.
        """
        if isinstance(as_of_date, str):
            as_of_date = pd.to_datetime(as_of_date).date()
        elif isinstance(as_of_date, datetime):
            as_of_date = as_of_date.date()

        curr = symbol.strip()
        visited = {curr}
        
        for _ in range(100):  # Safety limit for cycles
            # Try going forward
            if curr in self.forward_renames:
                s_next, change_date = self.forward_renames[curr]
                if as_of_date >= change_date:
                    if s_next in visited:
                        log.error("Cycle detected in rename graph at %s", s_next)
                        break
                    curr = s_next
                    visited.add(curr)
                    continue
            
            # Try going backward
            if curr in self.backward_renames:
                s_prev, change_date = self.backward_renames[curr]
                if as_of_date < change_date:
                    if s_prev in visited:
                        log.error("Cycle detected in rename graph at %s", s_prev)
                        break
                    curr = s_prev
                    visited.add(curr)
                    continue
            
            # If we reached here, no valid steps can be made
            break
        else:
            log.error("Infinite loop safety limit exceeded resolving symbol %s", symbol)
            
        return curr

    def get_isin(self, symbol: str) -> str | None:
        """Retrieve the ISIN for a symbol, tracing forward to currently listed if needed."""
        curr = symbol.strip()
        visited = {curr}
        
        # Trace forward to the end of the chain
        for _ in range(100):
            if curr in self.forward_renames:
                s_next, _ = self.forward_renames[curr]
                if s_next in visited:
                    break
                curr = s_next
                visited.add(curr)
            else:
                break
                
        # Return ISIN of the resolved latest symbol
        return self.symbol_to_isin.get(curr)
