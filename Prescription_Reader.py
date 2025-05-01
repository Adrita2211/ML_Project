import streamlit as st
import google.generativeai as genai
from PIL import Image

# Configuration
API_KEY = st.secrets["GOOGLE_API_KEY"]
genai.configure(api_key=API_KEY)

# Custom CSS for better visualization
st.markdown("""
<style>
    .medication-card {
        padding: 1rem;
        margin: 1rem 0;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    .warning-card {
        background-color: #fff3cd;
        padding: 1rem;
        margin: 1rem 0;
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

# System Prompt with Enhanced Formatting
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
    """Analyze prescription using Gemini Flash with advanced OCR capabilities"""
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    response = model.generate_content(
        [
            SYSTEM_PROMPT,
            genai.types.Part.from_data(
                data=image,
                mime_type="image/png"
            )
        ],
        generation_config={
            "temperature": 0.1,
            "max_output_tokens": 2000,
        }
    )
    
    return response.text

# Streamlit UI
st.title("Advanced Prescription Analyzer 🩺")
st.caption("Medical-grade OCR powered by Google Gemini Flash")

uploaded_file = st.file_uploader("Upload Prescription Image", 
                                type=["png", "jpg", "jpeg"],
                                help="Upload clear image of prescription (max 4MB)")

if uploaded_file:
    try:
        # Validate image
        img = Image.open(uploaded_file)
        if img.size[0] * img.size[1] > 4000000:  # ~4MP limit
            st.error("Image resolution too high. Please upload image under 4MP.")
            st.stop()
            
        with st.spinner("🔍 Analyzing prescription..."):
            analysis = analyze_prescription(uploaded_file.getvalue())
            
        if analysis:
            st.subheader("Analysis Results", divider="blue")
            st.markdown(analysis, unsafe_allow_html=True)
            
            # Add safety warnings
            st.markdown("""
            <div class="warning-card">
                ⚠️ **Important Notes:**
                - Always consult your physician before taking medications
                - Report any adverse effects immediately
                - Store medications properly
                - Check expiration dates
            </div>
            """, unsafe_allow_html=True)
            
    except Exception as e:
        st.error(f"Analysis failed: {str(e)}")
        st.error("Please ensure:")
        st.error("- Clear image of a valid prescription")
        st.error("- Legible text and proper lighting")
        st.error("- Valid Google API credentials")

# Sidebar with Instructions
with st.sidebar:
    st.header("Instructions")
    st.markdown("""
    1. Upload prescription image (PNG/JPG)
    2. Wait for AI analysis (10-30 seconds)
    3. Review structured medication data
    4. Consult your physician for validation
    
    **Supported Content:**
    - Handwritten/Rx pad prescriptions
    - Digital medication lists
    - Pharmacy labels
    
    **Limitations:**
    - Cannot verify prescription validity
    - No dosage recommendations
    - Not a substitute for medical advice
    """)
