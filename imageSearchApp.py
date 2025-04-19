import streamlit as st
import pinecone
from pinecone import Pinecone, ServerlessSpec
import numpy as np
from keras.applications.vgg16 import VGG16, preprocess_input
from keras.models import Model
from PIL import Image
from io import BytesIO
import boto3

# --- Initialize Pinecone ---
@st.cache_resource
def init_pinecone():
    return Pinecone(api_key=st.secrets["PINECONE_API_KEY"])
pinecone = init_pinecone()
index = pinecone.Index("visual-search-with-images")

# --- Initialize AWS S3 ---
@st.cache_resource
def init_s3():
    return boto3.client(
        's3',
        aws_access_key_id=st.secrets["AWS_ACCESS_KEY"],
        aws_secret_access_key=st.secrets["AWS_SECRET_KEY"]
    )

s3 = init_s3()
bucket_name = "ordermonitoringbucket"

# --- Load VGG16 model ---
@st.cache_resource
def load_model():
    base_model = VGG16(weights='imagenet')
    return Model(inputs=base_model.input, outputs=base_model.get_layer('fc1').output)

classificationmodel = load_model()

# --- Function to get image embedding ---
def get_image_embedding(pil_img):
    # Resize image using Pillow
    img = pil_img.resize((224, 224))
    # Convert to numpy array and process
    img_array = np.array(img)
    img_array = np.expand_dims(img_array, axis=0)
    img_array = preprocess_input(img_array)
    embedding = classificationmodel.predict(img_array)
    return embedding.flatten()

# --- Function to get image from S3 ---
def get_image_from_s3(product_id):
    try:
        key = f"{product_id}.png"
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
    pil_image = Image.open(uploaded_file).convert('RGB')
    st.image(pil_image, caption='Uploaded Image.', use_column_width=True)

    # Get image embedding
    query_embedding = get_image_embedding(pil_image)

    # Query Pinecone
    results = index.query(
        vector=query_embedding.tolist(),
        top_k=2,
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
                st.image(similar_image, 
                         caption=f"Product ID: {product_id}, Similarity: {similarity_score:.2f}", 
                         use_column_width=True)
    else:
        st.write("No similar products found.")
