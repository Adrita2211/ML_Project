import streamlit as st
import google.generativeai as genai
import re

# Replace with your actual API key
api_key=st.secrets["GOOGLE_API_KEY"] 
client = genai.Client(api_key=API_KEY)

# Enhanced prompt with strict formatting requirements
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

def parse_medicine_data(content):
    medicines = []
    pattern = r"""
        \*\*Medicine:\s*(.+?)\s*\((.+?)\)\*\*  # Generic and Brand names
        (?:- Strength:\s*(.+?)\n)?              # Optional strength
        - Dosage:\s*(.+?)\n                      # Dosage instructions
        - Side Effects:\s*((?:1\..+?\n)+)        # Numbered side effects
        - Benefits:\s*(.+?)(?=\n\*\*|$)          # Benefits until next medicine or end
    """
    
    matches = re.finditer(pattern, content, re.DOTALL | re.VERBOSE)
    
    for match in matches:
        medicine = {
            "generic": match.group(1).strip(),
            "brand": match.group(2).strip(),
            "strength": match.group(3).strip() if match.group(3) else "N/A",
            "dosage": match.group(4).strip(),
            "side_effects": [eff.strip() for eff in re.findall(r"\d+\.\s*(.+?)(?=\n\d+\.|$)", match.group(5))],
            "benefits": match.group(6).strip()
        }
        medicines.append(medicine)
    
    return medicines

# Streamlit app
st.title("Prescription Analyzer")

uploaded_file = st.file_uploader("Upload a prescription image (jpg/png)", type=["jpg", "png"])

if uploaded_file is not None:
    with st.spinner("Analyzing prescription..."):
        try:
            # Upload the image to Google AI
            my_file = client.files.upload(file=uploaded_file.getvalue(), filename=uploaded_file.name)  

            # Generate content using the prompt
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[my_file, PROMPT],
            )
            content = response.text

            # Extract medicine data
            medicines = parse_medicine_data(content)

            if not medicines:
                st.error("No medicines found in response. Please check the image quality or try a different prescription.")
            else:
                st.success(f"Found {len(medicines)} medications:")
                for idx, med in enumerate(medicines, 1):
                    st.write(f"**MEDICATION {idx}: {med['generic']} ({med['brand']})**")
                    st.write(f"- Strength: {med['strength']}")
                    st.write(f"- Dosage: {med['dosage']}")
                    st.write("- Common Side Effects:")
                    for eff in med['side_effects']:
                        st.write(f"    - {eff}")
                    st.write(f"- Therapeutic Benefits: {med['benefits']}")
                    st.write("---")  # Separator

        except Exception as e:
            st.error(f"Error processing prescription: {str(e)}")
