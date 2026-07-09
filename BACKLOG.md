# Backlog — Carob Order Tracker (BTP)

Ideas flagged during build, not yet implemented. Revisit when there's
real usage data to prioritize against.

## Partial dispatch
Right now an order moves through statuses as a whole unit — Confirmed →
In Production → Dispatched → Delivered applies to the entire order, all
line items together. In practice, some orders will need to ship in
parts (e.g. 300 of 500 units available now, rest later).

To support this properly would mean tracking dispatch/delivery at the
**line-item level**, not just the order level — likely:
- A `dispatch_id` / `shipment` concept: one order can have multiple
  partial shipments over time
- Each shipment records which items + quantities went out, and when
- Order-level status becomes a rollup (e.g. "Partially Dispatched")
  rather than one fixed value
- Order Tracker / Update Status UI would need a "split this order"
  or "dispatch partial quantity" action, not just a single button

This is a meaningful schema and UI change — worth doing once real
order volume shows how often partial dispatch actually happens, and
what patterns it follows (e.g. always stock-driven, or also
production-batch-driven).

## Region/state-based access control
RSM and Management should eventually only see orders for their own
region/state, not all customers. Needs:
- Real login (Supabase Auth) instead of the current role switcher
- A `users` table mapping each login to name, role, and assigned
  region/state(s)
- RLS policies (or app-level filtering) enforcing that scoping

Flagged in conversation, not started. Ties into the same login work
needed to make audit logs (`updated_by`) reflect real identities
instead of the "Your name" free-text field.
