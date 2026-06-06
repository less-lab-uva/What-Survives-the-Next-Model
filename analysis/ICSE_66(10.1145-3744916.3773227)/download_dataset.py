from huggingface_hub import hf_hub_download
import os
from pathlib import Path

repo_id = "NTU-NLP-sg/xCodeEval"
BASE_DIR = Path(__file__).resolve().parent
save_dir = str(BASE_DIR / "xCodeEval")

languages = ["C", "C#", "C++", "Go", "Java", "Javascript",
             "Kotlin", "PHP", "Python", "Ruby", "Rust"]

os.makedirs(f"{save_dir}/apr/validation", exist_ok=True)       

for lang in languages:
    print(f"Downloading validation/{lang}.jsonl ...")              
    path = hf_hub_download(
        repo_id=repo_id,
        filename=f"apr/validation/{lang}.jsonl",                   
        repo_type="dataset",
        local_dir=save_dir
    )
    print(f"  Saved to {path}")


print("\nDownloading problem_descriptions.jsonl ...")
path = hf_hub_download(
    repo_id=repo_id,
    filename="problem_descriptions.jsonl",
    repo_type="dataset",
    local_dir=save_dir
)
print(f"  Saved to {path}")


print("\nDownloading unittest_db.json ...")
path = hf_hub_download(
    repo_id=repo_id,
    filename="unittest_db.json",
    repo_type="dataset",
    local_dir=save_dir
)
print(f"  Saved to {path}")

print("\nAll done. Files saved to:", save_dir)
