"""Small presentation helpers; all expense and model logic stays in its own modules."""
from html import escape
import streamlit as st

PALETTE = ['#087F73', '#6F73D2', '#E8AA54', '#599CCA', '#DD7890', '#83BFA5', '#AB8CCD', '#9BAABD']
CATEGORY_COLORS = dict(zip(['Food', 'Transport', 'Shopping', 'Bills', 'Entertainment', 'Health', 'Education', 'Other'], PALETTE))


def apply_style():
    st.markdown('''<style>
    .stApp { background: #F5F7FA; }
    .block-container { max-width: 1480px; padding-top: 2.1rem; padding-bottom: 3rem; }
    [data-testid="stHeader"] { background: rgba(245,247,250,.95); }
    [data-testid="stSidebar"] { background: #EDF2F5; border-right: 1px solid #DEE5EC; }
    [data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }
    h1,h2,h3 { letter-spacing: -.035em; }
    h3 { font-size: 1.25rem !important; font-weight: 700 !important; }
    [data-testid="stCaptionContainer"] { color: #62748A; }
    .brand { display: flex; align-items: center; gap: 11px; margin: 8px 0 26px; }
    .brand-mark { display: grid; place-items: center; background: #087F73; color: white;
        width: 42px; height: 42px; border-radius: 13px; font-size: 24px; font-weight: 800; }
    .brand-name { color: #172B42; font-size: 19px; font-weight: 800; letter-spacing: -.6px; }
    .brand-sub { color: #698094; font-size: 11px; letter-spacing: 1.3px; text-transform: uppercase; }
    .sidebar-note { background: #DFEAE8; border: 1px solid #CDDFDA; padding: 16px;
        border-radius: 14px; font-size: 12px; color: #42615D; margin-top: 26px; line-height: 1.8; }
    .hero { background: linear-gradient(110deg,#132A3F 0%,#193F4B 75%,#16554F 100%);
        border-radius: 22px; padding: 30px 34px; display: flex; justify-content: space-between;
        align-items: center; gap: 20px; color: #fff; margin-bottom: 22px; }
    .hero-eyebrow { color: #94D9C8; font-size: 11px; letter-spacing: 2px; font-weight: 700; }
    .hero h1 { color: white; font-size: clamp(25px,3vw,38px); line-height: 1.2; margin: 10px 0;
        padding: 0; font-weight: 750; }
    .hero p { color: #C1D5DE; font-size: 14px; margin: 0; line-height: 1.6; }
    .hero-status { flex-shrink: 0; text-align: right; }
    .status-pill { display: inline-block; border: 1px solid #57777B; border-radius: 30px;
        color: #C8EEE2; padding: 7px 12px; font-size: 12px; background: #FFFFFF0A; }
    .hero-date { color: #B1C9D0; font-size: 12px; margin-top: 12px; }
    [data-testid="stTabs"] [role="tablist"] { gap: 7px; border-bottom: 1px solid #DFE6ED; padding-bottom: 10px; }
    [data-testid="stTabs"] [role="tab"] { border-radius: 9px; padding: 9px 15px; height: 42px; color: #607289; }
    [data-testid="stTabs"] [role="tab"][aria-selected="true"] { background: #DDF0E9; color: #087364; }
    [data-testid="stTabs"] [role="tab"] p { font-size: 13px; font-weight: 600; }
    [data-testid="stTabs"] [role="tabpanel"] { padding-top: 22px; }
    [data-testid="stMetric"] { background: white; border: 1px solid #E1E8EF; border-radius: 16px;
        padding: 20px 20px 17px; box-shadow: 0 3px 14px #18314B04; min-height: 124px;
        border-top: 3px solid #9CD3C2; }
    [data-testid="stMetricLabel"] { color: #62748A; font-size: 12px; }
    [data-testid="stMetricValue"] { color: #172B42; font-size: clamp(21px,2.1vw,31px); font-weight: 750; }
    [data-testid="stVerticalBlockBorderWrapper"] > div { border-radius: 16px !important; }
    [data-testid="stForm"] { background: white; border: 1px solid #E0E7ED; border-radius: 16px; padding: 24px; }
    [data-testid="stExpander"] { background: white; border-radius: 12px; }
    [data-testid="stButton"] button, [data-testid="stDownloadButton"] button,
    [data-testid="stFormSubmitButton"] button { border-radius: 10px; font-weight: 600; min-height: 42px; }
    [data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button:hover { border-color: #087F73; color: #087F73; }
    [data-testid="stMultiSelect"] [data-baseweb="tag"] { background: #DDF0E9; color: #125E52; }
    [data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
    .empty { background: white; border: 1px dashed #C9D7DF; border-radius: 18px; padding: 42px 24px;
        text-align: center; margin: 14px 0; }
    .empty-icon { display: inline-block; border-radius: 16px; background: #E0F1EA; color: #087F73;
        padding: 12px 19px; font-size: 28px; margin-bottom: 12px; }
    .empty h3 { color: #233B50; margin: 0 0 8px; }
    .empty p { color: #718297; font-size: 14px; max-width: 420px; margin: auto; line-height: 1.7; }
    .footer { color: #8795A5; font-size: 11px; border-top: 1px solid #E1E8EE;
        padding-top: 20px; margin-top: 28px; text-align: center; letter-spacing: .4px; }
    @media (max-width: 760px) {
        .block-container { padding: 1.3rem 1rem 2rem; }
        .hero { padding: 24px; align-items: flex-start; flex-direction: column; border-radius: 16px; }
        .hero-status { text-align: left; }
        .hero-date { display: inline; margin-left: 10px; }
        [data-testid="stTabs"] [role="tab"] { padding: 8px 10px; }
        [data-testid="stMetric"] { min-height: 105px; padding: 15px; }
    }
    </style>''', unsafe_allow_html=True)


def hero(mode, today):
    label = 'Synthetic demo' if mode == 'Synthetic demo' else 'Personal workspace'
    st.markdown(f'''<div class="hero">
        <div><div class="hero-eyebrow">SMART EXPENSE TRACKER · AI INSIGHTS</div>
        <h1>A clearer picture of your spending.</h1>
        <p>Your expenses, patterns and next steps. All in one place.</p></div>
        <div class="hero-status"><span class="status-pill">● &nbsp; {escape(label)}</span>
        <div class="hero-date">{today.strftime('%d %B %Y')}</div></div>
    </div>''', unsafe_allow_html=True)


def sidebar_brand():
    st.sidebar.markdown('''<div class="brand"><div class="brand-mark">₹</div>
        <div><div class="brand-name">Smart Expense</div><div class="brand-sub">Spend with clarity</div></div></div>''', unsafe_allow_html=True)


def chart_style(figure, height=320):
    figure.update_layout(template='plotly_white', height=height, paper_bgcolor='rgba(0,0,0,0)',
                         plot_bgcolor='rgba(0,0,0,0)', font=dict(family='Arial, sans-serif', color='#61758A', size=12),
                         margin=dict(l=10,r=10,t=15,b=10), hoverlabel=dict(bgcolor='#172B42',font_color='white'),
                         colorway=PALETTE, legend_title_text='')
    if not any(trace.type == 'pie' for trace in figure.data):
        figure.update_xaxes(title=None, showgrid=False, zeroline=False)
        figure.update_yaxes(title=None, gridcolor='#E9EFF4', zeroline=False, tickprefix='₹', tickformat=',.0f')
    return figure


def empty_state():
    st.markdown('''<div class="empty"><div class="empty-icon">₹</div>
        <h3>Your spending story starts here</h3>
        <p>Add your first expense or import a CSV to bring this dashboard to life.
        Try Synthetic demo in the sidebar for a preview, or adjust your filters.</p></div>''', unsafe_allow_html=True)
