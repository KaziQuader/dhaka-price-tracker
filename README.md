# Dhaka Price Tracker

A local, personal tool that tracks and predicts, from a Dhaka point of view:

- **BAJUS gold prices**: 22K, 21K, 18K and traditional, buy and sell.
- **Airfares from Dhaka (DAC)** to Hanoi, Bangkok, Manila and Vientiane.

It joins these prices with context (USD/BDT, world gold, Bangladesh holidays, news shocks) and
shows KPIs, patterns and short-horizon predictions on a local Metabase dashboard, with email alerts.

Everything runs locally with Docker Compose, at zero cost, and is triggered by hand once a day.

## Status

Planning stage. No code yet. See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the
architecture, data sources and the ticket list. Work starts with ticket **T0.1 (repo scaffold)**.
