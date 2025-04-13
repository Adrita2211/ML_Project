import streamlit as st
import numpy as np
from ultralytics import YOLO
import cv2
import faiss
from keras.applications.vgg16 import VGG16, preprocess_input
from keras.preprocessing import image
from keras.models import Model
from PIL import Image

# Image paths mapping (ensure these images exist in your directory)
image_paths = {
    0: "img_1.png",
    1: "img_2.png",
    2: "img_3.png",
    3: "img_4.png",  # Added missing index 3
    4: "img_5.png",
    5: "img_6.png",  # Changed duplicate index 6 to 5
    6: "img_7.png"
}

# Initialize models
@st.cache_resource
def load_model():
    return YOLO('best.pt')

@st.cache_resource     
def load_classification_model():
    base_model = VGG16(weights='imagenet')
    return Model(inputs=base_model.input, outputs=base_model.get_layer('fc1').output)

def getIndex():
    return faiss.read_index('faiss_index_apparel.index')

# Load models
yolomodel = load_model()
classificationmodel = load_classification_model()
index = getIndex()

def get_product_image(idx):
    """Retrieve product image based on FAISS index"""
    if idx in image_paths:
        try:
            img = Image.open(image_paths[idx])
            return img
        except FileNotFoundError:
            st.error(f"Image not found: {image_paths[idx]}")
            return None
    else:
        st.warning(f"No image mapping for index {idx}")
        return None

# Streamlit UI
st.title("Visual Search App")
st.write("Start your visual shopping")

# File uploader
uploaded_file = st.file_uploader("Upload your style", type=["jpg", "png", "jpeg"])

if uploaded_file:
    # Load and process image
    pil_image = Image.open(uploaded_file).convert("RGB")
    image_np = np.array(pil_image)
    
    # Detect objects
    results = yolomodel(image_np)
    
    if len(results[0].boxes.data) > 0:
        st.write(f"Found {len(results[0].boxes.data)} objects")
        
        for i, (*xyxy, conf, cls) in enumerate(results[0].boxes.data):
            x1, y1, x2, y2 = map(int, xyxy)
            
            # Crop and process detected object
            cropped_object = image_np[y1:y2, x1:x2]
            cropped_object = cv2.resize(cropped_object, (224, 224))
            cropped_object = image.img_to_array(cropped_object)
            cropped_object = np.expand_dims(cropped_object, axis=0)
            cropped_object = preprocess_input(cropped_object)

            # Generate embedding
            query_embedding = classificationmodel.predict(cropped_object)
            query_embedding = query_embedding.flatten().reshape(1, -1)
            k=2
            distances, indices = index.search(query_embedding, k=k)
            
            # Display results
            st.subheader(f"Object {i+1} (Confidence: {conf:.2f})")
            st.image(cv2.resize(image_np[y1:y2, x1:x2], (200, 200)), caption="Detected Object")
            
            st.write(f"Top {k} similar products:")
            
            # Create columns for display
            cols = st.columns(k)
            
            for col, idx, dist in zip(cols, indices[0], distances[0]):
                with col:
                    similar_img = get_product_image(idx)
                    if similar_img:
                        st.image(similar_img, 
                                width=200,
                                caption=f"Product ID: {idx}\nSimilarity: {1-dist:.2f}")
                    else:
                        st.warning(f"No image for index {idx}")
                
    else:
        st.write("Sorry, no relevant products found.")
