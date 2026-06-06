import os
import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

def package():
    export_dir = PROJECT_ROOT / "storage" / "combined_package"
    export_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Copy the script files
    script_srcs = [
        PROJECT_ROOT / "tools" / "generate_synthetic_device_data.py",
        PROJECT_ROOT / "tools" / "convert_google_android_control.py"
    ]
    
    for src in script_srcs:
        if src.exists():
            shutil.copy(src, export_dir / src.name)
            print(f"Copied script to export package: {export_dir / src.name}")
            
    # 2. Load and merge datasets
    examples = []
    
    device_data_path = PROJECT_ROOT / "storage" / "synthetic_training_data.jsonl"
    google_data_path = PROJECT_ROOT / "storage" / "google_converted_data.jsonl"
    
    for path in [device_data_path, google_data_path]:
        if path.exists():
            count = 0
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        examples.append(json.loads(line))
                        count += 1
            print(f"Loaded {count} examples from {path.name}")
            
    # Deduplicate examples
    seen_hashes = set()
    deduped_examples = []
    for ex in examples:
        # Create a hashable representation of the messages
        h = json.dumps(ex["messages"], sort_keys=True)
        if h not in seen_hashes:
            seen_hashes.add(h)
            deduped_examples.append(ex)
            
    print(f"Total merged and deduplicated examples: {len(deduped_examples)}")
    
    # Save the combined dataset
    out_file = export_dir / "combined_training_data.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for ex in deduped_examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
            
    print(f"Saved combined training samples to: {out_file}")
    print(f"\n--- SUCCESS ---")
    print(f"The export package is located at: {export_dir}")
    print(f"Files inside the package:")
    for f in export_dir.iterdir():
        print(f"  - {f.name} ({f.stat().st_size} bytes)")

if __name__ == "__main__":
    package()
