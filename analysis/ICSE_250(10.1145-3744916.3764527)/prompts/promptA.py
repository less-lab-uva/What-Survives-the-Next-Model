prompt = """
### Role
You are an expert software engineer specializing in Python library development, API design, and behavioral correctness analysis of code changes.

### Task
Given a pull request (PR) with its associated metadata and code diff, generate a self-contained Python test case that exposes a behavioral difference between the original and modified code, predict the output of that test on both the original and the modified code, and classify whether the behavioral difference is intended or unintended by the PR's developer.

### Input
- `title`: A short string describing the purpose of the PR.
- `description`: A string (possibly empty) with a longer explanation of the PR's goals.
- `diff`: A unified diff string showing the exact code changes introduced by the PR.
- `commit_messages`: A list of strings, one per commit, describing incremental changes.
- `discussion_comments`: A list of strings representing reviewer or author comments on the PR.

### Output
Produce a JSON object with the following fields:
- `test_case`: A self-contained Python code snippet (string) that exercises the modified code and exposes the behavioral difference. The snippet must use only publicly exposed APIs of the project and must not depend on non-deterministic behavior such as random number generation.
- `predicted_output_before_pr`: A string representing the complete console output (stdout and any exception tracebacks) produced when the test is run against the original code. Use an empty string if there is no output or no exception.
- `predicted_output_after_pr`: A string representing the complete console output (stdout and any exception tracebacks) produced when the test is run against the modified code. Use an empty string if there is no output or no exception.
- `verdict`: Either `"intended"` or `"unintended"`. Use `"intended"` if the behavioral difference is consistent with the goals stated in the PR. Use `"unintended"` if the behavioral difference represents a regression or side effect not aligned with the PR's stated purpose.
- `explanation`: A string explaining why the behavioral difference is intended or unintended, grounded in the PR's title, description, and commit messages.

### Example
```json
{
  "examples": [
    {
      "inputs": {
        "title": "Minor refactor of get_func_args",
        "description": "",
        "diff": "diff --git a/src/marshmallow/utils.py b/src/marshmallow/utils.py\nindex aa7350f89..66a895f0a 100644\n--- a/src/marshmallow/utils.py\n+++ b/src/marshmallow/utils.py\n@@ -296,7 +296,7 @@ def get_func_args(func: typing.Callable) -> typing.List[str]:\n     if isinstance(func, functools.partial):\n         return _signature(func.func)\n     # Callable class\n-    return _signature(func.__call__)\n+    return _signature(func)\n",
        "commit_messages": ["Minor refactor of get_func_args"],
        "discussion_comments": []
      },
      "outputs": {
        "test_case": "from marshmallow.utils import get_func_args\n\nclass ExampleClass:\n    def __init__(self, attr1, attr2):\n        pass\n\nargs = get_func_args(ExampleClass)\nprint(args)",
        "predicted_output_before_pr": "['args', 'kwargs']",
        "predicted_output_after_pr": "['attr1', 'attr2']",
        "verdict": "intended",
        "explanation": "The PR refactors get_func_args to call _signature(func) directly instead of _signature(func.__call__). Although the output changes, returning the actual constructor argument names instead of generic wrapper args is a more correct behavior and a natural consequence of the refactor. The behavioral change aligns with the intent of simplifying the signature resolution."
      }
    },
    {
      "inputs": {
        "title": "ENH: fft: GPU support for non-standard basic transforms",
        "description": "Towards gh-19257. Following by example from CuPy, the functions which are not part of the array API standard extension for FFT are implemented to support non-numpy array backends.",
        "diff": "diff --git a/scipy/fft/_basic_backend.py b/scipy/fft/_basic_backend.py\nindex 777e69ac36c7..14b77661482d 100644\n--- a/scipy/fft/_basic_backend.py\n+++ b/scipy/fft/_basic_backend.py\n@@ -104,22 +106,12 @@ def ifftn(x, s=None, axes=None, norm=None):\n \n def hfftn(x, s=None, axes=None, norm=None, overwrite_x=False, workers=None):\n-    return _pocketfft.hfftn(x, s, axes, norm, overwrite_x, workers)\n+    xp = array_namespace(x)\n+    if is_complex(x, xp):\n+        return _pocketfft.hfftn(x, s, axes, norm, overwrite_x, workers)\n+    raise TypeError('hfftn requires complex input')\n",
        "commit_messages": [
          "ENH: fft: GPU support for non-standard basic transforms",
          "MAINT: fft: simplify basic calls and use pocketfft for hfftn with np arrays"
        ],
        "discussion_comments": [
          "This looks good overall. One concern: does wrapping with array_namespace break list inputs that previously worked?"
        ]
      },
      "outputs": {
        "test_case": "from scipy.fft import hfftn\n\nx = [[1, 2], [3, 4]]\nresult = hfftn(x)",
        "predicted_output_before_pr": "",
        "predicted_output_after_pr": "Traceback (most recent call last):\n  File \"test.py\", line 4, in <module>\n    result = hfftn(x)\nAttributeError: 'list' object has no attribute 'shape'",
        "verdict": "unintended",
        "explanation": "The PR adds GPU backend support for FFT functions but introduces a regression: hfftn previously accepted plain Python lists as input by implicitly converting them, but after the PR it fails with an AttributeError because array_namespace is called on the list before any conversion. The PR description makes no mention of dropping list input support, so this behavioral change is unintended."
      }
    }
  ]
}
```

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- The `test_case` must be self-contained Python code that uses only the publicly exposed API of the project and does not depend on non-deterministic behavior (e.g., random number generation, non-deterministically ordered sets).
- The `test_case` must include at least one `print` statement or trigger a traceback so that behavioral differences are visible in output.
- Do not invoke private functions (those prefixed with an underscore) in the `test_case`.
- `predicted_output_before_pr` and `predicted_output_after_pr` must reflect the complete console output, including full exception tracebacks if an exception is raised. Use an empty string only if there is genuinely no output.
- If both versions of the code would produce the same output, reconsider the test case — it must expose a difference.
- For `verdict`, use `"intended"` if the behavioral difference is directly explained or implied by the PR's title, description, or commit messages; use `"unintended"` if it represents an unexpected side effect, regression, or breakage not mentioned in the PR.
- The `explanation` must reference specific details from the PR's natural language artifacts (title, description, commit messages, or discussion comments) to justify the verdict.
- Output only a single valid JSON object matching the schema above. Do not include any text outside the JSON.
"""
