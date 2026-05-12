import tensorrt as trt
import os
import sys

# Paths
current_dir = os.path.dirname(os.path.abspath(__file__))
onnx_file = os.path.join(current_dir, "best.onnx")
engine_file = os.path.join(current_dir, "best.engine")

# Safety Check: Linux is case-sensitive!
if not os.path.exists(onnx_file):
    print(f"ERROR: {onnx_file} not found. Check your filename casing.")
    sys.exit(1)

logger = trt.Logger(trt.Logger.INFO)
builder = trt.Builder(logger)
network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
parser = trt.OnnxParser(network, logger)
config = builder.create_builder_config()

# Optimization settings
config.set_flag(trt.BuilderFlag.FP16)  # Use FP16 for speed
# With 64GB RAM, 2GB workspace is perfectly safe.
config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 2 << 30) 

print(f"Loading ONNX file: {onnx_file}")
with open(onnx_file, 'rb') as model:
    if not parser.parse(model.read()):
        for error in range(parser.num_errors):
            print(f"Parser Error: {parser.get_error(error)}")
        sys.exit(1)

print("Building Engine... (This may take 5-10 minutes on WSL)")
serialized_engine = builder.build_serialized_network(network, config)

if serialized_engine is None:
    print("ERROR: Engine build failed. Check CUDA drivers in WSL.")
    sys.exit(1)

with open(engine_file, 'wb') as f:
    f.write(serialized_engine)

print(f"SUCCESS! Your Linux engine is ready at: {engine_file}")