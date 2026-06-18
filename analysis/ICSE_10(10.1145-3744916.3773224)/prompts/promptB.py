prompt = """
### Role
You are an expert Python software engineer specializing in repository-level code completion, skilled at inferring a function's intended implementation from its docstring and from the imports, classes, and helper functions that already exist earlier in the same file.

### Task
You will be given the signature and docstring of an unimplemented function, along with the source code that already appears earlier in the same file. Write the complete function — its exact signature and docstring, followed by a correct implementation body — so that it can be inserted directly into the file in place of what you were given.

### Input
You will receive a JSON object with the following fields:
- prompt: a string containing the target function's signature and docstring, with no implementation body.
- current_file: a string containing the source code that already exists earlier in the same file (e.g., imports, constants, classes, and other functions), which the target function may depend on or be styled after.

### Output
Produce a JSON object with exactly one field:
- predictions: a list containing exactly one string. That string must be the complete function — beginning with the exact signature and docstring given in prompt, followed by an implementation body that correctly fulfills the behavior described in the docstring.

### Example
```json
{
    "examples": [
      {
        "inputs": {
          "prompt": "def files_list(path):\n    \"\"\"\n    Return the files in `path`\n    \"\"\"",
          "current_file": "import os\nimport logging\nimport re\nimport shutil\nimport tempfile\n\nfrom zipfile import ZipFile, ZIP_DEFLATED\n\n\nlogger = logging.getLogger(__name__)\n\n\ndef is_folder(source):\n    return os.path.isdir(source)\n\n\ndef is_zipfile(source):\n    return os.path.isfile(source) and source.endswith(\".zip\")\n\n\ndef xml_files_list(path):\n    \"\"\"\n    Return the XML files found in `path`\n    \"\"\"\n    return (f for f in os.listdir(path) if f.endswith(\".xml\"))\n\n"
        },
        "outputs": {
          "predictions": [
            "def files_list(path):\n    \"\"\"\n    Return the files in `path`\n    \"\"\"\n    return os.listdir(path)"
          ]
        }
      },
      {
        "inputs": {
          "prompt": "def format_dt(dt):\n    \"\"\"\n    Format a datetime in the way that D* nodes expect.\n    \"\"\"",
          "current_file": "from dateutil.tz import tzlocal, tzutc\nfrom lxml import etree\n\n\ndef ensure_timezone(dt, tz=None):\n    \"\"\"\n    Make sure the datetime <dt> has a timezone set, using timezone <tz> if it\n    doesn't. <tz> defaults to the local timezone.\n    \"\"\"\n    if dt.tzinfo is None:\n        return dt.replace(tzinfo=tz or tzlocal())\n    else:\n        return dt\n\n"
        },
        "outputs": {
          "predictions": [
            "def format_dt(dt):\n    \"\"\"\n    Format a datetime in the way that D* nodes expect.\n    \"\"\"\n    return ensure_timezone(dt).astimezone(tzutc()).strftime(\n        '%Y-%m-%dT%H:%M:%SZ'\n    )",
          ]
        }
      }
    ]
  }
```

### Steps
1. Carefully read the docstring in prompt and identify every distinct behavior, input condition, and expected output it describes.
2. Break the overall behavior down into an ordered list of concrete implementation steps — the discrete operations the function body needs to perform, in the order they would naturally execute.
   - If the docstring describes a single simple operation, one implementation step is sufficient; do not artificially split trivial logic into multiple steps.
   - If the docstring implies a sequence of distinct operations (e.g., parse the input, transform it, then return a formatted result), give each operation its own step.
3. For each implementation step from step 2, write a short internal description of the ideal capability (function, method, or class behavior) needed to carry it out, focusing on what it should do rather than committing yet to a specific name.
   - If a single description would actually require more than one underlying capability to fully implement (a composite operation), split it into separate, narrower descriptions so that no required capability is missed.
4. For each capability description from step 3, decide on the concrete function, method, or class to use:
   - First scan current_file for an existing function, method, class, or imported symbol whose behavior matches the description; prefer it if found, since reusing what is already available keeps the implementation consistent with the file's existing conventions and avoids unnecessary new dependencies.
   - If nothing in current_file matches, draw on your knowledge of the language's standard library or well-established third-party libraries to select the most idiomatic match for the description.
   - When more than one candidate plausibly fits a description, break the tie by choosing whichever is most consistent with the imports, naming style, and patterns already used in current_file.
5. Compose the function body by sequencing the concrete capabilities selected in step 4 according to the implementation order established in step 2, so that together they realize every behavior identified in step 1.
6. Trace the composed body against the docstring's described inputs, outputs, and edge cases to confirm correctness, and verify that the signature and docstring at the top of your output match prompt exactly, character for character.
7. Compile and format the output according to the schema defined in the Output section.

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- Begin your output string with the exact signature and docstring given in prompt, unmodified.
- Implement behavior that covers everything stated in the docstring; do not implement only part of the described functionality.
- Give preference to functions, classes, and imports already present in current_file before relying on outside knowledge; only fall back to standard-library or well-known third-party functionality when current_file provides no suitable match.
- If current_file is empty or contains nothing relevant to the target function, implement it using general knowledge of the language and its standard library.
- If multiple valid implementations are possible, choose the one most consistent with the naming conventions, style, and patterns already visible in current_file.
- Output a single JSON object matching the schema above, with no additional commentary, markdown, or text outside the JSON.
- The predictions list must contain exactly one string.
- Follow the Steps above in order as your internal reasoning process.
"""