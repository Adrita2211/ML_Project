import streamlit as st
import numpy as np
import joblib
from ultralytics import YOLO
import cv2
import faiss
import os
from keras.applications.vgg16 import VGG16, preprocess_input
from keras.preprocessing import image
from keras.models import Model
from PIL import Image

object_embeddings = []
object_classes = []
similar_images_indices = []

# Load models
@st.cache_resource
def load_model():
    return YOLO('best.pt')

@st.cache_resource     
def load_classification_model():
    base_model = VGG16(weights='imagenet')
    return Model(inputs=base_model.input, outputs=base_model.get_layer('fc1').output)
    
def getIndex():
    return faiss.read_index('faiss_index_apparel.index')
    
def search_similar_images(index, query_embedding, top_k=1):
    D, I = index.search(query_embedding, top_k)
    return I
     
yolomodel = load_model()
classificationmodel = load_classification_model()
index = getIndex()  # You need to load your FAISS index
image_paths = [...]  # You need to define your image paths list

# Streamlit UI
st.title("Visual Search App")
st.write("Start your visual shopping")

# File uploader
uploaded_file = st.file_uploader("Upload your style", type=["jpg", "png", "jpeg"])

if uploaded_file:
    pil_image = Image.open(uploaded_file).convert("RGB")
    image_np = np.array(pil_image)
    
    # Perform object detection
    results = yolomodel(image_np)
    
    if len(results[0].boxes.data) > 0:
        for *xyxy, conf, cls in results[0].boxes.data:
            x1, y1, x2, y2 = map(int, xyxy)
            
            # Convert PIL Image to numpy array before cropping
            image_np = np.array(pil_image)
            cropped_object = image_np[y1:y2, x1:x2]
            
            # Preprocess for VGG16
            cropped_object = cv2.resize(cropped_object, (224, 224))
            cropped_object = image.img_to_array(cropped_object)
            cropped_object = np.expand_dims(cropped_object, axis=0)
            cropped_object = preprocess_input(cropped_object)

            # Generate embedding
            object_embedding = classificationmodel.predict(cropped_object)
            object_embedding = object_embedding.flatten()
            object_embeddings.append(object_embedding)
            
        for query_embedding in object_embeddings:
            query_embedding = query_embedding.reshape(1, -1)
            similar_image_indices = search_similar_images(index, query_embedding, top_k=2)
            
            for idx in similar_image_indices.flatten():
                if idx < len(image_paths):  # Safety check
                    similar_image = Image.open(image_paths[idx])
                    st.image(similar_image, caption=f"Similar product {idx+1}")
    else:
        st.write("Sorry, no relevant products found.")
