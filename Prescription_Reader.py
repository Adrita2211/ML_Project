import streamlit as st

import os
from PIL import Image
import google.generativeai as genai

# Load environment variables and configure API
#load_dotenv()
genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

# Create the model instance
model = genai.GenerativeModel('gemini-1.5-flash')

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
prompt = st.chat_input("Ask me anything...")

if prompt:
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate response
    try:
        response = model.generate_content(prompt)
        
        # Display assistant response
        with st.chat_message("assistant"):
            st.markdown(response.text)
        
        # Add assistant response to chat history
        st.session_state.messages.append({"role": "assistant", "content": response.text})
    
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
