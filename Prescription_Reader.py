import streamlit as st
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

# Function to parse medicine data (same as before)
def parse_medicine_data(content):
    # ... (same code as in your original script) ...

# Streamlit app
st.title("Prescription Analyzer")

uploaded_file = st.file_uploader("Upload a prescription image (PNG)", type="png")

if uploaded_file is not None:
    try:
        # Read the uploaded file as bytes
        file_bytes = uploaded_file.read()
        
        # Create an in-memory file-like object
        file_stream = io.BytesIO(file_bytes)

        # Upload the file using from_data
        my_file = client.files.upload(
            file=file_stream,
            filename=uploaded_file.name,  # Optional: Provide original filename
            mime_type="image/png"         # Set the correct MIME type
        )
        
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[my_file, PROMPT],
        )
        content = response.text
        if content:
            st.write(content)  
        else:
            st.warning("No content found in the response.")
    except Exception as e:
        st.error(f"Error processing prescription: {str(e)}")
