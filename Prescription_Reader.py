import streamlit as st
import google.generativeai as genai
import re
import io
from PIL import Image

# Configure GenAI client once at startup
if "genai_configured" not in st.session_state:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    st.session_state.genai_configured = True

# Create model instance once
if "model" not in st.session_state:
    st.session_state.model = genai.GenerativeModel('gemini-2.0-flash')

def optimize_image(image_bytes, max_size=1024):
    """Resize image to reduce payload size"""
    image = Image.open(io.BytesIO(image_bytes))
    if max(image.size) > max_size:
        image.thumbnail((max_size, max_size))
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG', quality=85)
        return img_byte_arr.getvalue()
    return image_bytes

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

def main():
    st.title("📋 Prescription Analyzer")
    st.markdown("Upload a prescription image to analyze medications and their details")
    
    uploaded_file = st.file_uploader("Choose a prescription image", 
                                   type=["png", "jpg", "jpeg"])
    
    if uploaded_file is not None:
        st.image(uploaded_file, caption="Uploaded Prescription", width=300)
        
        if st.button("Analyze Prescription"):
            with st.spinner("Analyzing medication details..."):
                try:
                    # Optimize image before processing
                    file_bytes = optimize_image(uploaded_file.getvalue())
                    
                    # Create async task with timeout
                    with st.status("Processing...", expanded=True) as status:
                        st.write("🔍 Extracting prescription details...")
                        response = st.session_state.model.generate_content(
                            [
                                {"inline_data": {
                                    "mime_type": "image/png",
                                    "data": file_bytes
                                }},
                                PROMPT
                            ],
                            request_options={"timeout": 30}
                        )
                        status.update(label="Analysis complete!", state="complete")

                    content = response.text
					st.write("displaying content")
					st.write(content)
                    medicines = parse_medicine_data(content)
                    st.write("displaying medicines")
                    st.write(medicines)
                   
                    
                except Exception as e:
                    st.error(f"❌ Error processing prescription: {str(e)}")
                    if 'content' in locals():
                        with st.expander("View Raw Response"):
                            st.code(content)

if __name__ == "__main__":
    main()
