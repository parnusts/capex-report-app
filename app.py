from st_aggrid import AgGrid, GridOptionsBuilder
from st_aggrid.shared import GridUpdateMode
import streamlit as st
import pandas as pd
import mysql.connector
import duckdb
import gspread
from gspread_dataframe import set_with_dataframe

# --- STEP 1: Connect to MySQL (Cached) ---
@st.cache_data(ttl=300) # Cache data for 5 minutes
def fetch_tables():
    """Establishes a connection and fetches data from MySQL."""
    conn = mysql.connector.connect(
        host="103.28.240.24",
        user="stsdriveView",
        password="AsWq!2022Zxc",
        database="stsdrive_intranet"
    )
    try:
        df_capex = pd.read_sql("SELECT * FROM capex_list", conn)
        df_po = pd.read_sql("SELECT * FROM po_order", conn)
        df_po_detail = pd.read_sql("SELECT * FROM po_order_detail", conn)
        df_div = pd.read_sql("SELECT * FROM division", conn)
        df_type = pd.read_sql("SELECT * FROM capex_budget_type", conn)
        df_company2 = pd.read_sql("SELECT * FROM company2", conn)
    finally:
        conn.close()
    return df_capex, df_po, df_po_detail, df_div, df_type, df_company2

# --- NEW: GOOGLE SHEETS CONNECTION ---
@st.cache_resource # Cache the connection itself
def get_gspread_client():
    """Connects to Google Sheets using service account credentials."""
    return gspread.service_account_from_dict(st.secrets["gcp_service_account"])

def update_google_sheet(df, sheet_url, worksheet_name):
    """Updates a Google Sheet worksheet with a pandas DataFrame."""
    try:
        gc = get_gspread_client()
        spreadsheet = gc.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet(worksheet_name)
        
        # Clear the worksheet and write the new dataframe
        worksheet.clear()
        set_with_dataframe(worksheet, df)
        return True
    except Exception as e:
        st.error(f"Failed to update Google Sheet: {e}")
        return False

# --- STEP 3: Register DataFrames into DuckDB ---
def load_to_duckdb(dfs: dict):
    con = duckdb.connect()
    for name, df in dfs.items():
        con.register(name, df)
    return con

# --- Main App Configuration ---
st.set_page_config(layout="wide")
# Place this right after st.set_page_config()


# Create the custom header



# Fetch data and load into DuckDB
df_capex, df_po, df_po_detail, df_div, df_type, df_company2 = fetch_tables()
con = load_to_duckdb({
    "capex_list": df_capex,
    "po_order": df_po,
    "po_order_detail": df_po_detail,
    "division": df_div,
    "capex_budget_type": df_type,
     "company2": df_company2
})

# Run SQL to get base data
sql = """
SELECT
    COALESCE(com2.name, 'No Company') AS company_name,
    COALESCE(d.name, 'No Division') AS division,
    ct.name AS capex_type,
    cl.capex_id,
    COALESCE(po.po_no,'') AS po_no,
    COALESCE(CAST(po.po_date AS VARCHAR), '') AS po_date,
    ROUND(MAX(CAST(cl.qty AS DOUBLE) * CAST(cl.unit_cost AS DOUBLE)), 2) AS capex_amount,
    ROUND(SUM(COALESCE(CAST(pod.qty AS DOUBLE) * CAST(pod.unit_price AS DOUBLE),0)), 2) AS po_line_amount
FROM capex_list cl
LEFT JOIN capex_budget_type ct ON cl.budget_type_id = ct.id
LEFT JOIN po_order_detail pod ON cl.capex_id = pod.expense_id
LEFT JOIN po_order po ON pod.po_id = po.po_id
LEFT JOIN division d ON cl.div_id = d.id
LEFT JOIN company2 com2 ON d.com2_id = com2.id

GROUP BY company_name, division, capex_type, cl.capex_id, po.po_no, po.po_date
ORDER BY company_name, division, capex_type, cl.capex_id
"""
df_base_data = con.execute(sql).fetchdf()
df_base_data['budget_balance'] = df_base_data['capex_amount'] - df_base_data['po_line_amount']

st.markdown("""
    <div class="custom-header">
        <h1>CAPEX Report</h1>
    </div>
""", unsafe_allow_html=True)

# --- ADD THE NEW COMPANY FILTER WIDGET HERE ---

# st.markdown("---") # Optional separator

company_list = ['All Companies'] + sorted(df_base_data['company_name'].unique().tolist())

# Get initial filter value from URL to persist state on refresh
try:
    persisted_company = st.query_params['company']
    default_company_index = company_list.index(persisted_company)
except (KeyError, ValueError):
    default_company_index = 0 # Default to 'All Companies'

selected_company = st.selectbox(
    "Filter by Company:",
    options=company_list,
    index=default_company_index
)

# Update URL parameter to save the filter state for the next refresh
if selected_company != 'All Companies':
    st.query_params['company'] = selected_company
elif 'company' in st.query_params:
    del st.query_params['company']

# Apply the filter to the main DataFrame
if selected_company != 'All Companies':
    df_base_data = df_base_data[df_base_data['company_name'] == selected_company]

# --- THE REST OF YOUR CODE WILL NOW USE THE FILTERED DATA ---

# --- Summary Section ---
st.subheader("📊 CAPEX Summary by Division")
# (Your summary metric cards and table code remains here...)
grand_total_capex = df_base_data['capex_amount'].sum()
grand_total_po = df_base_data['po_line_amount'].sum()
grand_total_balance = df_base_data['budget_balance'].sum()


col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="Total CAPEX Amount", value=f"{grand_total_capex:,.2f}")
with col2:
    st.metric(label="Total PO Amount", value=f"{grand_total_po:,.2f}")
with col3:
    st.metric(label="Budget Balance", value=f"{grand_total_balance:,.2f}", delta_color="off")
st.markdown("---")

df_summary = df_base_data.groupby('division').agg(
    total_capex_amount=('capex_amount', 'sum'),
    total_po_line_amount=('po_line_amount', 'sum'),
    total_budget_balance=('budget_balance', 'sum') 
).reset_index()

df_summary['Total CAPEX Amount'] = df_summary['total_capex_amount'].apply(lambda x: f"{x:,.2f}")
df_summary['Total PO Amount'] = df_summary['total_po_line_amount'].apply(lambda x: f"{x:,.2f}")
df_summary['Budget Balance'] = df_summary['total_budget_balance'].apply(lambda x: f"{x:,.2f}")

df_summary_display = df_summary[['division', 'Total CAPEX Amount', 'Total PO Amount', 'Budget Balance']]

st.dataframe(
    df_summary_display,
    use_container_width=True,
    selection_mode='single-row', 
    hide_index=True, 
    key='summary_table'
)


# --- Detail Section (using AgGrid for in-column filtering) ---
st.subheader("📋 Detail CAPEX and PO List")

# (Your existing Division filter logic remains unchanged)
division_to_filter = None
current_filter_message = ""

selection = st.session_state.get('summary_table', {}).get('selection', {})
if selection and selection.get('rows'):
    selected_row_index = selection['rows'][0]
    division_to_filter = df_summary_display.iloc[selected_row_index]['division']
    current_filter_message = f"Showing details for: **{division_to_filter}** (filtered by summary table click)."
    st.session_state.summary_table.selection.rows = []

all_divisions = ['All Divisions'] + sorted(df_base_data['division'].unique().tolist())
default_index = 0
if not division_to_filter:
    try:
        persisted_division = st.query_params["division"]
        default_index = all_divisions.index(persisted_division)
    except (KeyError, ValueError):
        default_index = 0

selected_division_from_dropdown = st.selectbox(
    "Filter by Division (Dropdown):",
    options=all_divisions,
    index=default_index
)

if not division_to_filter:
    division_to_filter = selected_division_from_dropdown
    if division_to_filter != "All Divisions":
        current_filter_message = f"Showing details for: **{division_to_filter}** (filtered by dropdown)."
    else:
        current_filter_message = "Showing details for all divisions."

if division_to_filter != "All Divisions":
    st.query_params["division"] = division_to_filter
elif "division" in st.query_params:
    del st.query_params["division"]

st.info(current_filter_message)

if division_to_filter != "All Divisions":
    df_detail_to_display = df_base_data[df_base_data['division'] == division_to_filter]
else:
    df_detail_to_display = df_base_data

# (The metric cards and Google Sheet button remain unchanged)
st.markdown("---") 
col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1.5])
with col1:
    st.metric(label="CAPEX Items", value=f"{df_detail_to_display['capex_id'].nunique():,}")
with col2:
    st.metric(label="CAPEX Amount", value=f"{df_detail_to_display['capex_amount'].sum():,.2f}")
with col3:
    st.metric(label="PO Amount", value=f"{df_detail_to_display['po_line_amount'].sum():,.2f}")
with col4:
    st.metric(label="Balance", value=f"{df_detail_to_display['budget_balance'].sum():,.2f}")

with col5:
    st.write("") 
    st.write("") 
    if st.button("Update Google Sheet 🚀", use_container_width=True):
        SHEET_URL = "https://docs.google.com/spreadsheets/d/1ZtA-gtrJnJc08yaOidn4EKds17yhEMjjATmRkPpMAE4/edit?usp=sharing"
        WORKSHEET_NAME = "Sheet1"
        
        df_to_export = df_detail_to_display[[
            "division", "capex_type", "capex_id", "po_no", "po_date",
            "capex_amount", "po_line_amount", "budget_balance"
        ]]
        
        with st.spinner("Updating Google Sheet... Please wait."):
            if update_google_sheet(df_to_export, SHEET_URL, WORKSHEET_NAME):
                st.success("Google Sheet updated successfully!")

st.markdown("---")

# --- Display Final Detail Table using AgGrid ---
df_detail_display_final = df_detail_to_display[[
    "division", "capex_type", "capex_id", "po_no", "po_date",
    "capex_amount", "po_line_amount", "budget_balance"
]]

# Configure the interactive grid
gb = GridOptionsBuilder.from_dataframe(df_detail_display_final)

# Enable the filter (รูปกรวย) for specific columns
gb.configure_column("capex_type", filter=True)
gb.configure_column("capex_id", filter=True)
gb.configure_column("po_no", filter=True)
gb.configure_column("division", filter=True) # Also enable for division

# Configure number columns for correct formatting and filtering
gb.configure_column("capex_amount", type=["numericColumn", "numberColumnFilter", "customNumericFormat"], precision=2)
gb.configure_column("po_line_amount", type=["numericColumn", "numberColumnFilter", "customNumericFormat"], precision=2)
gb.configure_column("budget_balance", type=["numericColumn", "numberColumnFilter", "customNumericFormat"], precision=2)

# General table settings
gb.configure_pagination(paginationAutoPageSize=True)
gb.configure_side_bar()

grid_options = gb.build()

# Display the AgGrid table
AgGrid(
    df_detail_display_final,
    gridOptions=grid_options,
    height=600,
    width='100%',
    fit_columns_on_grid_load=True,
    theme='streamlit' # or 'balham', 'alpine', etc.
)