import streamlit as st
import google.generativeai as genai
from PIL import Image

# Configure API key
API_KEY = st.secrets["GOOGLE_API_KEY"]
genai.configure(api_key=API_KEY)

PROMPT = """[Your exact prompt from original code here]"""

st.title("Prescription Analyzer")

uploaded_file = st.file_uploader("Upload a prescription image (PNG)", type="png")

if uploaded_file is not None:
    try:
        # Read and verify image
        img = Image.open(uploaded_file)
        
        # Create the model instance
        model = genai.GenerativeModel('gemini-pro-vision')
        
        # Generate content with proper formatting
        response = model.generate_content(
            [
                "Analyze this medical prescription and follow these instructions:\n" + PROMPT,
                img
            ]
        )
        
        if response.text:
            st.subheader("Medications Found:")
            st.markdown(response.text)
        else:
            st.warning("No medications found or the response format was invalid.")

    except Exception as e:
        st.error(f"Error processing prescription: {str(e)}")
