"""Chat with a Qwen agent answering with Perspective charts, tables and dashboards."""

import asyncio
import os
from urllib.parse import urlencode

import streamlit as st
from dotenv import load_dotenv

from agent import Settings, respond

EXAMPLES = [
    "Draw a chart of the Nasdaq year to date",
    "Compare Apple, Microsoft and Nvidia over the last year",
    "Show Tesla as candlesticks over the last 3 months",
    "Build a dashboard for the S&P 500, gold and bitcoin",
]
HEIGHTS = {"chart": 460, "table": 460, "workspace": 720}

load_dotenv()
st.set_page_config(page_title="Perspective MCP", page_icon="📈", layout="wide")
st.session_state.setdefault("history", [])
theme = "Pro Dark" if st.context.theme.type == "dark" else "Pro Light"


def show(entry: dict) -> None:
    with st.chat_message(entry["role"]):
        for call in entry.get("tool_calls", []):
            st.caption(f"🛠️ `{call}`")
        for visualization in entry.get("visualizations", []):
            url = f"{visualization['url']}?{urlencode({'theme': theme})}"
            st.iframe(url, height=HEIGHTS[visualization["kind"]])
        st.markdown(entry["content"])


with st.sidebar:
    st.header("Settings")
    settings = Settings(
        model=st.text_input("Qwen model", os.getenv("QWEN_MODEL", "qwen3.8-max")),
        base_url=st.text_input(
            "Qwen API base URL", os.getenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        ),
        api_key=st.text_input("Qwen API key", os.getenv("QWEN_API_KEY", ""), type="password"),
        mcp_url=st.text_input("Perspective MCP server", os.getenv("MCP_URL", "http://localhost:8000/mcp")),
        thinking=st.segmented_control(
            "Thinking", ["auto", "off", "on"], default=os.getenv("QWEN_THINKING", "auto"), required=True
        ),
    )
    if st.button("New conversation", width="stretch"):
        st.session_state.history = []

st.title("📈 Perspective MCP")
for entry in st.session_state.history:
    show(entry)

prompt = st.chat_input("Ask for a chart, a table or a dashboard")
if not st.session_state.history:
    for column, example in zip(st.columns(len(EXAMPLES)), EXAMPLES):
        if column.button(example, width="stretch"):
            prompt = example

if prompt:
    question = {"role": "user", "content": prompt}
    show(question)
    history = [{"role": entry["role"], "content": entry["content"]} for entry in st.session_state.history]
    with st.chat_message("assistant"), st.status("Working…") as status:
        try:
            turn = asyncio.run(respond([*history, question], settings, on_tool_call=status.write))
        except Exception as error:  # noqa: BLE001
            status.update(label="Failed", state="error")
            st.error(f"{type(error).__name__}: {error}")
            st.stop()
    answer = {
        "role": "assistant",
        "content": turn.text,
        "tool_calls": turn.tool_calls,
        "visualizations": turn.visualizations,
    }
    st.session_state.history += [question, answer]
    st.rerun()
