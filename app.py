import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import random

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

DB_PATH = "order_tracker.db"

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

# ---------------------------------------------------------
# DB SETUP
# ---------------------------------------------------------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS customers (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, region TEXT, rsm TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER, item TEXT, qty INTEGER, unit TEXT,
        requested_date TEXT, notes TEXT, status TEXT,
        placed_by TEXT, placed_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS status_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER, status TEXT, updated_by TEXT,
        updated_at TEXT, note TEXT)""")
    conn.commit()

    # Seed only if empty
    c.execute("SELECT COUNT(*) FROM customers")
    if c.fetchone()[0] == 0:
        seed_data(conn)
    conn.close()

def seed_data(conn):
    c = conn.cursor()
    rsms = ["Arun Kumar", "Priya Menon", "Suresh Babu", "Divya Raj"]
    customer_names = [f"{a} {b}" for a, b in zip(
        ["Sri", "Balaji", "Om", "New", "Modern", "United", "National", "Prime",
         "Star", "Royal", "Metro", "Classic", "Sunrise", "Elite", "Apex"],
        ["Auto Components", "Engineering Works", "Industries", "Motors",
         "Fabricators", "Traders", "Enterprises", "Corp", "Industries Ltd",
         "Auto Parts"]
    )]
    random.seed(42)
    for i in range(15):
        name = f"{customer_names[i % len(customer_names)]} #{i+1}"
        c.execute("INSERT INTO customers (name, region, rsm) VALUES (?,?,?)",
                   (name, random.choice(REGIONS), random.choice(rsms)))
    conn.commit()

    # seed ~40 sample orders over the last 20 days
    c.execute("SELECT customer_id FROM customers")
    cust_ids = [r[0] for r in c.fetchall()]
    for i in range(40):
        cust = random.choice(cust_ids)
        item = random.choice(ITEMS)
        qty = random.choice([50, 100, 150, 200, 250, 500])
        placed_days_ago = random.randint(0, 20)
        placed_at = (datetime.now() - timedelta(days=placed_days_ago)).strftime("%Y-%m-%d %H:%M")
        req_date = (datetime.now() + timedelta(days=random.randint(2, 15))).strftime("%Y-%m-%d")
        status = random.choices(STATUSES, weights=[15, 20, 25, 20, 20])[0]
        c.execute("""INSERT INTO orders
            (customer_id, item, qty, unit, requested_date, notes, status, placed_by, placed_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (cust, item, qty, "pcs", req_date, "", status, "Sales Coordinator", placed_at))
        order_id = c.lastrowid
        c.execute("""INSERT INTO status_log (order_id, status, updated_by, updated_at, note)
            VALUES (?,?,?,?,?)""", (order_id, "Placed", "Sales Coordinator", placed_at, ""))
    conn.commit()

def df_query(query, params=()):
    conn = get_conn()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def execute(query, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    last_id = c.lastrowid
    conn.close()
    return last_id

init_db()

# ---------------------------------------------------------
# STYLING
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

    /* Force readable light text everywhere, on top of whatever base theme is active */
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
    <h1>📦 Order Tracker POC</h1>
    <p>Carob Technologies — Customer to Factory order visibility</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# ROLE SELECTOR (simulated auth for POC)
# ---------------------------------------------------------
with st.sidebar:
    st.markdown("### 👤 Viewing as")
    role = st.selectbox("Role", ["Sales Coordinator", "Factory", "RSM / Management", "Admin"])
    st.caption("In the live version, this will be based on login — shown here as a switch for demo purposes.")
    st.divider()
    st.caption("POC build · Carob Technologies")

customers_df = df_query("SELECT * FROM customers")
customer_map = dict(zip(customers_df["name"], customers_df["customer_id"]))

def status_badge(status):
    color = STATUS_COLORS.get(status, "#666")
    return f'<span class="status-badge" style="background-color:{color}">{status}</span>'

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
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            order_id = execute("""INSERT INTO orders
                (customer_id, item, qty, unit, requested_date, notes, status, placed_by, placed_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (int(cust_row["customer_id"]), item, qty, unit, str(req_date), notes,
                 "Placed", "Sales Coordinator", now))
            execute("""INSERT INTO status_log (order_id, status, updated_by, updated_at, note)
                VALUES (?,?,?,?,?)""", (order_id, "Placed", "Sales Coordinator", now, ""))
            st.success(f"Order #{order_id} placed for {cust_name}")
            st.rerun()

        st.divider()
        st.markdown("**Orders entered today**")
        today = datetime.now().strftime("%Y-%m-%d")
        today_orders = df_query("""
            SELECT o.order_id, c.name as customer, o.item, o.qty, o.status
            FROM orders o JOIN customers c ON o.customer_id = c.customer_id
            WHERE o.placed_at LIKE ?
            ORDER BY o.order_id DESC""", (f"{today}%",))
        if today_orders.empty:
            st.caption("No orders entered yet today.")
        else:
            st.dataframe(today_orders, hide_index=True, use_container_width=True)

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

    query = """
        SELECT o.order_id as 'Order ID', c.name as Customer, c.region as Region,
               o.item as Item, o.qty as Qty, o.status as Status,
               o.requested_date as 'Requested Date', o.placed_at as 'Placed At',
               c.rsm as RSM
        FROM orders o JOIN customers c ON o.customer_id = c.customer_id
        ORDER BY o.order_id DESC
    """
    orders_df = df_query(query)

    if f_customer:
        orders_df = orders_df[orders_df["Customer"].isin(f_customer)]
    if f_region:
        orders_df = orders_df[orders_df["Region"].isin(f_region)]
    if f_status:
        orders_df = orders_df[orders_df["Status"].isin(f_status)]
    if f_search:
        mask = (orders_df["Item"].str.contains(f_search, case=False, na=False) |
                orders_df["Order ID"].astype(str).str.contains(f_search))
        orders_df = orders_df[mask]

    orders_df["Days Open"] = orders_df["Placed At"].apply(
        lambda x: (datetime.now() - datetime.strptime(x, "%Y-%m-%d %H:%M")).days)

    st.caption(f"{len(orders_df)} orders")
    display_df = orders_df.copy()
    st.dataframe(
        display_df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Status": st.column_config.TextColumn("Status"),
        }
    )

    with st.expander("🔍 View order detail / status history"):
        if not orders_df.empty:
            sel_id = st.selectbox("Order ID", orders_df["Order ID"].tolist())
            hist = df_query("""SELECT status as Status, updated_by as 'Updated By',
                updated_at as 'Updated At', note as Note
                FROM status_log WHERE order_id = ? ORDER BY log_id""", (int(sel_id),))
            st.dataframe(hist, hide_index=True, use_container_width=True)

# ---- FACTORY VIEW ----
if "🏭 Factory View" in tab_map:
    with tab_map["🏭 Factory View"]:
        st.subheader("Factory Queue")
        queue_status = st.selectbox("Show orders in status", STATUSES, index=1)
        queue_df = df_query("""
            SELECT o.order_id, c.name as customer, o.item, o.qty, o.requested_date
            FROM orders o JOIN customers c ON o.customer_id = c.customer_id
            WHERE o.status = ?
            ORDER BY o.requested_date ASC""", (queue_status,))

        if queue_df.empty:
            st.info(f"No orders currently in '{queue_status}'.")
        else:
            next_status_idx = STATUSES.index(queue_status) + 1
            next_status = STATUSES[next_status_idx] if next_status_idx < len(STATUSES) else None

            for _, row in queue_df.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 2])
                    with c1:
                        st.markdown(f"**Order #{row['order_id']}** — {row['customer']}")
                        st.caption(f"{row['item']} · Qty: {row['qty']} · Needed by {row['requested_date']}")
                    with c2:
                        note = st.text_input("Note", key=f"note_{row['order_id']}", label_visibility="collapsed", placeholder="Optional note")
                    with c3:
                        if next_status and st.button(f"Move to '{next_status}'", key=f"btn_{row['order_id']}"):
                            now = datetime.now().strftime("%Y-%m-%d %H:%M")
                            execute("UPDATE orders SET status = ? WHERE order_id = ?",
                                    (next_status, int(row["order_id"])))
                            execute("""INSERT INTO status_log (order_id, status, updated_by, updated_at, note)
                                VALUES (?,?,?,?,?)""",
                                (int(row["order_id"]), next_status, "Factory", now, note))
                            st.rerun()

# ---- DASHBOARD ----
with tab_map["📊 Dashboard"]:
    st.subheader("Overview")
    all_orders = df_query("""
        SELECT o.*, c.name as customer_name, c.region, c.rsm
        FROM orders o JOIN customers c ON o.customer_id = c.customer_id""")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Orders", len(all_orders))
    col2.metric("Open Orders", len(all_orders[all_orders["status"] != "Delivered"]))
    col3.metric("Dispatched/Delivered", len(all_orders[all_orders["status"].isin(["Dispatched", "Delivered"])]))
    avg_days = "—"
    if not all_orders.empty:
        all_orders["placed_dt"] = pd.to_datetime(all_orders["placed_at"])
        delivered = all_orders[all_orders["status"] == "Delivered"]
        if not delivered.empty:
            avg_days = f'{(datetime.now() - delivered["placed_dt"]).dt.days.mean():.1f} days'
    col4.metric("Avg. Age (Delivered)", avg_days)

    st.divider()
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
                execute("INSERT INTO customers (name, region, rsm) VALUES (?,?,?)",
                        (new_name, new_region, new_rsm))
                st.success(f"Added {new_name}")
                st.rerun()
            else:
                st.warning("Enter customer name and RSM.")

        st.divider()
        if st.button("🔄 Reset demo data", type="secondary"):
            conn = get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM orders")
            c.execute("DELETE FROM status_log")
            c.execute("DELETE FROM customers")
            conn.commit()
            conn.close()
            init_db()
            st.success("Demo data reset.")
            st.rerun()
