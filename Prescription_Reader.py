import streamlit as st
from google import genai
from google.genai.types import Content, Part
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

st.title("Prescription Analyzer")

uploaded_file = st.file_uploader("Upload a prescription image (PNG)", type="png")

if uploaded_file is not None:
    try:
        # Read image data
        image_data = uploaded_file.read()
        
        # Create content parts
        image_part = Part.from_data(image_data, mime_type="image/png")
        text_part = Part.from_text(PROMPT)
        content = Content(parts=[image_part, text_part])
        
        # Generate content using the prompt
        response = client.models.generate_content(
            model="gemini-pro-vision",  # Correct vision-enabled model
            contents=[content],
        )
        content = response.text

        if content:
            st.subheader("Medications Found:")
            st.markdown(content)  # Render markdown properly
        else:
            st.warning("No medications found in the prescription.")

    except Exception as e:
        st.error(f"Error processing prescription: {str(e)}")
