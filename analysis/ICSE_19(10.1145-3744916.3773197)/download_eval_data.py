from datasets import load_dataset
from huggingface_hub import snapshot_download
from pathlib import Path

HERE     = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

print("Downloading HumanEval...")
load_dataset("openai/openai_humaneval", split="test",
             cache_dir=str(DATA_DIR / "hf_cache"))

print("Downloading LiveCodeBench...")
snapshot_download(
    repo_id="livecodebench/code_generation_lite",
    repo_type="dataset",
    local_dir=str(DATA_DIR / "lcb"),
)

print("\nAll done. Data saved to:", DATA_DIR)
