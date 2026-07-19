import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from io import BytesIO
from supabase import create_client, Client
from fpdf import FPDF

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
st.set_page_config(page_title="Carob Order Tracker", page_icon="📦", layout="wide")

NAVY = "#0C2340"
GOLD = "#F5A800"
BLUE = "#1A6FC4"
TEAL = "#0D9488"
GREEN = "#16A34A"
ORANGE = "#D97706"
RED = "#EF4444"
BG = "#F1F5F9"
CARD_BG = "#FFFFFF"
TEXT = "#0C2340"
MUTED_TEXT = "#475569"

STATUSES = ["Placed", "Confirmed", "In Production", "Dispatched", "Delivered"]
STATUS_COLORS = {
    "Placed": "#64748B",
    "Confirmed": BLUE,
    "In Production": ORANGE,
    "Dispatched": TEAL,
    "Delivered": GREEN,
}
REGIONS = ["North", "South", "East", "West"]
# Products are now managed in the database (Admin tab) instead of
# hardcoded here — see fetch_products() / insert_product().

# Who is allowed to move an order out of each status, and to which
# next status(es). Some statuses have more than one valid next step —
# e.g. a Confirmed order can go to production, OR straight to
# Dispatched if it's already in stock.
# key = current status, value = list of (next_status, roles_allowed, button_label)
STATUS_TRANSITIONS = {
    "Placed": [
        ("Confirmed", ["Sales Coordinator", "Regional Sales Person", "Management", "Admin"], "Confirm Order"),
    ],
    "Confirmed": [
        ("In Production", ["Factory", "Admin"], "Send to Production"),
        ("Dispatched", ["Factory", "Admin"], "Dispatch (already in stock)"),
    ],
    "In Production": [
        ("Dispatched", ["Factory", "Admin"], "Mark Dispatched"),
    ],
    "Dispatched": [
        ("Delivered", ["Factory", "Sales Coordinator", "Admin"], "Mark Delivered"),
    ],
}

SCHEMA = "demo"
IST = ZoneInfo("Asia/Kolkata")

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

def fetch_products() -> pd.DataFrame:
    res = supabase.table("products").select("*").order("name").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame(
        columns=["product_id", "name", "created_at"])

def fetch_orders() -> pd.DataFrame:
    res = supabase.table("orders").select(
        "*, customers(name, region, rsm), order_items(item, qty, unit)"
    ).order("order_id", desc=True).execute()
    rows = res.data or []
    flat = []
    for r in rows:
        cust = r.get("customers") or {}
        items = r.get("order_items") or []
        items_summary = ", ".join(f"{it['item']} ({it['qty']} {it['unit']})" for it in items)
        total_qty = sum(it["qty"] for it in items)
        flat.append({
            "order_id": r["order_id"],
            "customer_id": r["customer_id"],
            "customer_name": cust.get("name"),
            "region": cust.get("region"),
            "rsm": cust.get("rsm"),
            "items_summary": items_summary,
            "line_count": len(items),
            "total_qty": total_qty,
            "requested_date": r["requested_date"],
            "expected_delivery_date": r.get("expected_delivery_date"),
            "box_count": r.get("box_count"),
            "notes": r["notes"],
            "status": r["status"],
            "placed_by": r["placed_by"],
            "placed_at": r["placed_at"],
        })
    return pd.DataFrame(flat)

def fetch_order_items(order_id) -> pd.DataFrame:
    res = supabase.table("order_items").select("*").eq("order_id", order_id).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame(
        columns=["item", "qty", "unit"])

def insert_order(customer_id, items, requested_date, notes, placed_by):
    """items: list of dicts with keys item, qty, unit"""
    now = datetime.now(timezone.utc).isoformat()
    res = supabase.table("orders").insert({
        "customer_id": int(customer_id),
        "requested_date": str(requested_date),
        "notes": notes,
        "status": "Placed",
        "placed_by": placed_by,
        "placed_at": now,
    }).execute()
    order_id = res.data[0]["order_id"]

    line_rows = [
        {"order_id": order_id, "item": it["item"], "qty": int(it["qty"]), "unit": it["unit"]}
        for it in items
    ]
    supabase.table("order_items").insert(line_rows).execute()

    supabase.table("status_log").insert({
        "order_id": order_id, "status": "Placed",
        "updated_by": placed_by, "updated_at": now, "note": "",
    }).execute()
    return order_id

def update_expected_delivery(order_id, new_date):
    supabase.table("orders").update(
        {"expected_delivery_date": str(new_date)}
    ).eq("order_id", order_id).execute()

def update_order_status(order_id, new_status, updated_by, note="", box_count=None):
    now = datetime.now(timezone.utc).isoformat()
    update_payload = {"status": new_status}
    if box_count is not None:
        update_payload["box_count"] = int(box_count)
    supabase.table("orders").update(update_payload).eq("order_id", order_id).execute()
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

def insert_customers_bulk(records):
    """records: list of dicts with keys name, region, rsm"""
    if records:
        supabase.table("customers").insert(records).execute()

def build_customer_template_xlsx() -> bytes:
    """Small downloadable template so the columns/format are unambiguous."""
    template_df = pd.DataFrame([
        {"Customer Name": "Sri Auto Components #1", "Region": "South", "RSM": "Arun Kumar"},
        {"Customer Name": "Balaji Engineering Works #2", "Region": "North", "RSM": "Priya Menon"},
    ])
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        template_df.to_excel(writer, index=False, sheet_name="Customers")
    return buf.getvalue()

def insert_product(name):
    supabase.table("products").insert({"name": name}).execute()

def is_blank(value):
    """True for None, NaN, NaT, or empty string — anything that should be
    treated as 'no value set'. Plain `if value:` wrongly treats NaN as
    truthy, which is how NaT ends up crashing st.date_input."""
    if value is None or value == "":
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False

def to_ist(value):
    """Parse a UTC timestamp and convert to IST. Returns a tz-aware
    pandas Timestamp, or None if blank/unparseable."""
    if is_blank(value):
        return None
    try:
        dt = pd.to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.tz_localize("UTC")
        return dt.tz_convert(IST)
    except Exception:
        return None

def fmt_date(value):
    """ISO date/datetime string -> dd-mm-yyyy for display. Leaves blanks as '—'."""
    if value is None or value == "" or pd.isna(value):
        return "—"
    try:
        return pd.to_datetime(value).strftime("%d-%m-%Y")
    except Exception:
        return str(value)

def fmt_datetime(value):
    """UTC timestamp -> dd-mm-yyyy HH:MM IST for display."""
    dt_ist = to_ist(value)
    if dt_ist is None:
        return "—"
    return dt_ist.strftime("%d-%m-%Y %H:%M") + " IST"

def pdf_safe(text) -> str:
    """fpdf2's core fonts (Helvetica) only support Latin-1 — anything
    outside that (em-dashes, curly quotes, etc.) crashes the renderer.
    Replace unsupported characters instead of failing."""
    return str(text).encode("latin-1", "replace").decode("latin-1")

def generate_order_pdf(order, items_df) -> bytes:
    """Build a single-page printable order sheet for the factory floor.
    order: dict-like (order_id, customer_name, region, rsm, status,
           requested_date, expected_delivery_date, notes, placed_by, placed_at)
    items_df: DataFrame with columns item, qty, unit
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_margin(15)

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, pdf_safe(f"Order #{order.get('order_id')}"), ln=1)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "Carob Technologies - BTP Order Sheet", ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)
    pdf.set_draw_color(180, 180, 180)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(6)

    def info_row(label, value):
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(55, 8, pdf_safe(label), border=0)
        pdf.set_font("Helvetica", "", 11)
        display_value = str(value) if value not in (None, "", "nan") else "-"
        pdf.cell(0, 8, pdf_safe(display_value), ln=1)

    info_row("Customer:", order.get("customer_name"))
    info_row("Region:", order.get("region"))
    info_row("Regional Sales Person:", order.get("rsm"))
    info_row("Status:", order.get("status"))
    info_row("Requested Date:", fmt_date(order.get("requested_date")))
    info_row("Expected Delivery:", fmt_date(order.get("expected_delivery_date")))
    info_row("Placed By:", order.get("placed_by"))
    info_row("Placed At:", fmt_datetime(order.get("placed_at")))
    box_count = order.get("box_count")
    if not is_blank(box_count):
        info_row("No. of Boxes:", int(box_count))

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Items", ln=1)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(100, 8, "Item", border=1, fill=True)
    pdf.cell(40, 8, "Quantity", border=1, fill=True)
    pdf.cell(40, 8, "Unit", border=1, fill=True, ln=1)

    pdf.set_font("Helvetica", "", 10)
    for _, row in items_df.iterrows():
        pdf.cell(100, 8, pdf_safe(row["item"]), border=1)
        pdf.cell(40, 8, pdf_safe(row["qty"]), border=1)
        pdf.cell(40, 8, pdf_safe(row["unit"]), border=1, ln=1)

    notes = order.get("notes")
    if notes and str(notes).strip() and str(notes) != "nan":
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "Notes:", ln=1)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, pdf_safe(notes))

    pdf.ln(14)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(90, 8, "Received by: ______________________", border=0)
    pdf.cell(0, 8, "Date: ______________________", border=0, ln=1)

    return bytes(pdf.output())



# ---------------------------------------------------------
# STYLING (self-contained dark theme — doesn't rely on config.toml)
# ---------------------------------------------------------
st.markdown(f"""
<style>
    #MainMenu, footer, header {{ visibility: hidden; }}

    html, body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stHeader"],
    [data-testid="stMain"],
    .main,
    .block-container {{
        background-color: {BG} !important;
    }}
    .block-container {{ padding-top: 1rem !important; }}

    .stApp, .stApp p, .stApp span, .stApp label, .stApp li, .stApp div {{ color: {TEXT} !important; }}
    h1, h2, h3, h4, h5, h6 {{ color: {NAVY} !important; }}
    .stMarkdown, .stCaption, [data-testid="stCaptionContainer"] {{ color: {MUTED_TEXT} !important; }}
    [data-testid="stMetricLabel"] p {{ color: {MUTED_TEXT} !important; }}
    [data-testid="stMetricValue"] {{ color: {NAVY} !important; }}
    [data-testid="stMetricValue"] div {{ color: {NAVY} !important; }}
    [data-testid="stWidgetLabel"] p {{ color: {TEXT} !important; }}

    section[data-testid="stSidebar"] {{ background-color: {NAVY} !important; }}
    section[data-testid="stSidebar"] * {{ color: #F1F5F9 !important; }}

    .stDataFrame, .stDataFrame * {{ color: {TEXT} !important; }}
    [data-testid="stContainer"], div[data-testid="stVerticalBlockBorderWrapper"] {{
        background-color: {CARD_BG} !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 10px !important;
    }}
    input, textarea, select {{
        background-color: {CARD_BG} !important;
        color: {TEXT} !important;
    }}
    [data-baseweb="select"] > div {{
        background-color: {CARD_BG} !important;
        color: {TEXT} !important;
    }}
    /* Selectbox inside the sidebar: the sidebar's own "make everything
       light text" rule above otherwise wins and makes the dropdown's
       text and arrow icon invisible on its white background.
       Scoping off Streamlit's own stSelectbox testid rather than
       BaseWeb's internal [data-baseweb="select"] — repeated attempts
       targeting the latter didn't work at all, suggesting it isn't
       the right element in this Streamlit version. testid is stable
       across versions since Streamlit adds it itself. */
    section[data-testid="stSidebar"] [data-testid="stSelectbox"][data-testid="stSelectbox"][data-testid="stSelectbox"] {{
        background-color: {CARD_BG} !important;
    }}
    section[data-testid="stSidebar"] [data-testid="stSelectbox"][data-testid="stSelectbox"][data-testid="stSelectbox"] * {{
        color: {NAVY} !important;
        -webkit-text-fill-color: {NAVY} !important;
        fill: {NAVY} !important;
        background-color: transparent;
    }}
    section[data-testid="stSidebar"] [data-testid="stSelectbox"][data-testid="stSelectbox"][data-testid="stSelectbox"] > div {{
        background-color: {CARD_BG} !important;
    }}
    section[data-testid="stSidebar"] [data-testid="stSelectbox"][data-testid="stSelectbox"][data-testid="stSelectbox"] input::placeholder {{
        color: {MUTED_TEXT} !important;
        opacity: 1 !important;
        -webkit-text-fill-color: {MUTED_TEXT} !important;
    }}
    /* Belt-and-braces: keep the baseweb-targeted version too in case
       it does match in some Streamlit versions. */
    section[data-testid="stSidebar"] [data-baseweb="select"][data-baseweb="select"][data-baseweb="select"] > div {{
        background-color: {CARD_BG} !important;
        color: {NAVY} !important;
    }}
    section[data-testid="stSidebar"] [data-baseweb="select"][data-baseweb="select"][data-baseweb="select"] * {{
        color: {NAVY} !important;
        -webkit-text-fill-color: {NAVY} !important;
    }}
    section[data-testid="stSidebar"] [data-baseweb="select"][data-baseweb="select"][data-baseweb="select"] svg,
    section[data-testid="stSidebar"] [data-baseweb="select"][data-baseweb="select"][data-baseweb="select"] svg path {{
        fill: {NAVY} !important;
    }}
    /* Fallback in case the arrow icon is rendered via CSS mask +
       background-color instead of SVG fill (some icon-font systems). */
    section[data-testid="stSidebar"] [data-baseweb="select"][data-baseweb="select"][data-baseweb="select"] [data-testid*="Icon"] {{
        background-color: {NAVY} !important;
        color: {NAVY} !important;
    }}
    /* While the dropdown is focused/searching, BaseWeb shows the current
       value as a placeholder (separate from normal text color, and
       browsers dim placeholders by default even when a color is set). */
    section[data-testid="stSidebar"] [data-baseweb="select"][data-baseweb="select"][data-baseweb="select"] input::placeholder {{
        color: {MUTED_TEXT} !important;
        opacity: 1 !important;
        -webkit-text-fill-color: {MUTED_TEXT} !important;
    }}

    /* Top bar */
    .top-bar {{
        background: {NAVY}; border-bottom: 3px solid {GOLD};
        border-radius: 10px; padding: 14px 24px; margin-bottom: 1.2rem;
        display: flex; align-items: center; justify-content: space-between;
    }}
    .top-bar .brand, .stApp .top-bar .brand {{ font-size: 18px; font-weight: 700; color: white !important; letter-spacing: 0.5px; }}
    .stApp .top-bar .brand span {{ color: {GOLD} !important; }}
    .stApp .top-bar .brand-sub {{ font-size: 11px; color: rgba(255,255,255,0.55) !important; margin-top: 2px; }}
    .stApp .top-bar .org {{ font-size: 12px; color: rgba(255,255,255,0.5) !important; text-align: right; }}

    /* Section header pills */
    .section-hdr {{
        background: {NAVY};
        padding: 8px 16px; border-radius: 8px;
        font-weight: 700; font-size: 12px; letter-spacing: 0.6px;
        text-transform: uppercase; margin: 1rem 0 0.8rem 0; display: inline-block;
    }}
    .stApp .section-hdr, .stApp .section-hdr * {{ color: {GOLD} !important; }}

    /* KPI cards */
    .kpi-card {{
        background: {CARD_BG}; border-radius: 12px; padding: 16px 18px;
        border: 1px solid #E2E8F0; box-shadow: 0 1px 4px rgba(0,0,0,0.06); min-height: 100px;
    }}
    .stApp .kpi-lbl {{ font-size: 11px; font-weight: 600; color: {MUTED_TEXT} !important;
        text-transform: uppercase; letter-spacing: 0.5px; }}
    .stApp .kpi-val {{ font-size: 24px; font-weight: 700; color: {NAVY} !important; margin-top: 4px; }}
    .kpi-sub {{ font-size: 12px; font-weight: 600; margin-top: 6px; }}
    .kpi-icon {{ float: right; font-size: 20px; }}
    .stApp .kpi-sub.c-green {{ color: {GREEN} !important; }}
    .stApp .kpi-sub.c-orange {{ color: {ORANGE} !important; }}
    .stApp .kpi-sub.c-red {{ color: {RED} !important; }}
    .stApp .kpi-sub.c-blue {{ color: {BLUE} !important; }}

    /* Status badges */
    .status-badge {{
        padding: 3px 10px; border-radius: 20px;
        font-size: 0.75rem; font-weight: 700;
        display: inline-block;
    }}
    .stApp .status-badge, .stApp .status-badge * {{ color: white !important; }}

    /* Tabs — flat underline style (matching another Carob app's design) */
    .stTabs [data-baseweb="tab-list"] {{
        background: transparent; border-radius: 0; padding: 0 0 0 0;
        gap: 28px; border-bottom: 1px solid #E2E8F0;
    }}
    .stTabs [data-baseweb="tab"] {{
        background: transparent !important;
        color: {MUTED_TEXT} !important; font-weight: 600;
        font-size: 14px; padding: 8px 0; border-radius: 0;
    }}
    .stTabs [data-baseweb="tab"] p {{ color: {MUTED_TEXT} !important; font-weight: 600; }}
    .stTabs [aria-selected="true"] {{
        background: transparent !important;
        border-bottom: 2px solid {NAVY} !important;
    }}
    .stTabs [aria-selected="true"] p {{ color: {NAVY} !important; font-weight: 700; }}

    /* Footer */
    .app-footer {{
        background: {NAVY}; border-radius: 10px; padding: 8px 18px; margin-top: 1.5rem;
        display: flex; justify-content: space-between; align-items: center;
    }}
    .stApp .app-footer span {{ color: rgba(255,255,255,0.45) !important; font-size: 11px; }}
    .stApp .app-footer .powered {{ color: {GOLD} !important; font-weight: 700; font-size: 12px; }}
</style>
""", unsafe_allow_html=True)

def section_header(text):
    st.markdown(f'<div class="section-hdr">{text}</div>', unsafe_allow_html=True)

def kpi_card(col, value, label, sub, color_class="c-blue", icon="📦"):
    with col:
        st.markdown(f"""
        <div class="kpi-card">
            <span class="kpi-icon">{icon}</span>
            <div class="kpi-lbl">{label}</div>
            <div class="kpi-val">{value}</div>
            <div class="kpi-sub {color_class}">{sub}</div>
        </div>
        """, unsafe_allow_html=True)

def status_badge_html(status):
    color = STATUS_COLORS.get(status, "#64748B")
    return f'<span class="status-badge" style="background-color:{color}">{status}</span>'

st.markdown(f"""
<div class="top-bar">
    <div>
        <div class="brand">📦 <span>C</span>AROB ORDER TRACKER</div>
        <div class="brand-sub">Customer to Factory order visibility</div>
    </div>
    <div style="text-align:center;">
        <div style="font-size:15px;font-weight:700;color:white;">BTP Order Tracking Portal</div>
        <div style="font-size:11px;color:rgba(255,255,255,0.5);">Powered by Carob Technologies</div>
    </div>
    <div class="org">Carob Technologies</div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# ROLE SELECTOR (simulated auth — Phase 2: swap for Supabase Auth)
# ---------------------------------------------------------
with st.sidebar:
    st.markdown("### 👤 Viewing as")
    role = st.selectbox("Role", ["Sales Coordinator", "Factory", "Regional Sales Person", "Management", "Admin"])
    display_name = role
    st.caption("Role-based login (Supabase Auth) replaces this switch in the next phase.")
    st.divider()
    st.caption("Carob Technologies · Supabase-backed")

customers_df = fetch_customers()
if customers_df.empty:
    st.warning(
        f"No customers found in `{SCHEMA}.customers` yet. "
        "Use the Admin tab (as Admin) to add your first customer — "
        "Order Entry will unlock once at least one exists."
    )

customer_map = dict(zip(customers_df["name"], customers_df["customer_id"]))
products_df = fetch_products()

# ---------------------------------------------------------
# TABS
# ---------------------------------------------------------
tab_names = []
if role in ["Sales Coordinator", "Admin"]:
    tab_names.append("➕ Order Entry")
tab_names.append("📋 Order Tracker")
tab_names.append("🔄 Update Status")
tab_names.append("📊 Dashboard")
if role == "Admin":
    tab_names.append("⚙️ Admin")

tabs = st.tabs(tab_names)
tab_map = dict(zip(tab_names, tabs))

# ---- ORDER ENTRY ----
if "➕ Order Entry" in tab_map:
    with tab_map["➕ Order Entry"]:
        section_header("New Order Entry")

        if customers_df.empty:
            st.warning(
                "No customers yet. Add at least one in the Admin tab "
                "before creating orders."
            )
        else:
            if "cart" not in st.session_state:
                st.session_state.cart = []

            cust_name = st.selectbox("Customer", sorted(customer_map.keys()))
            cust_row = customers_df[customers_df["name"] == cust_name].iloc[0]
            st.caption(f"Region: **{cust_row['region']}** · RSM: **{cust_row['rsm']}**")

            if products_df.empty:
                st.warning(
                    "No products set up yet. Add at least one product in the "
                    "Admin tab before creating orders."
                )
            else:
                st.markdown("**Add items to this order**")
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
                with c1:
                    item = st.selectbox("Item", sorted(products_df["name"]), key="cart_item")
                with c2:
                    qty = st.number_input("Quantity", min_value=1, value=100, step=10, key="cart_qty")
                with c3:
                    unit = st.selectbox("Unit", ["pcs", "kg", "boxes"], key="cart_unit")
                with c4:
                    st.markdown("<div style='margin-top:1.8rem'></div>", unsafe_allow_html=True)
                    if st.button("➕ Add"):
                        st.session_state.cart.append({"item": item, "qty": qty, "unit": unit})
                        st.rerun()

            if st.session_state.cart:
                st.markdown("**Items in this order**")
                for i, line in enumerate(st.session_state.cart):
                    lc1, lc2 = st.columns([5, 1])
                    lc1.write(f"{line['item']} — {line['qty']} {line['unit']}")
                    if lc2.button("Remove", key=f"remove_{i}"):
                        st.session_state.cart.pop(i)
                        st.rerun()
            else:
                st.caption("No items added yet — add at least one item above before submitting.")

            req_date = st.date_input("Requested Delivery Date",
                                       value=datetime.now() + timedelta(days=7),
                                       format="DD-MM-YYYY")
            notes = st.text_area("Notes (optional)", height=68)

            if st.button("Submit Order", type="primary", disabled=not st.session_state.cart):
                order_id = insert_order(
                    cust_row["customer_id"], st.session_state.cart, req_date, notes, display_name)
                st.success(f"Order #{order_id} placed for {cust_name} "
                           f"({len(st.session_state.cart)} item(s))")
                st.session_state.cart = []
                st.rerun()

            st.divider()
            st.markdown("**Orders entered today**")
            all_orders_preview = fetch_orders()
            if not all_orders_preview.empty:
                today_ist = datetime.now(IST).date()
                placed_ist_dates = all_orders_preview["placed_at"].apply(
                    lambda x: to_ist(x).date() if to_ist(x) is not None else None
                )
                today_orders = all_orders_preview[
                    placed_ist_dates == today_ist
                ][["order_id", "customer_name", "items_summary", "status"]].rename(
                    columns={"items_summary": "items"})
                if today_orders.empty:
                    st.caption("No orders entered yet today.")
                else:
                    st.dataframe(today_orders, hide_index=True, width='stretch')
            else:
                st.caption("No orders entered yet today.")

# ---- ORDER TRACKER ----
with tab_map["📋 Order Tracker"]:
    section_header("All Orders")
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
            mask = (orders_df["items_summary"].str.contains(f_search, case=False, na=False) |
                    orders_df["order_id"].astype(str).str.contains(f_search))
            orders_df = orders_df[mask]

        orders_df["days_open"] = orders_df["placed_at"].apply(
            lambda x: (datetime.now(timezone.utc) - pd.to_datetime(x, utc=True).to_pydatetime()).days
            if pd.notna(x) else None
        )

        display_df = orders_df.rename(columns={
            "order_id": "Order ID", "customer_name": "Customer", "region": "Region",
            "items_summary": "Items", "line_count": "Line Items", "status": "Status",
            "requested_date": "Requested Date", "expected_delivery_date": "Expected Delivery",
            "box_count": "Boxes", "placed_at": "Placed At", "rsm": "RSM", "days_open": "Days Open",
        })[["Order ID", "Customer", "Region", "Items", "Line Items", "Status",
            "Requested Date", "Expected Delivery", "Boxes", "Placed At", "RSM", "Days Open"]]

        display_df["Requested Date"] = display_df["Requested Date"].apply(fmt_date)
        display_df["Expected Delivery"] = display_df["Expected Delivery"].apply(fmt_date)
        display_df["Placed At"] = display_df["Placed At"].apply(fmt_datetime)
        display_df["Boxes"] = display_df["Boxes"].apply(lambda v: "—" if is_blank(v) else int(v))

        st.caption(f"{len(display_df)} orders")
        st.dataframe(display_df, hide_index=True, width='stretch')

        if display_df.empty:
            st.info("No orders match the current filters.")
        else:
            with st.expander("🔍 View order detail / status history"):
                sel_id = st.selectbox("Order ID", display_df["Order ID"].tolist())
                st.markdown("**Line items**")
                items_detail = fetch_order_items(int(sel_id))
                if not items_detail.empty:
                    items_detail = items_detail.rename(columns={
                        "item": "Item", "qty": "Qty", "unit": "Unit"})[["Item", "Qty", "Unit"]]
                st.dataframe(items_detail, hide_index=True, width='stretch')
                st.markdown("**Status history**")
                hist = fetch_status_log(int(sel_id))
                if not hist.empty:
                    hist = hist.rename(columns={
                        "status": "Status", "updated_by": "Updated By",
                        "updated_at": "Updated At", "note": "Note"})[
                        ["Status", "Updated By", "Updated At", "Note"]]
                    hist["Updated At"] = hist["Updated At"].apply(fmt_datetime)
                st.dataframe(hist, hide_index=True, width='stretch')

                if role in ["Factory", "Admin"]:
                    st.divider()
                    st.markdown("**🖨️ Printable order sheet**")
                    order_row = orders_df[orders_df["order_id"] == sel_id].iloc[0]
                    raw_items = fetch_order_items(int(sel_id))
                    pdf_bytes = generate_order_pdf(order_row, raw_items)
                    st.download_button(
                        "Download PDF",
                        data=pdf_bytes,
                        file_name=f"Order_{sel_id}.pdf",
                        mime="application/pdf",
                        key=f"pdf_{sel_id}",
                    )
                    st.caption("Download, then print from any browser — hand this to the factory.")
    else:
        st.info("No orders yet. Add one from the Order Entry tab.")

# ---- FACTORY VIEW ----
if "🔄 Update Status" in tab_map:
    with tab_map["🔄 Update Status"]:
        section_header("Order Status Queue")
        queue_status = st.selectbox("Show orders in status", STATUSES, index=1)
        st.markdown(status_badge_html(queue_status), unsafe_allow_html=True)
        all_orders = fetch_orders()
        queue_df = all_orders[all_orders["status"] == queue_status] if not all_orders.empty else all_orders

        if queue_df.empty:
            st.info(f"No orders currently in '{queue_status}'.")
        else:
            queue_df = queue_df.sort_values("requested_date")
            transitions = STATUS_TRANSITIONS.get(queue_status, [])
            actionable = [(nxt, roles, label) for nxt, roles, label in transitions if role in roles]
            all_roles_needed = sorted({r for _, roles, _ in transitions for r in roles})

            if transitions and not actionable:
                st.caption(f"👀 View-only here — updating orders from '{queue_status}' "
                           f"is done by: {', '.join(all_roles_needed)}.")

            for _, row in queue_df.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 3])
                    with c1:
                        st.markdown(f"**Order #{row['order_id']}** — {row['customer_name']}")
                        st.caption(f"{row['items_summary']} · Requested by {fmt_date(row['requested_date'])}")
                        current_expected = row.get("expected_delivery_date")
                        if not is_blank(current_expected):
                            st.caption(f"📅 Expected delivery: **{fmt_date(current_expected)}**")
                        else:
                            st.caption("📅 Expected delivery: _not set_")
                        if not is_blank(row.get("box_count")):
                            st.caption(f"📦 Boxes: **{int(row['box_count'])}**")
                    dispatching = any(nxt == "Dispatched" for nxt, _, _ in actionable)

                    with c2:
                        note = st.text_input("Note", key=f"note_{row['order_id']}",
                                              label_visibility="collapsed",
                                              placeholder="Optional note (e.g. 'in stock')")
                        box_count = None
                        if dispatching:
                            box_count = st.number_input(
                                "No. of boxes", min_value=1, value=1, step=1,
                                key=f"boxes_{row['order_id']}",
                                help="Number of boxes/packages this order is being dispatched in",
                            )
                    with c3:
                        if actionable:
                            btn_cols = st.columns(len(actionable))
                            for i, (nxt, roles, label) in enumerate(actionable):
                                if btn_cols[i].button(label, key=f"btn_{row['order_id']}_{nxt}"):
                                    bc = box_count if nxt == "Dispatched" else None
                                    update_order_status(int(row["order_id"]), nxt, display_name, note, bc)
                                    st.rerun()
                        elif transitions:
                            st.caption(f"Needs: {', '.join(all_roles_needed)}")

                    if role in ["Factory", "Admin"]:
                        dc1, dc2 = st.columns([3, 1])
                        with dc1:
                            try:
                                default_date = (
                                    datetime.now().date() if is_blank(current_expected)
                                    else pd.to_datetime(current_expected).date()
                                )
                            except Exception:
                                default_date = datetime.now().date()

                            new_expected = st.date_input(
                                "Expected delivery date",
                                value=default_date,
                                min_value=datetime(2020, 1, 1).date(),
                                max_value=datetime(2035, 12, 31).date(),
                                key=f"expected_{row['order_id']}",
                                label_visibility="collapsed",
                                format="DD-MM-YYYY",
                            )
                        with dc2:
                            if st.button("Save Date", key=f"save_expected_{row['order_id']}"):
                                update_expected_delivery(int(row["order_id"]), new_expected)
                                st.success("Expected delivery date updated.")
                                st.rerun()

# ---- DASHBOARD ----
with tab_map["📊 Dashboard"]:
    section_header("Overview")
    all_orders = fetch_orders()

    col1, col2, col3, col4 = st.columns(4)
    total_orders = len(all_orders)
    if not all_orders.empty:
        open_orders = len(all_orders[all_orders["status"] != "Delivered"])
        dispatched_delivered = len(all_orders[all_orders["status"].isin(["Dispatched", "Delivered"])])
        delivered = all_orders[all_orders["status"] == "Delivered"]
        avg_days = "—"
        if not delivered.empty:
            placed_dt = pd.to_datetime(delivered["placed_at"], utc=True)
            avg_days = f'{(datetime.now(timezone.utc) - placed_dt).dt.days.mean():.1f} days'
    else:
        open_orders, dispatched_delivered, avg_days = 0, 0, "—"

    kpi_card(col1, total_orders, "Total Orders", "All time", "c-blue", "📦")
    kpi_card(col2, open_orders, "Open Orders", "In progress", "c-orange", "⏳")
    kpi_card(col3, dispatched_delivered, "Dispatched / Delivered", "Fulfilled so far", "c-green", "🚚")
    kpi_card(col4, avg_days, "Avg. Age (Delivered)", "Placed to delivered", "c-blue", "📅")
    st.markdown("<br>", unsafe_allow_html=True)

    if not all_orders.empty:
        section_header("Status & Regional Breakdown")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Orders by Status**")
            status_counts = all_orders["status"].value_counts().reindex(STATUSES).fillna(0)
            st.bar_chart(status_counts)
        with c2:
            st.markdown("**Orders by Region**")
            region_counts = all_orders["region"].value_counts()
            st.bar_chart(region_counts)

        section_header("Customer Activity")
        st.markdown("**Top Customers by Order Count**")
        top_cust = all_orders["customer_name"].value_counts().head(8)
        st.bar_chart(top_cust)
    else:
        st.caption("No orders yet — charts will populate once orders are entered.")

# ---- ADMIN ----
if "⚙️ Admin" in tab_map:
    with tab_map["⚙️ Admin"]:
        section_header("Manage Customers")
        st.dataframe(customers_df, hide_index=True, width='stretch')

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

        with st.expander("📤 Bulk upload customers via Excel"):
            st.caption(
                "Columns needed: **Customer Name**, **Region**, **RSM**. "
                "Region must be one of: " + ", ".join(REGIONS) + "."
            )
            st.download_button(
                "Download template",
                data=build_customer_template_xlsx(),
                file_name="customer_upload_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            uploaded_file = st.file_uploader(
                "Upload customers Excel", type=["xlsx"], key="customer_bulk_upload"
            )

            if uploaded_file:
                try:
                    raw_df = pd.read_excel(uploaded_file, engine="openpyxl")
                except Exception as e:
                    st.error("Couldn't read that file — make sure it's a valid .xlsx file.")
                    st.exception(e)
                    raw_df = None

                if raw_df is not None and raw_df.empty:
                    st.warning("That file has no rows.")
                elif raw_df is not None:
                    cols_lower = {str(c).lower().strip(): c for c in raw_df.columns}

                    def find_col(candidates):
                        for cand in candidates:
                            if cand in cols_lower:
                                return cols_lower[cand]
                        return None

                    name_col = find_col(["customer name", "name", "customer"])
                    region_col = find_col(["region"])
                    rsm_col = find_col(["rsm", "rsm name", "regional sales person", "sales person"])

                    if not all([name_col, region_col, rsm_col]):
                        st.error(
                            "Couldn't find all required columns (Customer Name, Region, RSM). "
                            "Check the header row matches the template."
                        )
                    else:
                        existing_names = set(
                            customers_df["name"].str.strip().str.lower()
                        ) if not customers_df.empty else set()
                        seen_in_file = set()
                        preview_rows = []
                        valid_records = []

                        for _, r in raw_df.iterrows():
                            name = str(r[name_col]).strip() if pd.notna(r.get(name_col)) else ""
                            region_raw = str(r[region_col]).strip() if pd.notna(r.get(region_col)) else ""
                            rsm = str(r[rsm_col]).strip() if pd.notna(r.get(rsm_col)) else ""
                            region_match = next(
                                (rg for rg in REGIONS if rg.lower() == region_raw.lower()), None)

                            if not name or not rsm:
                                status = "⚠️ Missing name/RSM"
                            elif not region_match:
                                status = f"⚠️ Invalid region '{region_raw}'"
                            elif name.lower() in existing_names:
                                status = "⏭️ Duplicate (already exists)"
                            elif name.lower() in seen_in_file:
                                status = "⏭️ Duplicate (in this file)"
                            else:
                                status = "✅ Ready"
                                seen_in_file.add(name.lower())
                                valid_records.append(
                                    {"name": name, "region": region_match, "rsm": rsm})

                            preview_rows.append({
                                "Customer Name": name or "(blank)",
                                "Region": region_match or region_raw or "(blank)",
                                "RSM": rsm or "(blank)",
                                "Status": status,
                            })

                        preview_df = pd.DataFrame(preview_rows)
                        st.dataframe(preview_df, hide_index=True, width='stretch')
                        st.caption(f"{len(valid_records)} of {len(preview_df)} rows ready to upload.")

                        if valid_records:
                            if st.button(f"Upload {len(valid_records)} customer(s)", type="primary"):
                                insert_customers_bulk(valid_records)
                                st.success(f"Added {len(valid_records)} customer(s).")
                                st.rerun()

        st.divider()
        section_header("Manage Products")
        if products_df.empty:
            st.caption("No products yet — add one below.")
        else:
            st.dataframe(products_df[["name"]].rename(columns={"name": "Product"}),
                         hide_index=True, width='stretch')

        st.markdown("**Add Product**")
        pc1, pc2 = st.columns([3, 1])
        with pc1:
            new_product = st.text_input("Product Name", key="new_product_name")
        with pc2:
            st.markdown("<div style='margin-top:1.8rem'></div>", unsafe_allow_html=True)
            if st.button("Add Product"):
                if new_product.strip():
                    if new_product.strip() in products_df["name"].values:
                        st.warning(f"'{new_product.strip()}' already exists.")
                    else:
                        insert_product(new_product.strip())
                        st.success(f"Added {new_product.strip()}")
                        st.rerun()
                else:
                    st.warning("Enter a product name.")

# ---------------------------------------------------------
# FOOTER
# ---------------------------------------------------------
st.markdown(f"""
<div class="app-footer">
    <span>BTP Order Tracking Portal</span>
    <span class="powered">Powered by Carob Technologies</span>
    <span>Viewing as: {role}</span>
</div>
""", unsafe_allow_html=True)
