# alphaforge-crypto

Crypto-substrate research stack for AlphaForge. Sources data from Binance public endpoints; targets funding-rate carry and spot-perp basis as the crypto-native alpha class. v0 is data layer + minimal factor study scaffolding.

See `CLAUDE.md` for architecture, scope, and the methodology carry-over from the failed equity gauntlet.

## Quick start

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -v
python3 sync_binance_data.py --top-n 3 --start-date 2025-01-01 --end-date 2025-01-07
```
