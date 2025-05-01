
# Create model
model = genai.GenerativeModel('gemini-1.5-flash')

# App UI
st.title("Simple AI Assistant")
prompt = st.text_input("Ask me anything:")

if prompt:
    response = model.generate_content(prompt)
    st.write("Response:")
    st.write(response.text)
