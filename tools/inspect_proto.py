import sys
from android_env.proto.a11y import android_accessibility_forest_pb2

print("AndroidAccessibilityForest fields:")
forest = android_accessibility_forest_pb2.AndroidAccessibilityForest()
for field in forest.DESCRIPTOR.fields:
    print(f"  {field.name} ({field.type})")

print("\nAndroidAccessibilityNode fields:")
# Find the node message type
for name, desc in android_accessibility_forest_pb2.__dict__.items():
    if "Node" in name and hasattr(desc, "DESCRIPTOR"):
        print(f"Descriptor for {name}:")
        for field in desc.DESCRIPTOR.fields:
            print(f"  {field.name} ({field.type})")
