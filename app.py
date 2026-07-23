"""Streamlit Cloud entry point for the CRAG incident-aware support demo.

Deploy: push this repo to GitHub, create a Streamlit Cloud app pointing at
app.py, and set GROQ_API_KEY / TAVILY_API_KEY under the app's Secrets
(TOML format, see .env.example for the required keys).
"""

import os

import streamlit as st

# Streamlit Cloud secrets -> env vars, so the existing graph.py/web_search.py
# code (which reads os.environ) works unchanged. Local runs still pick up a
# .env file via python-dotenv.
try:
    for key in ("GROQ_API_KEY", "TAVILY_API_KEY"):
        if key in st.secrets:
            os.environ[key] = st.secrets[key]
except FileNotFoundError:
    pass  # no secrets.toml locally — fall back to .env below

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from graph import build_crag_graph  # noqa: E402  (must load env vars first)

st.set_page_config(page_title="CRAG Incident-Aware Support", page_icon="🛠️")
st.title("🛠️ CRAG Incident-Aware Support")
st.caption(
    "Corrective RAG demo: docs are graded for relevance, an active-incident "
    "feed is checked in parallel, and low-quality retrieval falls back to "
    "live web search before escalating to a human."
)

missing = [k for k in ("GROQ_API_KEY", "TAVILY_API_KEY") if not os.environ.get(k)]
if missing:
    st.error(
        "Missing required secret(s): "
        + ", ".join(missing)
        + ". Add them in Streamlit Cloud under App settings -> Secrets."
    )
    st.stop()


@st.cache_resource(show_spinner="Loading,kindly wait...")
def get_graph():
    return build_crag_graph()


graph = get_graph()

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("meta"):
            st.caption(message["meta"])

question = st.chat_input("Please descripe your issue..")

if question:
    # Snapshot prior turns before appending the new question, so the graph's
    # rewrite_question node only sees history that predates this turn.
    chat_history = [
        {"role": m["role"], "content": m["content"]} for m in st.session_state.messages
    ]

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = graph.invoke({"question": question, "chat_history": chat_history})
        answer = result["answer"]
        meta = (
            f"route: {result.get('source')} | doc grade: {result.get('overall_verdict')} "
            f"| web grade: {result.get('web_verdict')} | incident: {bool(result.get('incident'))}"
        )
        if result.get("standalone_question") and result["standalone_question"] != question:
            meta = f"resolved to: \"{result['standalone_question']}\" | " + meta
        st.markdown(answer)
        st.caption(meta)

    st.session_state.messages.append({"role": "assistant", "content": answer, "meta": meta})

with st.sidebar:
    st.subheader("Try these")
    st.markdown(
        "- How do I reset my password?\n"
        "- How does SSO login work?\n"
        "- My exported CSV file shows garbled/broken special characters "
        "when I open it in Excel — why does that happen?"
    )
    if st.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()
