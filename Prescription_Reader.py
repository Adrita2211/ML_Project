import streamlit as st
import google.generativeai as genai
import re
import io

# Configure GenAI client
def get_genai_client():
    api_key = st.secrets["GOOGLE_API_KEY"]
    return genai.Client(api_key=api_key)

# Reuse your medicine parsing function
def parse_medicine_data(content):
    medicines = []
    pattern = r"""
        \*\*Medicine:\s*(.+?)\s*\((.+?)\)\*\*
        (?:- Strength:\s*(.+?)\n)?
        - Dosage:\s*(.+?)\n
        - Side Effects:\s*((?:1\..+?\n)+)
        - Benefits:\s*(.+?)(?=\n\*\*|$)
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

# Streamlit UI
def main():
    st.title("📋 Prescription Analyzer")
    st.markdown("Upload a prescription image to analyze medications and their details")
    
    # File uploader
    uploaded_file = st.file_uploader("Choose a prescription image", 
                                   type=["png", "jpg", "jpeg"])
    
    if uploaded_file is not None:
        client = get_genai_client()
        
        # Display uploaded image
        st.image(uploaded_file, caption="Uploaded Prescription", width=300)
        
        if st.button("Analyze Prescription"):
            with st.spinner("Analyzing medication details..."):
                try:
                    # Read file bytes
                    file_bytes = uploaded_file.getvalue()
                    
                    # Generate content using your existing prompt
                    response = client.models.generate_content(
                        model="gemini-2.0-flash",
                        contents=[{
                            "inline_data": {
                                "mime_type": "image/png" if uploaded_file.name.endswith(".png") else "image/jpeg",
                                "data": file_bytes
                            }
                        }, PROMPT],
                    )
                    content = response.text
                    
                    # Parse using your existing function
                    medicines = parse_medicine_data(content)
                    
                    if not medicines:
                        st.warning("⚠️ No medications found in the prescription")
                        return
                    
                    st.success(f"✅ Found {len(medicines)} medications")
                    
                    # Display results in expandable sections
                    for idx, med in enumerate(medicines, 1):
                        with st.expander(f"{med['generic']} ({med['brand']})", expanded=True):
                            col1, col2 = st.columns(2)
                            with col1:
                                st.subheader("📝 Prescription Details")
                                st.markdown(f"""
                                - **Generic Name**: {med['generic']}
                                - **Brand Name**: {med['brand']}
                                - **Strength**: {med['strength']}
                                - **Dosage**: {med['dosage']}
                                """)
                                
                            with col2:
                                st.subheader("⚕️ Clinical Information")
                                st.markdown("**🚩 Common Side Effects:**")
                                for eff in med['side_effects']:
                                    st.markdown(f"- {eff}")
                                st.markdown(f"**💊 Therapeutic Benefits:** {med['benefits']}")
                    
                except Exception as e:
                    st.error(f"❌ Error processing prescription: {str(e)}")
                    if 'content' in locals():
                        with st.expander("View Raw Response"):
                            st.code(content)

# Reuse your existing prompt
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

if __name__ == "__main__":
    main()
