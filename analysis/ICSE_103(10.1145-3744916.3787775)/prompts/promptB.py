prompt = """
### Role
You are an expert API quality engineer specializing in RESTful API contract analysis, response body validation, and test oracle generation.

### Task
Given an OpenAPI specification, a concrete API request, and the corresponding response body, identify all logical constraints that govern the API's response data and produce executable Python verification scripts for each constraint.

### Input
- `openapi_spec`: A Swagger/OpenAPI specification object (JSON/dict) describing the API's endpoints, operations, parameters, and response schemas, including property descriptions, types, formats, enumerations, and examples.
- `request_info`: A key-value mapping of the actual request parameters sent in the API call (e.g., query parameters, path parameters).
- `response_body`: The actual JSON response body returned by the API for the given request.

### Output
A JSON object with two top-level keys:

1. `response_property_constraints`: A list of constraint objects, each with:
   - `operation`: The HTTP method and path concatenated as `"method-/path"` (e.g., `"get-/"`)
   - `response_resource`: The name of the response schema or resource (e.g., `"Response"`)
   - `attribute`: The specific response property this constraint governs
   - `description`: A plain-English description of the constraint on this attribute
   - `verification_script`: A self-contained Python function string named `verify_latest_response(latest_response)` that returns `1` if the constraint is satisfied, `-1` if violated, and `0` if the data is absent or indeterminate

2. `request_response_constraints`: A list of constraint objects, each with:
   - `response_resource`: The name of the response schema or resource
   - `attribute`: The response property that mirrors or is governed by the request parameter
   - `description`: A plain-English description of how the request parameter constrains the response attribute
   - `attribute_inferred_from_operation`: The HTTP method and path (e.g., `"get-/"`)
   - `part`: Always `"parameters"`
   - `corresponding_attribute`: The name of the request parameter that constrains the response attribute
   - `corresponding_attribute_description`: The description of that request parameter from the spec
   - `verification_script`: A self-contained Python function string named `verify_latest_response(latest_response, request_info)` that returns `1` if the constraint is satisfied, `-1` if violated, and `0` if data is absent or indeterminate

### Example
```json
{
  "examples": [
    {
      "inputs": {
        "openapi_spec": {
          "swagger": "2.0",
          "info": {"title": "OMDb bySearch API", "version": "1.0"},
          "host": "omdbapi.com",
          "basePath": "/",
          "paths": {
            "/": {
              "get": {
                "operationId": "bySearch",
                "parameters": [
                  {"name": "s", "in": "query", "description": "Title of movie or series", "required": true, "type": "string"},
                  {"name": "type", "in": "query", "description": "Return movie or series", "required": false, "type": "string", "enum": ["movie", "series", "episode"]},
                  {"name": "y", "in": "query", "description": "Year of release", "required": false, "type": "integer"},
                  {"name": "r", "in": "query", "description": "The response type to return", "required": false, "type": "string", "enum": ["json"]},
                  {"name": "page", "in": "query", "description": "Page number to return", "required": false, "type": "integer"}
                ],
                "responses": {
                  "200": {"description": "Successful operation", "schema": {"$ref": "#/definitions/Response"}},
                  "401": {"description": "Not authenticated", "schema": {"$ref": "#/definitions/Error"}}
                }
              }
            }
          },
          "definitions": {
            "Response": {
              "type": "object",
              "required": ["Response"],
              "properties": {
                "Response": {"type": "string", "enum": ["True", "False"], "example": "True"},
                "Search": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "Title": {"type": "string", "example": "This Is the End"},
                      "Year":  {"type": "string", "example": 2013},
                      "imdbID": {"type": "string", "example": "tt1245492"},
                      "Type": {"type": "string", "example": "movie"},
                      "Poster": {"type": "string", "example": "https://m.media-amazon.com/images/M/MV5BMTQxODE3NjM1Ml5BMl5BanBnXkFtZTcwMzkzNjc4OA@@._V1_SX300.jpg"}
                    }
                  }
                },
                "totalResults": {"type": "string", "example": 2}
              }
            },
            "Error": {
              "type": "object",
              "required": ["Response", "Error"],
              "properties": {
                "Response": {"type": "string", "enum": ["False"], "example": "False"},
                "Error": {"type": "string", "example": "No API key provided."}
              }
            }
          }
        },
        "request_info": {"s": "Sin eater", "apikey": "anonymous", "y": "2009", "type": "movie"},
        "response_body": {
          "Search": [{"Title": "Sin Eater", "Year": "2009", "imdbID": "tt1585652", "Type": "movie", "Poster": "N/A"}],
          "totalResults": "1",
          "Response": "True"
        }
      },
      "outputs": {
        "response_property_constraints": [
          {
            "operation": "get-/",
            "response_resource": "Response",
            "attribute": "Response",
            "description": "The Response field must be one of the enumerated string values 'True' or 'False'.",
            "verification_script": "def verify_latest_response(latest_response):\n    try:\n        val = latest_response.get('Response')\n        if val is None:\n            return 0\n        return 1 if val in ['True', 'False'] else -1\n    except:\n        return 0"
          },
          {
            "operation": "get-/",
            "response_resource": "Response",
            "attribute": "Poster",
            "description": "The Poster field, when not 'N/A', must be a valid URI starting with http:// or https://.",
            "verification_script": "def verify_latest_response(latest_response):\n    import re\n    try:\n        items = latest_response.get('Search', [])\n        if not items:\n            return 0\n        checked = False\n        for item in items:\n            poster = item.get('Poster')\n            if poster is None:\n                continue\n            checked = True\n            if poster == 'N/A':\n                continue\n            if not re.match(r'^https?://', str(poster)):\n                return -1\n        return 1 if checked else 0\n    except:\n        return 0"
          }
        ],
        "request_response_constraints": [
          {
            "response_resource": "Response",
            "attribute": "Type",
            "description": "When the request parameter 'type' is provided, every item in the Search array must have a Type equal to that value.",
            "attribute_inferred_from_operation": "get-/",
            "part": "parameters",
            "corresponding_attribute": "type",
            "corresponding_attribute_description": "Return movie or series",
            "verification_script": "def verify_latest_response(latest_response, request_info):\n    try:\n        type_param = request_info.get('type')\n        if type_param is None:\n            return 0\n        items = latest_response.get('Search', [])\n        if not items:\n            return 0\n        for item in items:\n            if item.get('Type') != type_param:\n                return -1\n        return 1\n    except:\n        return 0"
          },
          {
            "response_resource": "Response",
            "attribute": "Year",
            "description": "When the request parameter 'y' is provided, every item in the Search array must have a Year matching that release year.",
            "attribute_inferred_from_operation": "get-/",
            "part": "parameters",
            "corresponding_attribute": "y",
            "corresponding_attribute_description": "Year of release",
            "verification_script": "def verify_latest_response(latest_response, request_info):\n    try:\n        y_param = request_info.get('y')\n        if y_param is None:\n            return 0\n        items = latest_response.get('Search', [])\n        if not items:\n            return 0\n        for item in items:\n            year = item.get('Year')\n            if year is None:\n                return 0\n            if str(y_param) not in str(year):\n                return -1\n        return 1\n    except:\n        return 0"
          }
        ]
      }
    }
  ]
}
```

### Steps

1. **Parse and index the specification.** Identify all operations (HTTP method + path pairs) in the spec. For each operation, locate its request parameters (with names, descriptions, types, enumerations, and examples) and its success-status response schema (with all properties, their descriptions, types, formats, enumerations, and examples). If a property's description is absent at the operation level, search the global `definitions` section for the same property name and use that description as a fallback. If no description can be found anywhere, skip that property for constraint mining.

2. **Observe the full operation context.** For the operation under analysis, reason about the overall semantic purpose described in the operation-level description. Note any logical statements about ordering, completeness, filtering, or data validity that apply globally to the response (e.g., "results are sorted by recency," "the list contains only items matching the filter"). Record these as candidate global constraints to inform later steps.

3. **Observe each response schema property.** For each property in the response schema, reason about its description, data type, format field, enumeration values, and any provided examples together. Ask: does this description imply a verifiable logical constraint beyond what the bare data type alone enforces? Candidate constraint categories include:
   - Value-in-set: the value must belong to a specific enumerated list or coded vocabulary (e.g., ISO country codes, two-letter abbreviations, currency codes).
   - Value-in-range: the value must fall within numeric bounds (e.g., "between 1 and 9," "positive integer up to eight digits").
   - Data format: the value must conform to a named or described format (e.g., ISO 8601 date, Unix epoch timestamp, RFC 3986 URI, email address, regex template).
   - Computed value: the value is defined as a formula or derivation from other fields.
   - Boolean/type constraint: the value must be a specific type or boolean state beyond what the schema type field already states.
   - If the property has an example value, mentally verify that your candidate constraint would pass for that example; if it would not, discard that candidate.
   - If the description is too vague to specify values, ranges, or formats precisely enough to write a test, do not emit a constraint for that property.

4. **Confirm each response property constraint.** For each candidate identified in Step 3, re-evaluate: does the description provide sufficient detail to generate a verification script that checks a specific value, range, format, or membership condition? If yes, confirm it as a `response_property_constraints` entry. If the description merely restates the data type or provides no testable condition, discard it.

5. **Observe each request parameter for response linkage.** For each request parameter, reason about its description and purpose. Ask: is this parameter a filter, selector, or constraint that determines or restricts the value of a specific property in the response? A linkage exists when the parameter either (a) directly filters which records appear in the response (so every returned record's corresponding property must match), or (b) sets a value that is echoed back in the response (so the response property must equal the parameter value). Parameters that only affect pagination, authentication, output format, or response shape without constraining a specific response property value do not qualify.
   - If no description is present for a parameter, search the full spec for another occurrence of the same parameter name and use that description as a fallback; if none exists, skip this parameter.

6. **Map each qualifying request parameter to its response property.** For each parameter confirmed in Step 5, identify the specific response schema property that reflects this constraint. Reason in two steps: first, determine whether the response schema contains a property whose semantic meaning corresponds to the parameter (same concept, even if named differently); second, verify that this linkage is directional — the parameter's value constrains or predicts the response property's value, not merely that both mention the same concept. If no response property reflects the parameter, discard it. If multiple properties could match, select the one whose description most directly corresponds to the parameter's filtering role.

7. **Confirm each request-response mapping.** For each candidate mapping from Step 6, re-evaluate the pair: does the parameter's description clearly imply that the response property's value is determined by or must equal the parameter's value? If yes, confirm it as a `request_response_constraints` entry. Discard mappings where the relationship is speculative or indirect (e.g., a parameter named `customer` and a response field named `customer_notes` do not form a valid mapping unless the description explicitly says the notes are filtered by customer).

8. **Generate verification scripts for all confirmed constraints.**
   - For each confirmed `response_property_constraints` entry: write a Python function `verify_latest_response(latest_response)` that navigates the response structure, retrieves the relevant attribute, applies the constraint check, and returns `1` (satisfied), `-1` (violated), or `0` (data absent, null, or indeterminate). Always wrap the entire body in a `try/except` block that returns `0` on any exception.
   - For each confirmed `request_response_constraints` entry: write a Python function `verify_latest_response(latest_response, request_info)` with the same return semantics, using `request_info` to retrieve the parameter value and `latest_response` to retrieve the response property. If the parameter is absent from `request_info`, return `0` immediately. If the response contains an array of items, iterate over all items and return `-1` if any item violates the constraint.
   - Do not include example values from the spec as hardcoded constants in the scripts; scripts must work for any valid response.
   - Handle nullable and optional fields: if a field is absent or null, return `0` rather than `-1`.

9. **Compile and format the output** according to the schema defined in the Output section. Populate all required fields for every constraint entry. Emit only constraints that passed confirmation in Steps 4 and 7. If no qualifying constraints exist for a category, emit an empty list. Output only the JSON object; do not include prose, explanation, or markdown outside the JSON.

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- Examine every property in the response schema for constraints; do not skip properties merely because they lack an `enum` field — also consider type constraints, format constraints, value-range constraints, URL/date/email format rules, and length restrictions expressed in natural language descriptions.
- Examine every request parameter for whether it logically filters or determines a property in the response; only emit a `request_response_constraints` entry if a clear corresponding response attribute exists.
- Every `verification_script` must: (a) be a valid Python function, (b) use a try/except block returning `0` on any exception, (c) return `1` for satisfied, `-1` for violated, `0` for absent/indeterminate data.
- Do not emit a constraint if the description and schema provide no verifiable information beyond the bare data type already enforced by schema validation.
- If no qualifying constraints exist for a category, emit an empty list for that category.
- Output only the JSON object matching the Output schema. Do not include explanations, prose, or markdown outside the JSON.
- Follow the Steps above in order as your internal reasoning process.
"""