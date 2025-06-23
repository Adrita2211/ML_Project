import streamlit as st
import boto3
import uuid

# Setup Bedrock agent client
bedrock_agent = boto3.client("bedrock-agent-runtime", region_name="ap-southeast-1")

AGENT_ID = "UQA8UCQ9VC"
AGENT_ALIAS_ID = "LNA7EFUEUH"
SESSION_ID = str(uuid.uuid4())

# Query function
def query_bedrock_agent(user_input):
    try:
        response = bedrock_agent.invoke_agent(
            agentId=AGENT_ID,
            agentAliasId=AGENT_ALIAS_ID,
            sessionId=SESSION_ID,
            inputText=user_input
        )

        completion = ""
        for event in response.get("completion", []):
            if 'chunk' in event:
                chunk = event["chunk"]
                completion += chunk["bytes"].decode("utf-8")

        return completion.strip()
    except Exception as e:
        return f"⚠️ Error: {str(e)}"

# ------------------- Streamlit UI -------------------

# Set page config
st.set_page_config(page_title="Edu Plus", page_icon="🎓", layout="wide")

# Custom CSS for elegance
st.markdown("""
    <style>
        .title { font-size: 2.5em; font-weight: bold; color: #2E8B57; }
        .subtitle { font-size: 1.3em; color: #444; }
        .section { border-left: 4px solid #2E8B57; padding-left: 1em; margin-top: 2em; }
        .response-box { background-color: #f8f9fa; padding: 1em; border-radius: 10px; border: 1px solid #ccc; }
        .footer { font-size: 0.9em; color: #888; margin-top: 2em; text-align: center; }
    </style>
""", unsafe_allow_html=True)

# Header
st.markdown('<div class="title">👩‍🏫 Teaching Companion</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Your AI-powered assistant for lesson planning, quiz creation, student analysis & parent communication.</div>', unsafe_allow_html=True)

# Mode Selection
st.markdown('<div class="section"><strong>🧭 Choose Your Task</strong></div>', unsafe_allow_html=True)
task = st.radio("Select what you want to do:", [
    "📘 Generate Lesson Plan",
    "📝 Create Quiz",
    "📊 Analyze Student Performance",
    "📧 Analyze Class Attendance"
])

# User Prompt Input
st.markdown('<div class="section"><strong>✍️ Enter your instruction</strong></div>', unsafe_allow_html=True)

default_prompts = {
    "📘 Generate Lesson Plan": "Generate a lesson plan for class 6 on topic photosynthesis in a lucid and easy manner",
    "📝 Create Quiz": "Create 5 multiple choice questions for class 6 on photosynthesis with correct answers",
    "📊 Analyze Student Performance": "Analyze performance of student John Doe in last 3 assessments and suggest improvement tips",
    "📧 Attendance Checker": "Check Student Attendance Details"
}

user_prompt = st.text_area("What would you like me to do?", default_prompts[task], height=100)

# Button to trigger agent
if st.button("Enter"):
    with st.spinner("🤖 Thinking..."):
        output = query_bedrock_agent(user_prompt)

    st.markdown('<div class="section"><strong>📤 AI Response</strong></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="response-box">{output or "⚠️ No response received from the agent."}</div>', unsafe_allow_html=True)

# Footer
st.markdown('<div class="footer">© 2025 Teaching Companion | Built with Amazon Bedrock, Streamlit, and ❤️ for Educators</div>', unsafe_allow_html=True)