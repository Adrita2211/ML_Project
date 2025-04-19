import streamlit as st
import pinecone
from pinecone import Pinecone, ServerlessSpec
import cv2
import numpy as np
from keras.applications.vgg16 import VGG16, preprocess_input
from keras.preprocessing import image
from keras.models import Model
from PIL import Image
from io import BytesIO
import boto3
import matplotlib.pyplot as plt


# --- Initialize Pinecone ---
pinecone = Pinecone(
    api_key=""
)
index = pinecone.Index("visual-search-with-images")  

# --- Initialize AWS S3 ---
s3 = boto3.client(
    's3',
    aws_access_key_id="",
    aws_secret_access_key=""
)
bucket_name = "ordermonitoringbucket"

# --- Load VGG16 model ---
base_model = VGG16(weights='imagenet')
classificationmodel = Model(inputs=base_model.input, outputs=base_model.get_layer('fc1').output)


# --- Function to get image embedding ---
def get_image_embedding(img):
    img = cv2.resize(img, (224, 224))
    img = image.img_to_array(img)
    img = np.expand_dims(img, axis=0)
    img = preprocess_input(img)
    embedding = classificationmodel.predict(img)
    return embedding.flatten()


# --- Function to get image from S3 ---
def get_image_from_s3(product_id):
    try:
        key = f"{product_id}.png"  # Adjust if needed
        response = s3.get_object(Bucket=bucket_name, Key=key)
        image_data = response['Body'].read()
        return Image.open(BytesIO(image_data))
    except Exception as e:
        st.error(f"Error loading image from S3: {str(e)}")
        return None


# --- Streamlit App ---
st.title("Visual Product Search")

uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Read and display uploaded image
    image = Image.open(uploaded_file)
    st.image(image, caption='Uploaded Image.', use_column_width=True)

    # --- Image Processing and Search ---
    image = np.array(image)  # Convert PIL Image to NumPy array
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)  # Convert to BGR if necessary 

    # Get image embedding
    query_embedding = get_image_embedding(image)

    # Query Pinecone
    results = index.query(
        vector=query_embedding.tolist(),
        top_k=2,  # Number of similar images to retrieve
        include_values=False
    )

    # Display similar images
    st.subheader("Similar Products:")
    if results.matches:
        for match in results.matches:
            product_id = match.id
            similarity_score = match.score

            similar_image = get_image_from_s3(product_id)
            if similar_image:
                st.image(similar_image, caption=f"Product ID: {product_id}, Similarity: {similarity_score:.2f}", use_column_width=True)
    else:
        st.write("No similar products found.")