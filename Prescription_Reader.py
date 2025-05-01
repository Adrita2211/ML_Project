import streamlit as st
import io
from google import genai
import re

# Set your Google AI API key
API_KEY = st.secrets["GOOGLE_API_KEY"]  # Store your API key securely in Streamlit secrets
client = genai.Client(api_key=API_KEY)

# Define the prompt
PROMPT = """Analyze this medical prescription and:
1. Identify ALL medications with EXACT dosage from the document
2. For each medication, provide:
   - Generic and brand names
   - Precise dosage instructions
   - 3 most common side effects
   - Primary therapeutic benefits
3. Format EXACTLY like:

**Medicine: [Generic Name] ([Brand Name])**
- Strength: [Value from document]
- Dosage: [Verbatim instructions]
- Side Effects: 1. 2. 3.
- Benefits: [Mechanism] → [Clinical outcome]

Example:
**Medicine: Metformin (Glucophage)**
- Strength: 500mg
- Dosage: Take one tablet twice daily with meals
- Side Effects: 1. Nausea 2. Diarrhea 3. Abdominal discomfort
- Benefits: Decreases hepatic glucose production → Improves glycemic control"""

# Streamlit app
st.title("Prescription Analyzer")

uploaded_file = st.file_uploader("Upload a prescription image (PNG)", type="png")

if uploaded_file is not None:
    try:
       image_bytes = uploaded_file.getvalue()
        
        # Create image part using from_data
        image_part = Part.from_data(
            data=image_bytes,
            mime_type="image/png"
        )
        
        # Generate response from Gemini
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[image_part, PROMPT],
        )
        
        # Handle response
        if response.text:
            st.subheader("Analysis Results:")
            st.markdown(response.text)
        else:
            st.warning("No content found in the response. Please check the prescription format.")
            
    except Exception as e:
        st.error(f"Error processing prescription: {str(e)}")
        st.error("Please ensure:")
        st.error("- The image is a clear PNG of a prescription")
        st.error("- The prescription text is readable")
        st.error("- You have valid API credentials")
