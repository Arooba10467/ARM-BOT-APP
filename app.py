# ============================================================
# PART 1: Imports, data loading, charts, helper functions
# ============================================================
import gradio as gr
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

# Hugging Face's free tier now runs Gradio Spaces on ZeroGPU, which requires
# at least one function decorated with @spaces.GPU to exist at startup — even
# if your app never actually needs a GPU. The `spaces` package only exists on
# HF infrastructure, so we fall back to a no-op decorator everywhere else
# (Colab, local, etc.) so this doesn't break outside of HF.
try:
    import spaces
except ImportError:
    class _NoOpSpaces:
        @staticmethod
        def GPU(fn=None, **kwargs):
            if fn is None:
                return lambda f: f
            return fn
    spaces = _NoOpSpaces()

# Groq is optional — the app still runs without it, the AI tab just
# shows a setup message instead of crashing.
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
groq_client = Groq(api_key=GROQ_API_KEY) if (GROQ_AVAILABLE and GROQ_API_KEY) else None

# ----------------------------
# Load CSV Files
# ----------------------------
# Use a relative path so this works both in Colab (if you cd into /content)
# and on Hugging Face Spaces (where the CSVs should sit next to this app.py).
# In Colab, either upload the CSVs to /content and this will find them,
# or just make sure they're in the same folder you're running from.
DATA_DIR = "/content" if os.path.exists("/content/forecast.csv") else "."

forecast = pd.read_csv(os.path.join(DATA_DIR, "forecast.csv"))
consumption = pd.read_csv(os.path.join(DATA_DIR, "consumption.csv"))
mortality = pd.read_csv(os.path.join(DATA_DIR, "mortality.csv"))
pathogens = pd.read_csv(os.path.join(DATA_DIR, "pathogens.csv"))

forecast = forecast.fillna("")
consumption = consumption.fillna("")
mortality = mortality.fillna("")
pathogens = pathogens.fillna("")

# ----------------------------
# Dashboard Statistics
# ----------------------------

total_pathogens = forecast["pathogen"].nunique()

avg_resistance = round(
    pd.to_numeric(forecast["resistance_pct"], errors="coerce").mean(),
    1
)

highest_resistance = round(
    pd.to_numeric(forecast["resistance_pct"], errors="coerce").max(),
    1
)

countries_reporting = int(
    pd.to_numeric(forecast["countries_reporting"], errors="coerce").max()
)


def dashboard_html():
    return f"""
    <div style="display:flex; justify-content:center; gap:20px; flex-wrap:wrap;">

    <div style="background:#172554; padding:20px; border-radius:15px; width:220px; text-align:center;">
    <h3>🦠 Pathogens</h3>
    <h1>{total_pathogens}</h1>
    </div>

    <div style="background:#172554; padding:20px; border-radius:15px; width:220px; text-align:center;">
    <h3>📈 Avg Resistance</h3>
    <h1>{avg_resistance}%</h1>
    </div>

    <div style="background:#172554; padding:20px; border-radius:15px; width:220px; text-align:center;">
    <h3>🚨 Highest Resistance</h3>
    <h1>{highest_resistance}%</h1>
    </div>

    <div style="background:#172554; padding:20px; border-radius:15px; width:220px; text-align:center;">
    <h3>🌍 Countries</h3>
    <h1>{countries_reporting}</h1>
    </div>

    </div>
    """


def resistance_chart():
    df = forecast.copy()
    df["resistance_pct"] = pd.to_numeric(df["resistance_pct"], errors="coerce")

    fig = px.bar(
        df.sort_values("resistance_pct", ascending=False),
        x="pathogen",
        y="resistance_pct",
        color="resistance_pct",
        title="Global Resistance (%)"
    )
    fig.update_layout(template="plotly_dark", height=550)
    return fig


def _auto_chart(df, title):
    """
    Generic fallback chart for datasets whose exact schema we don't know
    (mortality.csv / consumption.csv). Picks the first text column as the
    x-axis and the first numeric column as the y-axis.

    NOTE: This is a placeholder so the app doesn't crash. Once you confirm
    the real column names in mortality.csv / consumption.csv, replace this
    with a chart tailored to those columns (e.g. x="country", y="deaths").
    """
    if df.empty:
        return go.Figure()

    numeric_cols = [c for c in df.columns if pd.to_numeric(df[c], errors="coerce").notna().any()]
    text_cols = [c for c in df.columns if c not in numeric_cols]

    if not numeric_cols or not text_cols:
        return go.Figure()

    x_col = text_cols[0]
    y_col = numeric_cols[0]

    plot_df = df.copy()
    plot_df[y_col] = pd.to_numeric(plot_df[y_col], errors="coerce")

    fig = px.bar(
        plot_df.sort_values(y_col, ascending=False),
        x=x_col,
        y=y_col,
        title=title
    )
    fig.update_layout(template="plotly_dark", height=550)
    return fig


def mortality_chart():
    return _auto_chart(mortality, "Mortality Overview")


def consumption_chart():
    return _auto_chart(consumption, "Antibiotic Consumption Overview")


def forecast_graph(pathogen):
    row = forecast[forecast["pathogen"] == pathogen]

    if row.empty:
        return go.Figure()

    row = row.iloc[0]

    years = [2023, 2024, 2025, 2026]
    values = [
        row["resistance_pct"],
        row["pred_2024"],
        row["pred_2025"],
        row["pred_2026"]
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=years, y=values, mode="lines+markers", line=dict(width=4))
    )
    fig.update_layout(template="plotly_dark", title=f"{pathogen} Forecast")
    return fig


def pathogen_info(name):
    row = pathogens[pathogens["pathogen"] == name]

    if row.empty:
        return "No Data"

    row = row.iloc[0]

    return f"""
# {row['pathogen']}

### Gram Stain
{row['gram_stain']}

### WHO Priority
{row['who_priority_2024']}

### Infection Types
{row['infection_types_monitored']}

### Resistance Mechanisms
{row['key_resistance_mechanisms']}

### Antibiotics Tested
{row['key_antibiotics_tested']}

### Key Concern
{row['key_concern']}
"""


# ============================================================
# PART 4: AI assistant logic + custom styling (defined here so
# they're ready before we build the Blocks UI below)
# ============================================================

# Satisfies Hugging Face's ZeroGPU startup check. Never actually needed for
# this app's logic — charts run on CPU and the AI assistant calls Groq's API
# remotely — but the decorator has to be present somewhere.
@spaces.GPU(duration=1)
def _zerogpu_warmup():
    return True


AMR_SYSTEM_PROMPT = """You are the AMR Vision AI assistant, embedded in a dashboard
about antimicrobial resistance (AMR). Answer questions about antibiotic resistance,
the pathogens, mortality, and consumption data shown in the app, and general AMR
education (WHO priority pathogens, resistance mechanisms, stewardship). Keep answers
clear, factual, and concise. If asked something unrelated to AMR/health, gently steer
back to the app's topic."""


def ai_chat(message, history):
    if not GROQ_AVAILABLE:
        return "The `groq` package isn't installed. Add `groq` to requirements.txt."
    if groq_client is None:
        return "AI assistant isn't configured yet — set a GROQ_API_KEY secret (in your HF Space settings, or as an env var locally) to enable it."

    messages = [{"role": "system", "content": AMR_SYSTEM_PROMPT}]
    for user_msg, bot_msg in history:
        messages.append({"role": "user", "content": user_msg})
        if bot_msg:
            messages.append({"role": "assistant", "content": bot_msg})
    messages.append({"role": "user", "content": message})

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.4,
            max_tokens=600,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI request failed: {e}"


CUSTOM_CSS = """
.gradio-container {
    background: linear-gradient(180deg, #0b1220 0%, #10192e 100%);
}
h1, h2, h3 {
    color: #e2e8f0 !important;
}
.tabitem {
    padding-top: 12px;
}
footer {display: none !important;}
"""

LEARN_AMR_MARKDOWN = """
## What is Antimicrobial Resistance (AMR)?

Antimicrobial resistance happens when bacteria, viruses, fungi, and parasites evolve
to no longer respond to the drugs designed to kill them. Infections that used to be
easily treatable become harder — or impossible — to cure, driving up mortality,
hospital stays, and healthcare costs worldwide.

### Why it matters
- The WHO has named AMR one of the top global public health threats.
- Overuse and misuse of antibiotics in humans, animals, and agriculture accelerates
  resistance.
- Drug-resistant infections already contribute to hundreds of thousands of deaths
  each year, with projections rising sharply without intervention.

### How this dashboard helps
- **Dashboard** — a snapshot of global resistance, mortality, and consumption trends.
- **Forecast** — projected resistance trajectories per pathogen through 2026.
- **Pathogen Explorer** — WHO priority status, resistance mechanisms, and key
  concerns for individual pathogens.
- **AI Assistant** — ask plain-language questions about any of the data or AMR
  concepts.

### Learn more
- World Health Organization — Antimicrobial Resistance fact sheets
- CDC — Antibiotic Resistance Threats reports
- GLASS (Global Antimicrobial Resistance and Use Surveillance System)
"""


# ============================================================
# PART 2 & 3: Build the UI — Dashboard, Forecast,
# Pathogen Explorer, Statistics, Learn AMR, AI Assistant
# ============================================================
with gr.Blocks(title="AMR Vision AI") as demo:

    gr.Markdown("""
# 🦠 AMR Vision AI

### Transforming Global Antimicrobial Resistance Data into Actionable Insights
""")

    with gr.Tab("🏠 Dashboard"):
        dashboard = gr.HTML(value=dashboard_html())
        resistance_plot = gr.Plot(value=resistance_chart)
        mortality_plot = gr.Plot(value=mortality_chart)
        consumption_plot = gr.Plot(value=consumption_chart)

    with gr.Tab("📈 Forecast"):
        pathogen = gr.Dropdown(
            choices=sorted(forecast["pathogen"].unique()),
            label="Choose Pathogen"
        )
        forecast_plot = gr.Plot()
        pathogen.change(
            forecast_graph,
            inputs=pathogen,
            outputs=forecast_plot
        )

    with gr.Tab("🦠 Pathogen Explorer"):
        pathogen2 = gr.Dropdown(
            choices=sorted(pathogens["pathogen"].unique()),
            label="Choose Pathogen"
        )
        info = gr.Markdown()
        pathogen2.change(
            pathogen_info,
            pathogen2,
            info
        )

    with gr.Tab("📊 Statistics"):
        gr.Dataframe(forecast)
        gr.Dataframe(consumption)
        gr.Dataframe(mortality)

    with gr.Tab("📚 Learn AMR"):
        gr.Markdown(LEARN_AMR_MARKDOWN)

    with gr.Tab("🤖 AI Assistant"):
        gr.Markdown("Ask about resistance trends, pathogens, or general AMR questions.")
        gr.ChatInterface(
            fn=ai_chat,
            examples=[
                "Which pathogen has the highest resistance right now?",
                "What is AMR and why does it matter?",
                "Explain WHO priority pathogen categories."
            ],
        )


if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft(), css=CUSTOM_CSS)