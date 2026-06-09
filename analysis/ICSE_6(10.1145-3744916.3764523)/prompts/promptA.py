prompt = """
### Role
You are an expert software reliability engineer specializing in log analysis and structured template extraction for large-scale distributed systems.

### Task
You receive a single raw runtime log message produced by a software system and must produce its corresponding log template — the static structural pattern of the message with all dynamic, runtime-specific values replaced by a wildcard token.

### Input
- `log_message`: A string containing a single raw log entry produced at runtime by a software system. It may contain a mix of static text (keywords, punctuation, fixed phrases) and dynamic values (numbers, IP addresses, file paths, timestamps, identifiers, status codes, or other variable content).

### Output
A JSON object with a single field:
- `log_template`: A string representing the structural template of the log message. All dynamic, runtime-specific values must be replaced with the token `<*>`. Static words, keywords, operators, and fixed structural tokens must be preserved exactly as they appear. Whitespace normalization (collapsing multiple spaces to one) is acceptable. The output must be valid JSON.

### Example
```json
{
  "examples": [
    {
      "inputs": {
        "log_message": "normal"
      },
      "outputs": {
        "log_template": "normal"
      }
    },
    {
      "inputs": {
        "log_message": "ambient=30"
      },
      "outputs": {
        "log_template": "ambient=<*>"
      }
    },
    {
      "inputs": {
        "log_message": "boot  (command 1911)"
      },
      "outputs": {
        "log_template": "boot (command <*>)"
      }
    }
  ]
}
```

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- Replace every runtime-variable token (numbers, IP addresses, file paths, hex values, UUIDs, version strings, usernames, hostnames, timestamps, status codes, and other system-specific identifiers) with exactly `<*>`.
- Preserve all static keywords, operators, punctuation, and fixed structural words verbatim.
- If the entire log message is a single static word or phrase with no dynamic components, return it unchanged as the template.
- Do not merge or split tokens beyond whitespace normalization; replace each dynamic token individually with `<*>`.
- When consecutive dynamic tokens appear, replace each one separately with its own `<*>`.
- Output only the JSON object. Do not include explanation, commentary, or any text outside the JSON.
"""