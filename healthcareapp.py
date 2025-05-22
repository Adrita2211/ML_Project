import streamlit as st
import os
import tempfile
import base64
import json
import re
from enum import Enum
from azure.identity import DefaultAzureCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.cosmos import CosmosClient, PartitionKey
from autogen import AssistantAgent, UserProxyAgent
from dateutil import parser as date_parser
# --- Cosmos DB Config ---
COSMOS_ENDPOINT =st.secrets["COSMOS_DB_ENDPOINT_URL"] 
COSMOS_KEY = st.secrets["COSMOS_DB_KEY"]
DATABASE_NAME = "MedicalAssistantDB"
CONTAINER_NAME = "Appointments"
cosmos_client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
database = cosmos_client.create_database_if_not_exists(id=DATABASE_NAME)
container = database.create_container_if_not_exists(
    id=CONTAINER_NAME,
    partition_key=PartitionKey(path="/userEmail"),
    offer_throughput=400)


# --- Enum for Agent Types ---
class AgentType(Enum):
    DOCUMENT_ANALYZER = 1
    PRESCRIPTION_READER = 2
    HEALTH_ADVISOR = 3


# --- Medical Agent Class ---
class MedicalAgent:

    def __init__(self):
        try:
            self.credential = DefaultAzureCredential()
            self.document_client = DocumentIntelligenceClient(
                st.secrets["AZURE_DOC_INTELLIGENCE_ENDPOINT"],
                credential=AzureKeyCredential(
                    st.secrets["AZURE_DOC_INTELLIGENCE_KEY"]
                ))
            from openai import AzureOpenAI
            self.openai_client = AzureOpenAI(
                api_version="2024-05-01-preview",
                azure_endpoint=
                st.secrets["AZURE_OPEN_AI_ENDPOINT"],
                api_key=
                st.secrets["AZURE_OPEN_AI_KEY"]
            )
            self.api_initialized = True
        except Exception as e:
            st.error(f"Error initializing API clients: {str(e)}")
            self.api_initialized = False

        self.agent_prompts = {
            AgentType.DOCUMENT_ANALYZER: {
                "system":
                "Analyze medical reports and provide:\n- Report Details\n- Trend analysis\n- Lifestyle recommendations\n- Urgency indicators\nFormat in markdown.",
                "temperature": 0.1
            },
            AgentType.PRESCRIPTION_READER: {
                "system": """
Analyze the uploaded prescription and provide the following information for each medication listed:

1. **Medication Name**: Include both generic and brand names.
2. **Dosage Instructions**: How and when it should be taken.
3. **Potential Side Effects**: List common side effects with emojis.
4. **Drug Interactions**: Warn about any known interactions.
5. **Important Warnings**: Highlight severe risks (e.g., allergies, overdose) with ⚠️.
6. **Usage Statistics**: Include estimated percentage of patients commonly prescribed this medication.
7. **Effectiveness Overview**:
   - Brief summary of how effective the drug is based on studies or clinical use.
   - Include a simple markdown bar chart (1–5 scale or percentage) to visualize effectiveness.

⚠️ Use simple language. Format the output clearly in markdown with headings and bullet points. Add emojis where appropriate for better understanding.
""",
                "temperature": 0.2
            },
            AgentType.HEALTH_ADVISOR: {
                "system":
                "Answer health questions with general info only. Never diagnose. Add disclaimers.",
                "temperature": 0.3
            }
        }

    def analyze_document(self, file_content: bytes) -> str:
        if not self.api_initialized:
            return "Error: API not initialized."
        try:
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name

            with open(temp_file_path, "rb") as f:
                analyze_request = {
                    "base64Source": base64.b64encode(f.read()).decode("utf-8")
                }
                poller = self.document_client.begin_analyze_document(
                    "prebuilt-layout",
                    body=analyze_request,
                    output_content_format="markdown")
            result = poller.result()
            text_content = "\n".join(line.content for page in result.pages
                                     for line in page.lines)
            os.unlink(temp_file_path)

            response = self.openai_client.chat.completions.create(
                model="mistral-medium-2505",
                messages=[{
                    "role":
                    "system",
                    "content":
                    self.agent_prompts[AgentType.DOCUMENT_ANALYZER]["system"]
                }, {
                    "role": "user",
                    "content": text_content
                }],
                temperature=self.agent_prompts[
                    AgentType.DOCUMENT_ANALYZER]["temperature"])
            return response.choices[0].message.content or "No analysis."
        except Exception as e:
            return f"Error analyzing document: {e}"

    def process_prescription(self, file_content: bytes) -> str:
        if not self.api_initialized:
            return "Error: API not initialized."
        try:
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name

            with open(temp_file_path, "rb") as f:
                analyze_request = {
                    "base64Source": base64.b64encode(f.read()).decode("utf-8")
                }
                poller = self.document_client.begin_analyze_document(
                    "prebuilt-read",
                    body=analyze_request,
                    output_content_format="markdown")
            result = poller.result()
            text_content = "\n".join(line.content for page in result.pages
                                     for line in page.lines)
            os.unlink(temp_file_path)

            response = self.openai_client.chat.completions.create(
                model="mistral-medium-2505",
                messages=[{
                    "role":
                    "system",
                    "content":
                    self.agent_prompts[AgentType.PRESCRIPTION_READER]["system"]
                }, {
                    "role": "user",
                    "content": text_content
                }],
                temperature=self.agent_prompts[
                    AgentType.PRESCRIPTION_READER]["temperature"])
            return response.choices[
                0].message.content or "No details extracted."
        except Exception as e:
            return f"Error processing prescription: {e}"

    def answer_health_query(self, query: str) -> str:
        if not self.api_initialized:
            return "Error: API not initialized."
        try:
            response = self.openai_client.chat.completions.create(
                model="mistral-medium-2505",
                messages=[{
                    "role":
                    "system",
                    "content":
                    self.agent_prompts[AgentType.HEALTH_ADVISOR]["system"]
                }, {
                    "role": "user",
                    "content": query
                }],
                temperature=self.agent_prompts[
                    AgentType.HEALTH_ADVISOR]["temperature"])
            return response.choices[
                0].message.content + "\n\n⚠️ *Always consult a healthcare professional.*"
        except Exception as e:
            return f"Error answering query: {e}"


# --- Autogen Agents ---
booking_agent = AssistantAgent(
    name="booking_agent",
    llm_config={
        "model":
        "gpt-4o",
        "api_key":st.secrets["AZURE_OPEN_AI_KEY"],
        "api_type":
        "azure",
        "api_version":
        "2024-12-01-preview",
        "base_url":st.secrets["AZURE_GPT4_URL"]
    },
    system_message=
    ("You are an appointment scheduling assistant.\n"
     "Extract the following fields from the user's booking request:\n"
     "- name\n- email\n- doctorId\n- time\n\n"
     "Respond ONLY with a valid JSON object. Example:\n"
     '{ "name": "John", "email": "john@example.com", "doctorId": "D1234", "time": "2PM May 25 2025" }\n\n'
     "❗Do not include any explanation, greeting, or markdown. Just return the JSON."
     ))
conflict_agent = AssistantAgent(
    name="conflict_agent",
    llm_config={
        "model":
        "gpt-4o",
        "api_key":st.secrets["AZURE_OPEN_AI_KEY"],
        "api_type":
        "azure",
        "api_version":
        "2024-12-01-preview",
        "base_url":st.secrets["AZURE_GPT4_URL"]
    },
    system_message=
    "Suggest 3 alternate times if a doctor appointment is unavailable. Use times like 9AM, 11AM, 2PM, 4PM."
)

cbt_agent = AssistantAgent(
    name="cbt_agent",
    llm_config={
        "model":
        "o4-mini",
        "base_url":st.secrets["AZURE_O4_END_POINT"],
        "api_type":
        "azure",
        "api_version":
        "2024-12-01-preview",
        "api_key":st.secrets["AZURE_O4_API_KEY"]
    },
    system_message=
    ("You are a CBT assistant trained on clinically validated therapy techniques. "
     "Guide users through cognitive restructuring, journaling, and behavioral activation. "
     "Always include disclaimers and encourage professional consultation."))

research_agent = AssistantAgent(
    name="research_agent",
    llm_config={
        "model":
        "o4-mini",
        "base_url":st.secrets["AZURE_O4_END_POINT"],
        "api_type":
        "azure",
        "api_version":
        "2024-12-01-preview",
        "api_key":st.secrets["AZURE_O4_API_KEY"]
    },
    system_message=
    ("You are a medical research assistant. Answer health-related questions by referencing "
     "peer-reviewed journals and clinical guidelines. Always cite sources."))

mood_agent = AssistantAgent(
    name="mood_agent",
    llm_config={
        "model":
        "o4-mini",
        "base_url":st.secrets["AZURE_O4_END_POINT"],
        "api_type":
        "azure",
        "api_version":
        "2024-12-01-preview",
        "api_key":st.secrets["AZURE_O4_API_KEY"]
    },
    system_message=
    ("You are a compassionate and friendly mood tracking assistant. "
     "Your job is to help users log their mood, identify emotional patterns, and suggest evidence-based coping strategies. "
     "If the user expresses sadness, gently acknowledge their feelings and offer comforting words. "
     "Then suggest uplifting activities such as watching feel-good movies, reading inspiring books, listening to calming music, or engaging in light physical activity. "
     "Include emojis and a warm tone to cheer them up. "
     "If the user is feeling happy or shares joyful thoughts, celebrate with them! Encourage them to reflect on what made them feel good and suggest ways to sustain that positivity. "
     "Always be empathetic, supportive, and non-judgmental. "
     "Avoid clinical diagnoses. End with a gentle reminder that it's okay to seek help from a mental health professional if needed. "
     "Use emojis to enhance emotional connection and keep the tone light and encouraging."
     ))

user_proxy = UserProxyAgent(name="user_proxy", human_input_mode="NEVER")


# --- Appointment Helpers ---
def is_slot_available(doctorId: str, date_time: str) -> bool:
    query = "SELECT * FROM c WHERE c.doctorId = @doctorId AND c.appointmentTime = @dateTime"
    parameters = [{
        "name": "@doctorId",
        "value": doctorId
    }, {
        "name": "@dateTime",
        "value": date_time
    }]
    results = list(
        container.query_items(query=query,
                              parameters=parameters,
                              enable_cross_partition_query=True))
    return len(results) == 0


def save_appointment(user_email, doctorId, date_time):
    item = {
        "id": f"{user_email}-{date_time}",
        "userEmail": user_email,
        "doctorId": doctorId,
        "appointmentTime": date_time
    }
    container.upsert_item(item)
    return item


def handle_booking_request(user_input):
    try:
        response = user_proxy.initiate_chat(recipient=booking_agent,
                                            message=user_input,
                                            max_turns=1)
        #st.write("hello", response.chat_history[-1]["content"])
        content = response.chat_history[-1]["content"]
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return "❌ Could not understand the booking request."
        data = json.loads(match.group())
        try:
            parsed_datetime = date_parser.parse(data["time"])
            iso_time = parsed_datetime.isoformat()
        except Exception as dt_err:
            return f"❌ Unable to parse time: {dt_err}"
        if is_slot_available(data["doctorId"], iso_time):
            saved = save_appointment(data["email"], data["doctorId"], iso_time)
            return f"✅ Appointment booked for {data['name']} with a {saved['doctorId']} on {saved['appointmentTime']}."
        else:
            st.write("conflict agent")
            #return "booking confirmed"
            alt = user_proxy.initiate_chat(
                recipient=conflict_agent,
                message=
                f"Doctor {data['doctorId']} is busy at {data['time']}. Suggest alternatives.",
                max_turns=1)
            alt_text = alt.chat_history[-1]["content"]
            return f"❌ That slot is taken.\n\n**Alternatives:**\n{alt_text}"
    except Exception as e:
        return f"❌ Error booking: {e}"


# --- Streamlit UI ---
st.set_page_config(page_title="MediGenie", layout="wide")
st.title("🧞 MediGenie ")

if 'agent' not in st.session_state:
    st.session_state.agent = MedicalAgent()

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Medical Report Analysis", "💊 Prescription Reader",
    "🌈 Mindful Assistant ", "📅 Book Appointment"
])

with tab1:
    st.header("Medical Report Analysis")
    uploaded_doc = st.file_uploader("Upload Medical Report",
                                    type=["pdf", "jpg", "jpeg", "png"])
    if st.button("Analyze Document") and uploaded_doc:
        with st.spinner("Analyzing..."):
            result = st.session_state.agent.analyze_document(
                uploaded_doc.getvalue())
            st.markdown(result)

with tab2:
    st.header("Prescription Interpretation")
    uploaded_prescription = st.file_uploader(
        "Upload Prescription", type=["pdf", "jpg", "jpeg", "png"])
    if st.button("Analyze Prescription") and uploaded_prescription:
        with st.spinner("Analyzing..."):
            result = st.session_state.agent.process_prescription(
                uploaded_prescription.getvalue())
            st.markdown(result)

with tab3:
    st.header("🌈 Mindful Assistant")
    mode = st.selectbox(
        "Choose Support Type",
        ["CBT Support", "Mood Tracking", "General Health Info"])
    user_input = st.text_area("Your input:")
    if st.button("Submit") and user_input:
        with st.spinner("Processing..."):
            if mode == "CBT Support":
                result = user_proxy.initiate_chat(recipient=cbt_agent,
                                                  message=user_input,
                                                  max_turns=3)
            elif mode == "Mood Tracking":
                result = user_proxy.initiate_chat(recipient=mood_agent,
                                                  message=user_input,
                                                  max_turns=3)
            else:
                result = user_proxy.initiate_chat(recipient=research_agent,
                                                  message=user_input,
                                                  max_turns=3)
            st.markdown(result.chat_history[-1]["content"])

with tab4:
    st.header("Book a Doctor Appointment")
    booking_input = st.text_area(
        "Describe your booking (e.g., name, email, doctorId, time):")
    if st.button("Book Appointment") and booking_input:
        with st.spinner("Processing Booking..."):
            response = handle_booking_request(booking_input)
            st.markdown(response)

st.markdown("---")
st.markdown(
    "⚠️ This tool does not replace medical advice. Always consult a licensed physician."
)
