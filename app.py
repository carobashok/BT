import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client, Client

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
st.set_page_config(page_title="Carob Order Tracker", page_icon="📦", layout="wide")

NAVY = "#0D1B2A"
ACCENT = "#2563EB"
BG = "#0D1B2A"
CARD_BG = "#16273D"
TEXT = "#F0F4FA"
MUTED_TEXT = "#93A4BD"

STATUSES = ["Placed", "Confirmed", "In Production", "Dispatched", "Delivered"]
STATUS_COLORS = {
    "Placed": "#94A3B8",
    "Confirmed": "#2563EB",
    "In Production": "#F59E0B",
    "Dispatched": "#8B5CF6",
    "Delivered": "#16A34A",
}
REGIONS = ["North", "South", "East", "West"]
ITEMS = ["Bearing Assembly", "Brake Pad Set", "Clutch Plate", "Gear Box Unit",
         "Piston Ring Kit", "Radiator Core", "Suspension Arm", "Wiring Harness"]

SCHEMA = "btp"

# ---------------------------------------------------------
# SUPABASE CLIENT
# Expects st.secrets["SUPABASE_URL"] and st.secrets["SUPABASE_SERVICE_KEY"]
# (service_role key — this app runs server-side in Streamlit,
# so it's safe here; never ship a service key in client-side JS)
# ---------------------------------------------------------
@st.cache_resource
def get_client() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

try:
    supabase = get_client().schema(SCHEMA)
except Exception as e:
    st.error(
        "Couldn't connect to Supabase. Check that your secrets contain a "
        "[supabase] section with 'url' and 'key', and that the "
        f"'{SCHEMA}' schema has been created (see sql/schema.sql) and "
        "added to Project Settings > API > Exposed schemas."
    )
    st.exception(e)
    st.stop()

# ---------------------------------------------------------
# DATA ACCESS HELPERS
# ---------------------------------------------------------
def fetch_customers() -> pd.DataFrame:
    res = supabase.table("customers").select("*").order("name").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame(
        columns=["customer_id", "name", "region", "rsm", "created_at"])

def fetch_orders() -> pd.DataFrame:
    res = supabase.table("orders").select(
        "*, customers(name, region, rsm)"
    ).order("order_id", desc=True).execute()
    rows = res.data or []
    flat = []
    for r in rows:
        cust = r.get("customers") or {}
        flat.append({
            "order_id": r["order_id"],
            "customer_id": r["customer_id"],
            "customer_name": cust.get("name"),
            "region": cust.get("region"),
            "rsm": cust.get("rsm"),
            "item": r["item"],
            "qty": r["qty"],
            "unit": r["unit"],
            "requested_date": r["requested_date"],
            "notes": r["notes"],
            "status": r["status"],
            "placed_by": r["placed_by"],
            "placed_at": r["placed_at"],
        })
    return pd.DataFrame(flat)

def insert_order(customer_id, item, qty, unit, requested_date, notes, placed_by):
    now = datetime.utcnow().isoformat()
    res = supabase.table("orders").insert({
        "customer_id": int(customer_id),
        "item": item,
        "qty": int(qty),
        "unit": unit,
        "requested_date": str(requested_date),
        "notes": notes,
        "status": "Placed",
        "placed_by": placed_by,
        "placed_at": now,
    }).execute()
    order_id = res.data[0]["order_id"]
    supabase.table("status_log").insert({
        "order_id": order_id, "status": "Placed",
        "updated_by": placed_by, "updated_at": now, "note": "",
    }).execute()
    return order_id

def update_order_status(order_id, new_status, updated_by, note=""):
    now = datetime.utcnow().isoformat()
    supabase.table("orders").update({"status": new_status}).eq("order_id", order_id).execute()
    supabase.table("status_log").insert({
        "order_id": order_id, "status": new_status,
        "updated_by": updated_by, "updated_at": now, "note": note,
    }).execute()

def fetch_status_log(order_id) -> pd.DataFrame:
    res = supabase.table("status_log").select("*").eq(
        "order_id", order_id).order("log_id").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame(
        columns=["status", "updated_by", "updated_at", "note"])

def insert_customer(name, region, rsm):
    supabase.table("customers").insert(
        {"name": name, "region": region, "rsm": rsm}).execute()

# ---------------------------------------------------------
# STYLING (self-contained dark theme — doesn't rely on config.toml)
# ---------------------------------------------------------
st.markdown(f"""
<style>
    html, body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stHeader"],
    [data-testid="stMain"],
    .main {{
        background-color: {BG} !important;
    }}
    .stApp, .stApp p, .stApp span, .stApp label, .stApp li, .stApp div {{ color: {TEXT} !important; }}
    h1, h2, h3, h4, h5, h6 {{ color: {TEXT} !important; }}
    .stMarkdown, .stCaption, [data-testid="stCaptionContainer"] {{ color: {MUTED_TEXT} !important; }}
    [data-testid="stMetricLabel"] p {{ color: {MUTED_TEXT} !important; }}
    [data-testid="stMetricValue"] {{ color: {TEXT} !important; }}
    [data-testid="stMetricValue"] div {{ color: {TEXT} !important; }}
    [data-testid="stWidgetLabel"] p {{ color: {TEXT} !important; }}
    section[data-testid="stSidebar"] {{ background-color: {CARD_BG} !important; }}
    section[data-testid="stSidebar"] * {{ color: {TEXT} !important; }}
    .stTabs [data-baseweb="tab"] {{ color: {MUTED_TEXT} !important; }}
    .stTabs [data-baseweb="tab"] p {{ color: {MUTED_TEXT} !important; }}
    .stTabs [aria-selected="true"] {{ color: {ACCENT} !important; }}
    .stTabs [aria-selected="true"] p {{ color: {ACCENT} !important; }}
    .stDataFrame, .stDataFrame * {{ color: {TEXT} !important; }}
    [data-testid="stContainer"], div[data-testid="stVerticalBlockBorderWrapper"] {{
        background-color: {CARD_BG} !important;
    }}
    input, textarea, select {{
        background-color: {CARD_BG} !important;
        color: {TEXT} !important;
    }}
    [data-baseweb="select"] > div {{
        background-color: {CARD_BG} !important;
        color: {TEXT} !important;
    }}
    .main-header {{
        background-color: {CARD_BG} !important;
        padding: 1.2rem 1.5rem;
        border-radius: 8px;
        margin-bottom: 1.5rem;
        border: 1px solid #223349;
    }}
    .main-header h1, .main-header h1 * {{ color: white !important; margin: 0; font-size: 1.5rem; }}
    .main-header p {{ color: #93C5FD !important; margin: 0; font-size: 0.9rem; }}
    .status-badge {{
        padding: 3px 10px;
        border-radius: 12px;
        color: white !important;
        font-size: 0.75rem;
        font-weight: 600;
        display: inline-block;
    }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="main-header">
    <h1>📦 Order Tracker</h1>
    <p>Carob Technologies — Customer to Factory order visibility</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# ROLE SELECTOR (simulated auth — Phase 2: swap for Supabase Auth)
# ---------------------------------------------------------
with st.sidebar:
    st.markdown("### 👤 Viewing as")
    role = st.selectbox("Role", ["Sales Coordinator", "Factory", "RSM / Management", "Admin"])
    st.caption("Role-based login (Supabase Auth) replaces this switch in the next phase.")
    st.divider()
    st.caption("Carob Technologies · Supabase-backed")

customers_df = fetch_customers()
if customers_df.empty:
    st.warning(
        f"No customers found in `{SCHEMA}.customers`. Run `sql/schema.sql` in the "
        "Supabase SQL Editor to create tables and seed sample data."
    )
    st.stop()

customer_map = dict(zip(customers_df["name"], customers_df["customer_id"]))

# ---------------------------------------------------------
# TABS
# ---------------------------------------------------------
tab_names = []
if role in ["Sales Coordinator", "Admin"]:
    tab_names.append("➕ Order Entry")
tab_names.append("📋 Order Tracker")
if role in ["Factory", "Admin"]:
    tab_names.append("🏭 Factory View")
tab_names.append("📊 Dashboard")
if role == "Admin":
    tab_names.append("⚙️ Admin")

tabs = st.tabs(tab_names)
tab_map = dict(zip(tab_names, tabs))

# ---- ORDER ENTRY ----
if "➕ Order Entry" in tab_map:
    with tab_map["➕ Order Entry"]:
        st.subheader("New Order Entry")
        col1, col2 = st.columns(2)
        with col1:
            cust_name = st.selectbox("Customer", sorted(customer_map.keys()))
            item = st.selectbox("Item", ITEMS)
            qty = st.number_input("Quantity", min_value=1, value=100, step=10)
        with col2:
            unit = st.selectbox("Unit", ["pcs", "kg", "boxes"])
            req_date = st.date_input("Requested Delivery Date",
                                       value=datetime.now() + timedelta(days=7))
            notes = st.text_area("Notes (optional)", height=68)

        cust_row = customers_df[customers_df["name"] == cust_name].iloc[0]
        st.caption(f"Region: **{cust_row['region']}** · RSM: **{cust_row['rsm']}**")

        if st.button("Submit Order", type="primary"):
            order_id = insert_order(
                cust_row["customer_id"], item, qty, unit, req_date, notes,
                "Sales Coordinator")
            st.success(f"Order #{order_id} placed for {cust_name}")
            st.rerun()

        st.divider()
        st.markdown("**Orders entered today**")
        all_orders_preview = fetch_orders()
        if not all_orders_preview.empty:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            today_orders = all_orders_preview[
                all_orders_preview["placed_at"].astype(str).str.startswith(today)
            ][["order_id", "customer_name", "item", "qty", "status"]]
            if today_orders.empty:
                st.caption("No orders entered yet today.")
            else:
                st.dataframe(today_orders, hide_index=True, use_container_width=True)
        else:
            st.caption("No orders entered yet today.")

# ---- ORDER TRACKER ----
with tab_map["📋 Order Tracker"]:
    st.subheader("All Orders")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        f_customer = st.multiselect("Customer", sorted(customer_map.keys()))
    with col2:
        f_region = st.multiselect("Region", REGIONS)
    with col3:
        f_status = st.multiselect("Status", STATUSES)
    with col4:
        f_search = st.text_input("Search item / order ID")

    orders_df = fetch_orders()

    if not orders_df.empty:
        if f_customer:
            orders_df = orders_df[orders_df["customer_name"].isin(f_customer)]
        if f_region:
            orders_df = orders_df[orders_df["region"].isin(f_region)]
        if f_status:
            orders_df = orders_df[orders_df["status"].isin(f_status)]
        if f_search:
            mask = (orders_df["item"].str.contains(f_search, case=False, na=False) |
                    orders_df["order_id"].astype(str).str.contains(f_search))
            orders_df = orders_df[mask]

        orders_df["days_open"] = orders_df["placed_at"].apply(
            lambda x: (datetime.utcnow() - pd.to_datetime(x).to_pydatetime().replace(tzinfo=None)).days
            if pd.notna(x) else None
        )

        display_df = orders_df.rename(columns={
            "order_id": "Order ID", "customer_name": "Customer", "region": "Region",
            "item": "Item", "qty": "Qty", "status": "Status",
            "requested_date": "Requested Date", "placed_at": "Placed At",
            "rsm": "RSM", "days_open": "Days Open",
        })[["Order ID", "Customer", "Region", "Item", "Qty", "Status",
            "Requested Date", "Placed At", "RSM", "Days Open"]]

        st.caption(f"{len(display_df)} orders")
        st.dataframe(display_df, hide_index=True, use_container_width=True)

        with st.expander("🔍 View order detail / status history"):
            sel_id = st.selectbox("Order ID", display_df["Order ID"].tolist())
            hist = fetch_status_log(int(sel_id))
            if not hist.empty:
                hist = hist.rename(columns={
                    "status": "Status", "updated_by": "Updated By",
                    "updated_at": "Updated At", "note": "Note"})[
                    ["Status", "Updated By", "Updated At", "Note"]]
            st.dataframe(hist, hide_index=True, use_container_width=True)
    else:
        st.info("No orders yet. Add one from the Order Entry tab.")

# ---- FACTORY VIEW ----
if "🏭 Factory View" in tab_map:
    with tab_map["🏭 Factory View"]:
        st.subheader("Factory Queue")
        queue_status = st.selectbox("Show orders in status", STATUSES, index=1)
        all_orders = fetch_orders()
        queue_df = all_orders[all_orders["status"] == queue_status] if not all_orders.empty else all_orders

        if queue_df.empty:
            st.info(f"No orders currently in '{queue_status}'.")
        else:
            queue_df = queue_df.sort_values("requested_date")
            next_status_idx = STATUSES.index(queue_status) + 1
            next_status = STATUSES[next_status_idx] if next_status_idx < len(STATUSES) else None

            for _, row in queue_df.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 2])
                    with c1:
                        st.markdown(f"**Order #{row['order_id']}** — {row['customer_name']}")
                        st.caption(f"{row['item']} · Qty: {row['qty']} · Needed by {row['requested_date']}")
                    with c2:
                        note = st.text_input("Note", key=f"note_{row['order_id']}",
                                              label_visibility="collapsed", placeholder="Optional note")
                    with c3:
                        if next_status and st.button(f"Move to '{next_status}'", key=f"btn_{row['order_id']}"):
                            update_order_status(int(row["order_id"]), next_status, "Factory", note)
                            st.rerun()

# ---- DASHBOARD ----
with tab_map["📊 Dashboard"]:
    st.subheader("Overview")
    all_orders = fetch_orders()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Orders", len(all_orders))
    if not all_orders.empty:
        col2.metric("Open Orders", len(all_orders[all_orders["status"] != "Delivered"]))
        col3.metric("Dispatched/Delivered",
                    len(all_orders[all_orders["status"].isin(["Dispatched", "Delivered"])]))
        delivered = all_orders[all_orders["status"] == "Delivered"]
        avg_days = "—"
        if not delivered.empty:
            placed_dt = pd.to_datetime(delivered["placed_at"]).dt.tz_localize(None)
            avg_days = f'{(datetime.utcnow() - placed_dt).dt.days.mean():.1f} days'
        col4.metric("Avg. Age (Delivered)", avg_days)
    else:
        col2.metric("Open Orders", 0)
        col3.metric("Dispatched/Delivered", 0)
        col4.metric("Avg. Age (Delivered)", "—")

    st.divider()
    if not all_orders.empty:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Orders by Status**")
            status_counts = all_orders["status"].value_counts().reindex(STATUSES).fillna(0)
            st.bar_chart(status_counts)
        with c2:
            st.markdown("**Orders by Region**")
            region_counts = all_orders["region"].value_counts()
            st.bar_chart(region_counts)

        st.markdown("**Top Customers by Order Count**")
        top_cust = all_orders["customer_name"].value_counts().head(8)
        st.bar_chart(top_cust)
    else:
        st.caption("No orders yet — charts will populate once orders are entered.")

# ---- ADMIN ----
if "⚙️ Admin" in tab_map:
    with tab_map["⚙️ Admin"]:
        st.subheader("Manage Customers")
        st.dataframe(customers_df, hide_index=True, use_container_width=True)

        st.markdown("**Add Customer**")
        c1, c2, c3 = st.columns(3)
        with c1:
            new_name = st.text_input("Customer Name")
        with c2:
            new_region = st.selectbox("Region", REGIONS, key="new_region")
        with c3:
            new_rsm = st.text_input("RSM Name")
        if st.button("Add Customer"):
            if new_name and new_rsm:
                insert_customer(new_name, new_region, new_rsm)
                st.success(f"Added {new_name}")
                st.rerun()
            else:
                st.warning("Enter customer name and RSM.")
