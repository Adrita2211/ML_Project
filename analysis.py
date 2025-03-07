# -*- coding: utf-8 -*-
"""
Created on Sun Feb 23 15:45:34 2025

@author: Adrita
"""
#pip install xgboost
####import dependencies########
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import AdaBoostClassifier
import xgboost as xgb
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_curve, confusion_matrix
from sklearn.preprocessing import OneHotEncoder
from sklearn.model_selection import RandomizedSearchCV
from sklearn.feature_selection import RFE
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.preprocessing import OneHotEncoder
from imblearn.over_sampling import SMOTE
from imblearn.under_sampling import RandomUnderSampler
from sklearn.metrics import confusion_matrix, classification_report
from sklearn.model_selection import train_test_split
import pickle
########read csv###############
data=pd.read_csv("bank.csv",sep=";")
#####binng job field###########
job_counts = data['job'].value_counts()
print(job_counts)
threshold = 0.05 * len(data)
# Identify frequent jobs
frequent_jobs = job_counts[job_counts > threshold].index
print(frequent_jobs)
# Apply binning: Keep frequent jobs, others become "Other"
data['job_binned'] = data['job'].apply(lambda x: x if x in frequent_jobs else 'Other')
# Check the new distribution
print(data['job_binned'].value_counts())
data['job'] = data['job_binned']
data.drop(columns=['job_binned'], inplace=True)
print(data.head(10))
############encoding the dependent variable########
data['y'] = [0 if x == 'no' else 1 for x in data['y']]
data['y']
######removing dependent variable #################
X=data.drop(columns=['y', 'duration'],axis=1)
Y=data['y']
print(data['y'].value_counts())
print(X.head())
###################################################
numerical_features = X.select_dtypes(exclude=["object"]).columns.tolist()
categorical_features = X.select_dtypes(include=["object"]).columns.tolist()
print("numerical...")
print(numerical_features)
print("categories...")
print(categorical_features)
for col in categorical_features:
    X[col] = data[col].astype("category")
print(X.dtypes)
model = xgb.XGBClassifier(tree_method="hist", enable_categorical=True)
model.fit(X,Y)
importance = model.get_booster().get_score(importance_type='gain')
print(importance)
sorted_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)
top_10_features = dict(sorted_features[:10])
feature_list = list(top_10_features.keys())
print(top_10_features)
df_selected = X[feature_list]
print("adrita2")
print(df_selected.head())
#################################################
X=df_selected
print(X.head()) 
with open("bank_data_encoded.pkl", "wb") as file:
    pickle.dump(X, file)
#############selected data set#########
numerical_features = X.select_dtypes(exclude=["category"]).columns.tolist()
categorical_features = X.select_dtypes(include=["category"]).columns.tolist()
######################################
print("categories")
print(categorical_features)
encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False)
one_hot_encoded = encoder.fit_transform(X[categorical_features])
one_hot_df = pd.DataFrame(one_hot_encoded, columns=encoder.get_feature_names_out(categorical_features))
df_encoded = pd.concat([X, one_hot_df], axis=1)
data_encoded = df_encoded.drop(categorical_features, axis=1)
print(data_encoded.head())
print(data_encoded.dtypes)
X=data_encoded
print(X.dtypes)
print(Y)
# Load encoded dataset (if needed for reference)
# Save the label encoders separately (useful for decoding or future use)
with open("onehot_encoder.pkl", "wb") as file:
    pickle.dump(encoder, file)
print()
print(X.dtypes)
###over sampling & undesr sampling########
smote = SMOTE(sampling_strategy=0.7, random_state=42)  # Increase minority class to 70% of majority
X_smote, y_smote = smote.fit_resample(X,Y)
undersampler = RandomUnderSampler(sampling_strategy=0.7, random_state=42)  # Reduce majority class
X_smote_under, y_smote_under = undersampler.fit_resample(X_smote, y_smote)
################
print("adrita3")
print(X_smote_under.columns)
#####################################
trainX, testX, trainY, testY = train_test_split(X_smote_under, y_smote_under,test_size=0.3,random_state=24)
#####################################
###Model creation#####
import xgboost as XGB
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_curve, confusion_matrix
xgb = XGB.XGBClassifier(objective='multi:softmax', learning_rate = 0.01, max_depth=20,n_estimators=250,
num_class=2, random_state=42)
# Train the model
xgb.fit(trainX, trainY)
predY = xgb.predict(testX)
y_prob = xgb.predict_proba(testX)[:,1]
print(round(accuracy_score(testY, predY)*100,2))
print(f"Classification Report:\n{classification_report(testY, predY)}")
with open("xgb_model.pkl", "wb") as file:
    pickle.dump(xgb, file)


