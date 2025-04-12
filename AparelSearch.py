import streamlit as st
import numpy as np
from ultralytics import YOLO
import cv2
import faiss
from keras.applications.vgg16 import VGG16, preprocess_input
from keras.preprocessing import image
from keras.models import Model
from PIL import Image

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
            
            # Search similar images
            distances, indices = index.search(query_embedding, k=3)  # Get top 3 matches
            
            # Display results
            st.subheader(f"Object {i+1} (Confidence: {conf:.2f})")
            
            # Show the cropped query object
            st.image(cv2.resize(image_np[y1:y2, x1:x2], caption="Detected object", width=200)
            
            # Display similar images (you'll need a way to map indices to actual images)
            st.write("Similar products:")
            
            # Here you need to implement your logic to get actual images from the indices
            # This is just a placeholder - you'll need to replace with your actual image retrieval logic
            for idx in indices[0]:
                # This assumes you have a way to get the image from the index
                # For example, if you have a list of image paths ordered the same as your index:
                # similar_img = Image.open(image_paths[idx])
                # st.image(similar_img, width=200)
                st.write(f"Match {idx} (Distance: {distances[0][idx]:.2f})")
                # In a real implementation, you would display the actual image here
                
    else:
        st.write("Sorry, no relevant products found.")
