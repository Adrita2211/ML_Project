import streamlit as st
import google.generativeai as genai
from PIL import Image

# Configuration
API_KEY = st.secrets["GOOGLE_API_KEY"]
genai.configure(api_key=API_KEY)

SYSTEM_PROMPT = """**Prescription Analysis Task:**
1. **Extract ALL medications** with EXACT dosage information
2. For each medication, provide:
   - Generic name (Brand name in parentheses if available)
   - Strength (exact value from document)
   - Precise dosage instructions (verbatim)
   - 3 most common side effects (prioritize frequency)
   - Primary therapeutic benefits (mechanism → outcome)
   - Drug class and pregnancy category (if available)

**Output Format:**
**Medicine: [Generic Name]** (Brand Name)
- **Strength**: [Value]
- **Dosage**: [Instructions]
- **Side Effects**: 1. 2. 3.
- **Benefits**: [Mechanism] → [Outcome]
- **Class**: [Therapeutic Class]
- **Pregnancy**: [Category]

**Example:**
**Medicine: Metformin** (Glucophage)
- **Strength**: 500mg
- **Dosage**: Take one tablet twice daily with meals
- **Side Effects**: 1. Nausea 2. Diarrhea 3. Abdominal discomfort
- **Benefits**: Decreases hepatic glucose production → Improves glycemic control
- **Class**: Biguanide
- **Pregnancy**: Category B"""

def analyze_prescription(image):
    """Analyze prescription using Gemini Flash"""
    model = genai.GenerativeModel('gemini-pro-vision')
    
    # Correct image handling without Part class
    response = model.generate_content(
        [
            SYSTEM_PROMPT,
            {
                "mime_type": "image/png", 
                "data": image
            }
        ]
    )
    return response.text

# Streamlit UI
st.title("Prescription Analyzer")
uploaded_file = st.file_uploader("Upload Prescription", type=["png", "jpg", "jpeg"])

if uploaded_file:
    try:
        with st.spinner("Analyzing..."):
            analysis = analyze_prescription(uploaded_file.read())
        
        if analysis:
            st.subheader("Results")
            st.markdown(analysis)
            
    except Exception as e:
        st.error(f"Error: {str(e)}")
