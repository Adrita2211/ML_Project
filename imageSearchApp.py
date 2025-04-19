import streamlit as st
import pinecone
from pinecone import Pinecone
import numpy as np
from keras.applications.vgg16 import VGG16, preprocess_input
from keras.models import Model
from PIL import Image
from io import BytesIO
import boto3
from ultralytics import YOLO

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
def load_classification_model():
    base_model = VGG16(weights='imagenet')
    return Model(inputs=base_model.input, outputs=base_model.get_layer('fc1').output)

classificationmodel = load_classification_model()

@st.cache_resource
def load_model():
    return YOLO('/content/best.pt')

model_yolo = load_model()

# --- Function to get image embedding ---
def get_image_embedding(pil_img):
    # Resize using PIL
    img = pil_img.resize((224, 224))
    # Convert to array and process
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

    # Convert to numpy array for YOLO
    image_np = np.array(pil_image)

    # --- Object Detection with YOLO ---
    results_yolo = model_yolo.predict(image_np)
    detections = results_yolo[0].boxes.data

    if detections.shape[0] > 0:
        for *xyxy, conf, cls in detections:
            x1, y1, x2, y2 = map(int, xyxy)
            
            # Crop using PIL
            cropped_pil = pil_image.crop((x1, y1, x2, y2))
            
            # Get embedding for cropped object
            query_embedding = get_image_embedding(cropped_pil)

            # Query Pinecone
            results_pinecone = index.query(
                vector=query_embedding.tolist(),
                top_k=2,
                include_values=False
            )

            # Display similar images
            st.subheader("Similar Products:")
            if results_pinecone.matches:
                for match in results_pinecone.matches:
                    product_id = match.id
                    similarity_score = match.score

                    similar_image = get_image_from_s3(product_id)
                    if similar_image:
                        st.image(
                            similar_image,
                            caption=f"Product ID: {product_id}, Similarity: {similarity_score:.2f}",
                            use_column_width=True
                        )
            else:
                st.write("No similar products found.")
    else:
        st.write("No objects detected in the image.")
