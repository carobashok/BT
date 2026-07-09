# Carob Order Tracker — POC

A self-contained Streamlit app (SQLite backend, pre-seeded with sample
customers/orders) so you can demo it locally in 2 minutes, or put it on a
free public link your friend can open himself.

## Option A — Run it locally (fastest, for you to check first)

```bash
cd order_tracker
pip install -r requirements.txt
streamlit run app.py
```

It opens at http://localhost:8501. Comes pre-loaded with 15 sample
customers and ~40 sample orders so the Dashboard/Tracker aren't empty.

Use the **"Viewing as"** dropdown in the sidebar to switch between Sales
Coordinator / Factory / RSM / Admin views — that's simulating login for
the POC (real login comes later, via Supabase Auth).

## Option B — Give your friend a live link (recommended for the demo)

Easiest free option: **Streamlit Community Cloud**.

1. Push this folder to a new GitHub repo (can be private).
2. Go to https://share.streamlit.io → "New app" → connect the repo →
   set main file to `app.py` → Deploy.
3. You get a public URL (e.g. `https://carob-order-tracker.streamlit.app`)
   — send that to your friend. He can click around on his own, no
   install needed.

Takes about 5 minutes end to end and it's free for a POC like this.

## What's real vs. simulated in this POC

- **Real:** the full order entry → status workflow → factory queue →
  dashboard logic, using an actual database (SQLite here).
- **Simulated for demo speed:** login (role switcher instead), and the
  data is seeded/sample. Both get replaced with Supabase (Postgres) +
  proper auth in the production build — same pattern as your other
  Carob apps (PULSE, QuoteDesk), so that swap is straightforward.

## Next steps after he sees this

- Swap SQLite → Supabase (multi-user, persistent, not tied to one laptop)
- Add real login (Supabase Auth) mapped to Coordinator/RSM/Factory/Admin
- Load his actual 100 customers instead of sample data
- Then decide if/where WhatsApp automation is worth adding (Phase 2)
