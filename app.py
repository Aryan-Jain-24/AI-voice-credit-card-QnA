"""Streamlit UI — built out in S08.

This S00 skeleton only proves the wiring: the app boots, and the API key
loads from the environment. See all-specs.md S08 and
.claude/agents/voice-ui-engineer.md for the real UI.
"""
import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.title("Voice Q&A over Credit Card Data")
st.write("hello")

if os.getenv("OPENAI_API_KEY"):
    st.success("OPENAI_API_KEY loaded from environment.")
else:
    st.warning("OPENAI_API_KEY not set. Copy .env.example to .env and add your key.")
