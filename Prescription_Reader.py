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
    st.session_state.model = genai.GenerativeModel('gemini-1.5-flash')

def optimize_image(image_bytes, max_size=1024):
    """Resize image to reduce payload size"""
    image = Image.open(io.BytesIO(image_bytes))
    if max(image.size) > max_size:
        image.thumbnail((max_size, max_size))
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='JPEG', quality=85)
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
                                    "mime_type": "image/jpeg",
                                    "data": file_bytes
                                }},
                                PROMPT
                            ],
                            request_options={"timeout": 30}
                        )
                        status.update(label="Analysis complete!", state="complete")

                    content = response.text
                    medicines = parse_medicine_data(content)
                    
                    if not medicines:
                        st.warning("⚠️ No medications found in the prescription")
                        return
                    
                    st.success(f"✅ Found {len(medicines)} medications")
                    
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
                                st.mark
