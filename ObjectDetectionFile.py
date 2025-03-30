import streamlit as st

import numpy as np
import joblib
from ultralytics import YOLO
from PIL import Image
import matplotlib.pyplot as plt
# Load a pre-trained YOLOv5 model
@st.cache_resource
def load_model():
     return YOLO('best.pt')

model = load_model()

# Streamlit UI
st.title("Image Object Detection App")
st.write("Upload an image to detect objects.")

# File uploader
uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "png", "jpeg"])

if uploaded_file:
    # Convert the uploaded file to a NumPy array
    image = Image.open(uploaded_file)
    #image_np = np.array(image)

    # Perform object detection using the YOLO model
    #results = model(image_np)

    # Convert results to a format that can be displayed
    #result_img = np.squeeze(results.render())
    #result_img = results[0].plot()
    res = model.predict(image)
    boxes = res[0].boxes
    res_plotted = res[0].plot()[:, :, ::-1]
    st.image(res_plotted, caption='Detected Image',
                         use_column_width=True)
   
    # Display the detected image
    #st.image(result_img, caption="Detected Objects", use_column_width=True)

    # Show detected objects with confidence scores
    st.write("### 📌 Detected Objects:")
    #st.dataframe(results.pandas().xyxy[0][['name', 'confidence']])  # O
    try:
        with st.expander("Detection Results"):
             for box in boxes:
                 st.write(box.data)
     
    except Exception as ex:
                    # st.write(ex)
          st.write("No image is uploaded yet!")
