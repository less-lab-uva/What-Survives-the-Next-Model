import os
import sys
import re
import base64
import anthropic

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not found. Run 'source ~/.bashrc' first.")

client = anthropic.Anthropic(api_key=api_key)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_meta_prompt():
    path = os.path.join(BASE_DIR, "prompts", "meta_prompt.txt")
    with open(path, "r") as f:
        return f.read()


def load_pdf_base64(pdf_path):
    with open(pdf_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def strip_outer_fence(section: str) -> str:
    section = re.sub(r"^##[^\n]*\n", "", section.strip()).strip()
    section = re.sub(r"^```[a-z]*\n", "", section)
    if section.endswith("```"):
        section = section[:-3].rstrip("\n")
    return section.strip()


def extract_prompts(response_text):
    prompt_a = ""
    prompt_b = ""

    if "## PROMPT B" in response_text:
        a_raw, b_raw = response_text.split("## PROMPT B", 1)
        b_raw = "## PROMPT B" + b_raw
    else:
        a_raw = response_text
        b_raw = ""

    if "## PROMPT A" in a_raw:
        a_section = a_raw[a_raw.index("## PROMPT A"):]
        a_section = re.sub(r"\s*---\s*$", "", a_section)
        prompt_a = strip_outer_fence(a_section)

    if b_raw:
        prompt_b = strip_outer_fence(b_raw)

    return prompt_a, prompt_b


def main():
    if len(sys.argv) != 2:
        print("Usage: python prompt_generator.py <path_to_paper.pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    meta_prompt = load_meta_prompt()
    pdf_b64 = load_pdf_base64(pdf_path)

    print(f"Loaded meta prompt and PDF: {pdf_path}")
    print("Sending to Claude to generate Prompt A and Prompt B...")

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=64000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64
                        }
                    },
                    {
                        "type": "text",
                        "text": meta_prompt
                    }
                ]
            }
        ]
    ) as stream:
        raw_output = stream.get_final_text()
        final_msg = stream.get_final_message()

    print(f"Tokens: {final_msg.usage.input_tokens} in / {final_msg.usage.output_tokens} out")

    prompt_a, prompt_b = extract_prompts(raw_output)

    os.makedirs(os.path.join(BASE_DIR, "prompts"), exist_ok=True)

    if prompt_a:
        out_a = os.path.join(BASE_DIR, "prompts", "prompt_A.txt")
        with open(out_a, "w") as f:
            f.write(prompt_a)
        print(f"Prompt A saved to {out_a}")
    else:
        print("WARNING: Could not extract Prompt A from response.")

    if prompt_b:
        out_b = os.path.join(BASE_DIR, "prompts", "prompt_B.txt")
        with open(out_b, "w") as f:
            f.write(prompt_b)
        print(f"Prompt B saved to {out_b}")
    else:
        print("WARNING: Could not extract Prompt B from response.")

    raw_path = os.path.join(BASE_DIR, "prompts", "raw_output.txt")
    with open(raw_path, "w") as f:
        f.write(raw_output)
    print(f"Raw response saved to {raw_path}")


if __name__ == "__main__":
    main()
