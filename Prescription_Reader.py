import streamlit as st
from google import genai
import re

# Set your Google AI API key
API_KEY = st.secrets["api_key"]  # Store your API key securely in Streamlit secrets
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
        # Upload the file to Google AI
        my_file = client.files.upload(file=uploaded_file)  
        
        # Generate content using the prompt
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[my_file, PROMPT],
        )
        content = response.text

        # Parse the response
        #medicines = parse_medicine_data(content)

        if content:
            st.subheader("Medications Found:")
	    st.write(content)
            #for idx, med in enumerate(medicines, 1):
                #st.write(f"**MEDICATION {idx}: {med['generic']} ({med['brand']})**")
                #st.write(f"- Strength: {med['strength']}")
                #st.write(f"- Dosage: {med['dosage']}")
                #st.write("- Common Side Effects:")
                #for eff in med['side_effects']:
                    #st.write(f"   - {eff}")
                #st.write(f"- Therapeutic Benefits: {med['benefits']}\n")
        else:
            st.warning("No medications found in the prescription.")

    except Exception as e:
        st.error(f"Error processing prescription: {str(e)}")
