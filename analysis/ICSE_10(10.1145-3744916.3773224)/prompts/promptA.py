prompt = """
### Role
You are an expert Python software engineer specializing in repository-level function completion, with deep knowledge of Python standard libraries, common third-party packages, and idiomatic coding patterns.

### Task
You receive a Python function's signature and docstring alongside the full content of the source file in which that function resides. Your task is to produce five distinct, functionally correct Python implementations of the target function.

### Input
- `prompt` (string): The target function's signature and docstring, exactly as it appears in the source file, defining the function you must implement.
- `current_file` (string): The full content of the source file in which the target function resides, including all import statements, class definitions, module-level constants, and other function implementations that appear before the target function.

### Output
A JSON object with a single field:
- `predictions`: A list of exactly 5 strings. Each string is a complete, syntactically valid Python implementation of the target function, including the original function signature and docstring. All 5 implementations must be functionally equivalent — each correctly realising the behaviour described in the docstring — while differing from one another in structure, variable naming, or coding style.

### Example

{
    "examples": [
      {
        "inputs": {
          "prompt": "def files_list(path):\n    \"\"\"\n    Return the files in `path`\n    \"\"\"",
          "current_file": "import os\nimport logging\nimport re\nimport shutil\nimport tempfile\n\nfrom zipfile import ZipFile, ZIP_DEFLATED\n\n\nlogger = logging.getLogger(__name__)\n\n\ndef is_folder(source):\n    return os.path.isdir(source)\n\n\ndef is_zipfile(source):\n    return os.path.isfile(source) and source.endswith(\".zip\")\n\n\ndef xml_files_list(path):\n    \"\"\"\n    Return the XML files found in `path`\n    \"\"\"\n    return (f for f in os.listdir(path) if f.endswith(\".xml\"))\n\n"
        },
        "outputs": {
          "predictions": [
            "def files_list(path):\n    \"\"\"\n    Return the files in `path`\n    \"\"\"\n    return os.listdir(path)",
            "def files_list(path):\n    \"\"\"\n    Return the files in `path`\n    \"\"\"\n    return list(os.listdir(path))",
            "def files_list(path):\n    \"\"\"\n    Return the files in `path`\n    \"\"\"\n    return [f for f in os.listdir(path)]",
            "def files_list(path):\n    \"\"\"\n    Return the files in `path`\n    \"\"\"\n    files = os.listdir(path)\n    return files",
            "def files_list(path):\n    \"\"\"\n    Return the files in `path`\n    \"\"\"\n    return sorted(os.listdir(path))"
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
            "def format_dt(dt):\n    \"\"\"\n    Format a datetime in the way that D* nodes expect.\n    \"\"\"\n    dt_with_tz = ensure_timezone(dt)\n    return dt_with_tz.astimezone(tzutc()).strftime('%Y-%m-%dT%H:%M:%SZ')",
            "def format_dt(dt):\n    \"\"\"\n    Format a datetime in the way that D* nodes expect.\n    \"\"\"\n    utc_dt = ensure_timezone(dt).astimezone(tzutc())\n    return utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')",
            "def format_dt(dt):\n    \"\"\"\n    Format a datetime in the way that D* nodes expect.\n    \"\"\"\n    return ensure_timezone(dt).astimezone(tzutc()).strftime('%Y-%m-%dT%H:%M:%SZ')",
            "def format_dt(dt):\n    \"\"\"\n    Format a datetime in the way that D* nodes expect.\n    \"\"\"\n    aware_dt = ensure_timezone(dt)\n    utc_dt = aware_dt.astimezone(tzutc())\n    return utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')"
          ]
        }
      }
    ]
  }

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- Produce exactly 5 predictions in the `predictions` list — no more, no fewer.
- Each prediction must be a complete Python implementation of the target function, beginning with the exact function signature and docstring from `prompt`, followed by the function body.
- Every prediction must be functionally correct: its behaviour must satisfy the specification given in the docstring.
- Use only names, functions, classes, and imports that are present in `current_file` or in Python's standard library. Do not introduce functions, modules, or identifiers that are absent from both.
- All 5 predictions must be distinct from one another; differentiate them through at least one of: direct return vs. intermediate variable, list comprehension vs. generator expression vs. explicit loop, sorted vs. unsorted result, chained call vs. step-by-step assignment, or use of an equivalent alternative API.
- If `current_file` is empty or provides no relevant symbols, rely solely on Python's standard library.
- Output must be a single valid JSON object matching the schema shown in the Example section above.
"""