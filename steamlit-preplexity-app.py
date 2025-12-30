import os
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="Perplexity Chat", page_icon="🔎", layout="centered")

# --- Sidebar controls ---
with st.sidebar:
    st.title("Perplexity Chat")
    api_key = st.text_input("PPLX API Key", type="password", value=os.getenv("PPLX_API_KEY", ""))
    model = st.selectbox(
        "Model",
        [
            "sonar",
            "sonar-pro",
            "sonar-reasoning",
            "sonar-reasoning-pro",
            "sonar-deep-research"
        ],
        index=1,
    )

    temperature = st.slider("Temperature", 0.0, 1.5, 0.2, 0.1)
    max_tokens = st.slider("Max tokens", 64, 2048, 512, 64)

    st.caption("Tip: set env var PPLX_API_KEY to avoid pasting here.")
    if st.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()

# --- Validate key ---
if not api_key:
    st.info("Enter your PPLX API key in the sidebar (or set PPLX_API_KEY env var) to start chatting.")
    st.stop()

# Perplexity OpenAI-compat client (Option A)
client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")  # [web:12]

# --- Session state init ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": "Be precise and concise. Use bullet points when helpful."}
    ]

st.header("Chat")

# --- Render history (skip system message in UI) ---
for m in st.session_state.messages:
    if m["role"] == "system":
        continue
    with st.chat_message(m["role"]):  # user/assistant chat bubbles [web:28]
        st.markdown(m["content"])

# --- Input box ---
prompt = st.chat_input("Ask something...")  # [web:28]
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            resp = client.chat.completions.create(
                model=model,
                messages=st.session_state.messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )  # Chat Completions pattern [web:12]
            answer = resp.choices[0].message.content
            st.markdown(answer)

            # Optional: show Perplexity search sources if present
            try:
                if getattr(resp, "search_results", None):
                    with st.expander("Sources"):
                        for r in resp.search_results:
                            st.write(f"- {r.get('title','(no title)')}: {r.get('url','')}")
            except Exception:
                pass

    st.session_state.messages.append({"role": "assistant", "content": answer})
