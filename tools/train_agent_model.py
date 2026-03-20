"""
train_agent_model.py
====================
Fine-tunes a small base model (Llama-3.2-3B / Phi-3.5) using QLoRA + Unsloth
on the agent's JSONL training data.

Hardware target: RTX 3050 4 GB VRAM + 16 GB RAM

Install deps first:
  pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
  pip install --no-deps trl peft accelerate bitsandbytes
"""

import json
from pathlib import Path

# ── 1. Config ─────────────────────────────────────────────────────────────────
BASE_MODEL   = "unsloth/Phi-3.5-mini-instruct"   # 3.8B, great instruction-following
# Alternative: "unsloth/Llama-3.2-3B-Instruct"
MAX_SEQ_LEN  = 2048          # Most UI dumps fit in 1024 tokens
LORA_RANK    = 16            # LoRA rank — higher = more capacity
BATCH_SIZE   = 1             # Must be 1 for 4 GB VRAM
GRAD_ACCUM   = 8             # Effective batch = 8
EPOCHS       = 3
LEARNING_RATE = 2e-4
OUTPUT_DIR   = "storage/finetuned_model"
DATA_PATH    = "storage/training_data.jsonl"

# ── 2. Load model ──────────────────────────────────────────────────────────────
from unsloth import FastLanguageModel
import torch

print("Loading base model with 4-bit quantization...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name     = BASE_MODEL,
    max_seq_length = MAX_SEQ_LEN,
    dtype          = None,        # auto-detect (float16 for RTX 3050)
    load_in_4bit   = True,        # 4-bit quantization — fits in 4 GB VRAM
)

# ── 3. Add LoRA adapters ───────────────────────────────────────────────────────
model = FastLanguageModel.get_peft_model(
    model,
    r              = LORA_RANK,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"],
    lora_alpha     = 16,
    lora_dropout   = 0,
    bias           = "none",
    use_gradient_checkpointing = "unsloth",  # saves VRAM
    random_state   = 42,
)
print(f"Trainable parameters: {model.num_parameters(only_trainable=True):,}")

# ── 4. Load dataset ────────────────────────────────────────────────────────────
from datasets import Dataset

records = []
with open(DATA_PATH, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

print(f"Loaded {len(records)} training examples")

# Format to the chat template the model expects
def format_example(example):
    messages = example["messages"]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}

raw_dataset = Dataset.from_list(records)
dataset     = raw_dataset.map(format_example)
print("Sample formatted input (first 500 chars):")
print(dataset[0]["text"][:500])

# ── 5. Train ───────────────────────────────────────────────────────────────────
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model        = model,
    tokenizer    = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length    = MAX_SEQ_LEN,
    dataset_num_proc  = 2,
    packing           = True,      # Pack multiple short examples per window
    args = TrainingArguments(
        per_device_train_batch_size  = BATCH_SIZE,
        gradient_accumulation_steps  = GRAD_ACCUM,
        warmup_steps                 = 10,
        num_train_epochs             = EPOCHS,
        learning_rate                = LEARNING_RATE,
        fp16                         = not torch.cuda.is_bf16_supported(),
        bf16                         = torch.cuda.is_bf16_supported(),
        logging_steps                = 5,
        optim                        = "adamw_8bit",
        weight_decay                 = 0.01,
        lr_scheduler_type            = "linear",
        seed                         = 42,
        output_dir                   = OUTPUT_DIR,
        report_to                    = "none",
    ),
)

print("\nStarting training...")
trainer_stats = trainer.train()
print(f"\nTraining complete! Loss: {trainer_stats.training_loss:.4f}")

# ── 6. Save as GGUF (for Ollama) ───────────────────────────────────────────────
print("\nExporting to GGUF (Q4_K_M quantization) for Ollama...")
model.save_pretrained_gguf(
    OUTPUT_DIR + "/gguf",
    tokenizer,
    quantization_method = "q4_k_m",  # Best quality/size tradeoff
)
print(f"GGUF saved to {OUTPUT_DIR}/gguf/")
print("\nTo use with Ollama:")
print(f"  ollama create mobile-agent -f {OUTPUT_DIR}/gguf/Modelfile")
print("  ollama run mobile-agent")
print("\nDone!")
