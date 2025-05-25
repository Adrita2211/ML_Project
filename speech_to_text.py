import streamlit as st
import azure.cognitiveservices.speech as speechsdk
import openai
from openai import AzureOpenAI

#speech configuration
SPEECH_KEY = st.secrets["AZURE_SPEECH_KEY"] 
SPEECH_REGION = "centralindia"
#azure open ai
endpoint = "https://azureaihub17053356581548.cognitiveservices.azure.com/"
model_name = "gpt-4o"
deployment = "gpt-4o"

subscription_key = "FRmMLpsNo2ChMwxpD25GvaQ8spL4nNTDoOv8QcSKPVCacU29hO4JJQQJ99BEAC77bzfXJ3w3AAAAACOGA1GC"
api_version = "2024-12-01-preview"

client = AzureOpenAI(
    api_version="2024-12-01-preview",
    endpoint="https://azureaihub17053356581548.cognitiveservices.azure.com/",
    credential=AzureKeyCredential(subscription_key)
)

def recognize_speech():
    speech_config = speechsdk.SpeechConfig(subscription="YOUR_AZURE_SPEECH_KEY", region="YOUR_REGION")
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config)
    
    print("Speak now...")
    result = recognizer.recognize_once()
    
    return result.text if result.reason == speechsdk.ResultReason.RecognizedSpeech else None


def get_chatbot_response(user_input):

    response = client.chat.completions.create(
    messages=[{"role": "user", "content": user_input}],
    max_tokens=4096,
    temperature=1.0,
    top_p=1.0,
    model=deployment
)
def text_to_speech(response_text):
    speech_config = speechsdk.SpeechConfig(subscription="YOUR_AZURE_SPEECH_KEY", region="YOUR_REGION")
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config)
    
    synthesizer.speak_text_async(response_text)

st.title("AI Chatbot with OpenAI and Azure Speech")

if st.button("Speak"):
    user_input = recognize_speech()
    if user_input:
        st.write(f"**You said:** {user_input}")
        chatbot_response = get_chatbot_response(user_input)
        st.write(f"**Chatbot:** {chatbot_response}")
        text_to_speech(chatbot_response)
