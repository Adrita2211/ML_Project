import streamlit as st
import pandas as pd
import joblib
import numpy as np# -*
@st.cache_resource
def load_encoder():
    return joblib.load("onehot_encoder.pkl")

@st.cache_resource
def load_model():
    return joblib.load("xgb_model.pkl")
@st.cache_resource
def load_data():
    return joblib.load("bank_data_encoded.pkl")
@st.cache_resource
def load_job_frequencies():
    df = load_data()
    print(df.head())
    job_counts = df["job"].value_counts()  # Count job occurrences
    threshold = 100  # Set threshold (adjustable)
    common_jobs = set(job_counts[job_counts >= threshold].index)  # Keep common jobs
    #common_jobs =1
   # return common_jobs 

encoder = load_encoder()
model = load_model()
#frequent_jobs = load_job_frequencies()

st.title("Portuguese Bank Marketing Campaign Predictor 🎯")
st.write("Enter the details to predict if the customer will subscribe to the term deposit.")


poutcome = st.selectbox("Previous Campaign Outcome", ["success", "failure", "unknown", "other"])
month_options = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

# Replace number input with a dropdown
month = st.selectbox("Month", list(month_options.keys()))
default = st.selectbox("Default", ["yes", "no"])
contact = st.selectbox("Contact Type", ["cellular", "telephone"])
loan = st.selectbox("Loan", ["yes", "no"])
job = st.selectbox("Job", ["admin.", "blue-collar", "technician", "services", "management", "retired", "self-employed", "entrepreneur", "unemployed", "housemaid", "student"])
day = st.number_input("Day of Contact", min_value=1, max_value=31, value=15)
pdays = st.number_input("Previous Days Contact", min_value=-1, max_value=500, value=10)
age = st.number_input("Age", min_value=18, max_value=100, value=30)
marital = st.selectbox("Marital Status", ["married", "single", "divorced"])
categorical_data = pd.DataFrame([[poutcome,month,default, contact, loan, job, marital]], 
                                columns=['poutcome','month','default', 'contact', 'loan', 'job', 'marital'])
categorical_data = categorical_data.astype(str)
numerical_data = pd.DataFrame([[day,pdays,age]], columns=['day', 'pdays','age'])
encoded_categorical = pd.DataFrame(encoder.transform(categorical_data), 
                                   columns=encoder.get_feature_names_out())
input_data = pd.concat([numerical_data, encoded_categorical], axis=1)
print("adrita")
print(input_data)
# Apply Encoding
# input_encoded = pd.DataFrame(encoder.transform(input_data), columns=encoder.get_feature_names_out())

# Predict Outcome
if st.button("Predict"):
   prediction = model.predict(input_data)
   result = "Yes (Subscribed)" if prediction[0] == 1 else "No (Not Subscribed)"
   st.success(f"Prediction: **{result}**")
    
import os
os.system("streamlit run app.py")