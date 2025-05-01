import streamlit as st
import google.generativeai as genai
from PIL import Image
import io

# Set your Google AI API key
API_KEY = st.secrets["GOOGLE_API_KEY"]
genai.configure(api_key=API_KEY)

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
        # Read image using PIL
        img = Image.open(uploaded_file)
        
        # Create the model instance
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Generate content with proper formatting
        response = model.generate_content(
            [
                "Analyze this medical prescription and follow these instructions:\n" + PROMPT,
                img
            ]
        )
        
        if response.text:
            st.subheader("Analysis Results:")
            st.markdown(response.text)
        else:
            st.warning("No valid response received from the model.")
            
    except Exception as e:
        st.error(f"Error processing prescription: {str(e)}")
