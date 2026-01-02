import streamlit as st
import pandas as pd
from supabase import create_client
import altair as alt

# ============================================================
# CONFIG
# ============================================================
st.set_page_config(page_title="The Young Shall Grow – Njangi", layout="wide")
st.title("🌱 The Young Shall Grow – Njangi")

# ============================================================
# SUPABASE SECRETS
# Streamlit Secrets (TOML) must contain:
# SUPABASE_URL = "https://xxxx.supabase.co"
# SUPABASE_ANON_KEY = "xxxxx"
# ============================================================
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("❌ Missing SUPABASE_URL or SUPABASE_ANON_KEY in Streamlit Secrets.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================================
# HELPERS
# ============================================================
def safe_df(data) -> pd.DataFrame:
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)

@st.cache_data(ttl=30)
def load_table(table_name: str, limit: int | None = None) -> pd.DataFrame:
    """
    Load a table from Supabase. Returns empty DF if blocked/missing.
    """
    try:
        q = supabase.table(table_name).select("*")
        if limit:
            q = q.limit(limit)
        res = q.execute()
        return safe_df(res.data)
    except Exception as e:
        st.warning(f"⚠️ Could not load '{table_name}'. (Table missing or RLS blocked)")
        st.caption(str(e))
        return pd.DataFrame()

def pick_col(df: pd.DataFrame, options: list[str]) -> str | None:
    for c in options:
        if c in df.columns:
            return c
    return None

def to_number(s):
    return pd.to_numeric(s, errors="coerce").fillna(0)

def money(x):
    try:
        return f"${float(x):,.0f}"
    except Exception:
        return "$0"

# ============================================================
# LOAD DATA (common Njangi tables)
# ============================================================
members_df            = load_table("members")
contrib_df            = load_table("contributions")
foundation_pay_df     = load_table("foundation_payments")
loans_df              = load_table("loans")
fines_df              = load_table("fines")
payouts_df            = load_table("payouts")
history_df            = load_table("history", limit=200)
sureties_df           = load_table("sureties")

# ============================================================
# COMPUTE METRICS (robust to column name differences)
# ============================================================
# Members count
members_count = len(members_df) if not members_df.empty else 0

# Contributions total (Njangi Pot)
contrib_amount_col = pick_col(contrib_df, ["amount", "amount_paid", "contribution_amount", "paid_amount", "value"])
pot_total = to_number(contrib_df[contrib_amount_col]).sum() if (not contrib_df.empty and contrib_amount_col) else 0

# Foundation total (from foundation_payments.amount_paid or amount)
foundation_amount_col = pick_col(foundation_pay_df, ["amount_paid", "amount", "paid_amount", "value"])
foundation_total = to_number(foundation_pay_df[foundation_amount_col]).sum() if (not foundation_pay_df.empty and foundation_amount_col) else 0

# Outstanding Loans / Total Due
# Try common columns
loan_due_col = pick_col(loans_df, ["total_due", "amount_due", "balance", "due_amount", "remaining_due"])
loan_principal_col = pick_col(loans_df, ["principal", "amount", "loan_amount"])
outstanding_loans_due = to_number(loans_df[loan_due_col]).sum() if (not loans_df.empty and loan_due_col) else 0

# Total interest (if present)
interest_col = pick_col(history_df, ["interest", "interest_amount", "interest_generated"])
total_interest = to_number(history_df[interest_col]).sum() if (not history_df.empty and interest_col) else 0

# ============================================================
# SIDEBAR NAV (like your website)
# ============================================================
st.sidebar.markdown("### 📌 Menu")
page = st.sidebar.radio(
    "Go to",
    [
        "Dashboard",
        "Members",
        "Contributions",
        "Foundation Payments",
        "Loans",
        "Fines",
        "Payouts",
        "History",
        "Sureties",
    ],
    index=0
)

st.sidebar.markdown("---")
st.sidebar.metric("Total Interest", money(total_interest))
st.sidebar.caption("Tip: If data shows 0, Streamlit is likely connected to an empty DB or RLS is blocking reads.")

# ============================================================
# DASHBOARD PAGE
# ============================================================
if page == "Dashboard":
    st.subheader("📊 Dashboard")

    # KPI cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Njangi Pot", money(pot_total), help="Sum of contributions")
    c2.metric("Foundation", money(foundation_total), help="Sum of foundation payments")
    c3.metric("Outstanding Loans", money(outstanding_loans_due), help="Sum of loans due/balance")
    c4.metric("Members", f"{members_count}", help="Rotation list size")

    st.markdown("---")

    # Top 10 contribution chart
    st.subheader("📈 Contributions (Top 10)")
    if contrib_df.empty or not contrib_amount_col:
        st.info("No contributions found (or column name not recognized).")
    else:
        name_col = pick_col(contrib_df, ["member_name", "name", "member", "full_name"])
        member_id_col = pick_col(contrib_df, ["member_id", "user_id"])
        created_col = pick_col(contrib_df, ["created_at", "date", "paid_at", "timestamp"])

        work = contrib_df.copy()
        work[contrib_amount_col] = to_number(work[contrib_amount_col])

        # Try to map member names if only member_id exists
        if (not name_col) and member_id_col and not members_df.empty:
            mem_id_col = pick_col(members_df, ["id", "member_id"])
            mem_name_col = pick_col(members_df, ["name", "full_name", "member_name"])
            if mem_id_col and mem_name_col:
                work = work.merge(
                    members_df[[mem_id_col, mem_name_col]].rename(columns={mem_id_col: member_id_col, mem_name_col: "member_name_join"}),
                    on=member_id_col,
                    how="left"
                )
                name_col = "member_name_join"

        if not name_col:
            # fallback bucket
            work["member_name_fallback"] = "Member"
            name_col = "member_name_fallback"

        top = (
            work.groupby(name_col, dropna=False)[contrib_amount_col]
            .sum()
            .sort_values(ascending=False)
            .head(10)
            .reset_index()
            .rename(columns={name_col: "Member", contrib_amount_col: "Amount"})
        )

        chart = (
            alt.Chart(top)
            .mark_bar()
            .encode(
                x=alt.X("Member:N", sort="-y"),
                y=alt.Y("Amount:Q"),
                tooltip=["Member", alt.Tooltip("Amount:Q", format=",.0f")]
            )
            .properties(height=320)
        )
        st.altair_chart(chart, use_container_width=True)

    st.markdown("---")

    # Pie chart: Pot vs Foundation vs Loans Due
    st.subheader("🥧 Pot vs Foundation vs Loans Due")
    pie_df = pd.DataFrame({
        "Category": ["Pot", "Foundation", "Loans Due"],
        "Value": [float(pot_total), float(foundation_total), float(outstanding_loans_due)]
    })

    pie = (
        alt.Chart(pie_df)
        .mark_arc()
        .encode(
            theta="Value:Q",
            color="Category:N",
            tooltip=["Category", alt.Tooltip("Value:Q", format=",.0f")]
        )
        .properties(height=360)
    )
    st.altair_chart(pie, use_container_width=True)

    st.markdown("---")

    # Recent Activity
    st.subheader("🕒 Recent Activity")
    if history_df.empty:
        st.info("No history/activity found.")
    else:
        # Try to format typical columns
        time_col = pick_col(history_df, ["created_at", "time", "date", "timestamp"])
        type_col = pick_col(history_df, ["type", "action", "event_type", "category"])
        member_col = pick_col(history_df, ["member_name", "name", "member", "full_name"])
        amount_col = pick_col(history_df, ["amount", "value", "amount_paid"])
        interest_pct_col = pick_col(history_df, ["interest_pct", "interest_rate", "interest_percent"])
        total_due_col = pick_col(history_df, ["total_due", "amount_due", "due_amount"])

        show_cols = [c for c in [time_col, type_col, member_col, amount_col, interest_pct_col, total_due_col] if c]
        view = history_df[show_cols].copy() if show_cols else history_df.copy()

        if time_col and time_col in view.columns:
            # keep as text if parsing fails
            try:
                view[time_col] = pd.to_datetime(view[time_col], errors="ignore")
                view = view.sort_values(time_col, ascending=False)
            except Exception:
                pass

        st.dataframe(view.head(20), use_container_width=True)

# ============================================================
# TABLE PAGES
# ============================================================
def table_page(title: str, df: pd.DataFrame):
    st.subheader(title)
    if df.empty:
        st.info("No data found.")
    else:
        st.dataframe(df, use_container_width=True)

if page == "Members":
    table_page("👥 Members", members_df)

elif page == "Contributions":
    table_page("💰 Contributions", contrib_df)

elif page == "Foundation Payments":
    table_page("🏦 Foundation Payments", foundation_pay_df)

elif page == "Loans":
    table_page("💳 Loans", loans_df)

elif page == "Fines":
    table_page("⚠️ Fines", fines_df)

elif page == "Payouts":
    table_page("💸 Payouts", payouts_df)

elif page == "History":
    table_page("🧾 History", history_df)

elif page == "Sureties":
    table_page("🛡️ Sureties", sureties_df)

st.caption("✅ If you see 0s but your website shows data, your Streamlit SUPABASE_URL/ANON_KEY are pointing to a different Supabase project.")
