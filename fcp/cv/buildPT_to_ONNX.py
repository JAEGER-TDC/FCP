import os
from ultralytics import YOLO

current_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(current_dir, "best.pt")

model = YOLO(model_path)
print("Converting to ONNX on CPU...")

# This avoids the Blackwell/PyTorch conflict entirely
model.export(format="onnx", imgsz=320, half=False, device='cpu') 

print("Step 1 Complete: You should now see 'best.onnx' in your folder.")