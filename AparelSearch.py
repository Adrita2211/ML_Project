import streamlit as st

import numpy as np
import joblib
from ultralytics import YOLO
import cv2
import numpy as np
import faiss
import os
from keras.applications.vgg16 import VGG16, preprocess_input
from keras.preprocessing import image
from keras.models import Model
from google.colab.patches import cv2_imshow
from google.colab import drive
import os
from PIL import Image

object_embeddings = []
object_classes = []
similar_images_indices = []
# Load a pre-trained YOLOv5 model
@st.cache_resource
def load_model():
     return YOLO('best.pt')
@st.cache_resource     
def load_classification_model():
     base_model = VGG16(weights='imagenet')
     return Model(inputs=base_model.input, outputs=base_model.get_layer('fc1').output)
     
def getIndex():
    return  faiss.read_index('faiss_index_apparel.index')
    
def search_similar_images(index, query_embedding, top_k=1):
    D, I = index.search(query_embedding, top_k)
    return I
    
# Call search_similar_images for each query embedding in the array
for query_embedding in embeddings:
    # Reshape the query embedding if necessary (e.g., for FAISS, it expects 2D array)
    query_embedding = query_embedding.reshape(1, -1)
    I = search_similar_images(index, query_embedding, top_k=1)
    similar_images_indices.append(I)  # Append I to the list

yolomodel = load_model()
classificationmodel = load_classification_model()


# Streamlit UI
st.title("Visual Search App")
st.write("Start your visual shopping")

# File uploader
uploaded_file = st.file_uploader("Upload your style", type=["jpg", "png", "jpeg"])

if uploaded_file:
    image = Image.open(uploaded_file).convert("RGB")
    image_np = np.array(image)
    # Perform object detection using the YOLO model
    results = yolomodel(image_np)
    original_image = image
    if results[0].boxes.data.shape[0] > 0:  # Check if there are any detected bounding boxes
       for *xyxy, conf, cls in results[0].boxes.data: # Access bounding box data correctly
        x1, y1, x2, y2 = map(int, xyxy)
        cropped_object = original_image[y1:y2, x1:x2]

        # Preprocess for VGG16
        cropped_object = cv2.resize(cropped_object, (224, 224))
        cropped_object = image.img_to_array(cropped_object)
        cropped_object = np.expand_dims(cropped_object, axis=0)
        cropped_object = preprocess_input(cropped_object)

        # Generate embedding
        object_embedding = classificationmodel.predict(cropped_object)
        object_embedding = object_embedding.flatten()
        object_embeddings.append(object_embedding)
    else:
        st.write("Sorry no relevant products found.")
     for query_embedding in object_embeddings:
       query_embedding = query_embedding.reshape(1, -1)
       similar_image_indices = search_similar_images(index, query_embedding, top_k=2) # Example: top_k=5 for 5 most similar
       for idx in similar_image_indices.flatten():
           print(image_paths[idx]) # Prints paths of similar images
           similar_image=cv2.imread(image_paths[idx])
           st.image(annotated_image)
           #cv2_imshow(similar_image)
           #annotated_image = results[0].plot()
           # st.image(annotated_image, caption="Processed Image with Detections")
            #st.write(results)
            # Show detected objects with confidence scores
            #st.write("### 📌 Detected Objects:")
            #st.dataframe(results.pandas().xyxy[0][['name', 'confidence']])  # O
