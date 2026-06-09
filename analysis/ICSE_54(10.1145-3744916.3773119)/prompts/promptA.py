prompt = """
### Role
You are an expert Java software engineer specializing in program analysis, type inference, and code completion for incomplete or partial code snippets.

### Task
You receive a partial Java code snippet that is syntactically incomplete — it may be missing variable declarations, import statements, class or method wrappers, and type information. Your task is to produce a fully compilable, approximately-complete Java program that wraps and preserves the original snippet without modifying it, along with a list of resolved type annotations for all variables used in the snippet.

### Input
- `partial_code`: A string containing a partial Java code snippet. It may reference undeclared variables, unresolved types, missing imports, and absent method or class enclosures. This is the raw snippet exactly as provided — no preprocessing has been applied.

### Output
Produce a JSON object with exactly the following two fields:

- `approximated_code`: A string containing a complete, compilable Java program. It must include all necessary import statements, a class declaration, and a method signature that wraps the original partial code. The original code body must appear verbatim and unmodified inside the method. The added context should resolve all unknown identifiers by supplying plausible variable declarations, import statements, method parameters, and class scaffolding.
- `type_information`: A JSON array of strings. Each string maps one variable name from the partial code to its fully-qualified Java type, using the format `"variableName => fully.qualified.TypeName;"`. Include every variable that appears in the partial code whose type can be inferred or reasonably approximated. Do not include variables introduced solely by the added scaffolding unless they directly appear in the original snippet.

### Example
```json
{
  "examples": [
    {
      "inputs": {
        "partial_code": "\t\tDateTime d2 = new DateTime();\n\t\tlong diffInMillis = d2.getMillis() - d1.getMillis();\n"
      },
      "outputs": {
        "approximated_code": "\nimport org.joda.time.DateTime;\npublic class MyClass {\n    void someMethod() {\n        DateTime d1 = new DateTime();\n\t\tDateTime d2 = new DateTime();\n\t\tlong diffInMillis = d2.getMillis() - d1.getMillis();\n    }\n}\n",
        "type_information": [
          "d1 => org.joda.time.DateTime;",
          "d2 => org.joda.time.DateTime;"
        ]
      }
    }
  ]
}
```

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- Do not modify any part of the original `partial_code` — it must appear verbatim inside the output `approximated_code`.
- The `approximated_code` must be a syntactically and semantically complete Java compilation unit: it must include at least one import block (if needed), one class declaration, and one method that contains the original snippet.
- Use the most plausible, standard Java library types when resolving unknown identifiers. If a type comes from a well-known third-party library (e.g., Joda-Time, Apache Commons, Android SDK), use its fully-qualified name.
- Every variable referenced in the original `partial_code` that lacks a declaration must be declared in the added scaffolding (as a method parameter, local variable, or field).
- In `type_information`, include only variables that appear in the original `partial_code`. Use the exact format `"variableName => fully.qualified.TypeName;"` for every entry.
- Do not include explanations, comments, or any text outside the JSON output.
- Output must be a single valid JSON object matching the schema shown in the Output section.
"""