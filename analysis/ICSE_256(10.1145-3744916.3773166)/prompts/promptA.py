prompt = """
### Role
You are an expert software security engineer specializing in Solidity smart contract vulnerability analysis and automated fuzz test generation for Ethereum blockchain programs.

### Task
You receive the complete source code of a Solidity smart contract together with two fuzzing configuration parameters — a session duration in seconds and a number of queue cycles — and must produce a complete fuzzing result report that identifies every vulnerability present in the contract, generates concrete transaction sequences that trigger each one, and reports realistic execution statistics for the described fuzzing session.

### Input
- `source_code` (string): The complete Solidity source code of the smart contract under analysis.
- `duration` (integer): Total duration of the fuzzing session in seconds.
- `rounds` (integer): Number of fuzzing queue cycles to complete.

### Output
A single JSON object with the following fields:

- `totalExecs` (integer): Total number of contract executions performed. Must equal `round(speed × duration)`.
- `speed` (float): Average execution throughput in executions per second.
- `queueCycles` (integer): Number of queue cycles completed. Must exactly equal the `rounds` input value.
- `uniqExceptions` (integer): Count of distinct vulnerability types detected; equals the number of vulnerability types whose `number` field is greater than 0.
- `coverage` (float): Proportion of the contract's branches exercised, in the range [0.0, 1.0].
- `vulnerabilities` (object): Exactly six fixed keys — `"unchecked call"`, `"reentrancy"`, `"timestamp dependency"`, `"block number dependency"`, `"integer overflow"`, `"integer underflow"` — each mapping to an object with:
  - `number` (integer): Count of vulnerability instances found. Use `0` if none detected.
  - `instruction distinction` (string): Short alphanumeric identifier for the triggering instruction location (e.g., `"1a3"`). Use `""` if `number` is `0`.
  - `test cases` (array): Ordered list of test case objects that trigger the vulnerability. Use `[]` if `number` is `0`. Each test case object contains:
    - `functions` (array): Ordered sequence of function calls comprising the triggering transaction sequence. Each element has:
      - `name` (string): Exact function name as declared in the contract.
      - `inputs` (array): List of arguments, each with:
        - `type` (string): Solidity parameter type (e.g., `"uint256"`, `"address"`).
        - `value` (string): Hex-encoded argument value prefixed with `"0x"` (e.g., `"0x2"`).
    - `accounts` (array): Ethereum accounts involved in the test. Each has:
      - `address` (string): 40-hex-digit Ethereum address prefixed with `"0x"`.
      - `balance` (integer): Account balance in wei (non-negative integer).

### Example

```json
{
  "examples": [
    {
      "inputs": {
        "source_code": "pragma solidity ^0.4.19;\n\ncontract IntegerOverflowMinimal {\n    uint public count = 1;\n\n    function run(uint256 input) public {\n        count -= input;\n    }\n}",
        "duration": 300,
        "rounds": 3
      },
      "outputs": {
        "totalExecs": 15000,
        "speed": 50.0,
        "queueCycles": 3,
        "uniqExceptions": 1,
        "coverage": 1.0,
        "vulnerabilities": {
          "unchecked call": {
            "number": 0,
            "instruction distinction": "",
            "test cases": []
          },
          "reentrancy": {
            "number": 0,
            "instruction distinction": "",
            "test cases": []
          },
          "timestamp dependency": {
            "number": 0,
            "instruction distinction": "",
            "test cases": []
          },
          "block number dependency": {
            "number": 0,
            "instruction distinction": "",
            "test cases": []
          },
          "integer overflow": {
            "number": 0,
            "instruction distinction": "",
            "test cases": []
          },
          "integer underflow": {
            "number": 1,
            "instruction distinction": "1a3",
            "test cases": [
              {
                "functions": [
                  {
                    "name": "run",
                    "inputs": [{"type": "uint256", "value": "0x2"}]
                  }
                ],
                "accounts": [
                  {"address": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "balance": 100000000000000000000}
                ]
              }
            ]
          }
        }
      }
    }
  ]
}
```

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- The `vulnerabilities` object must always contain all six keys: `"unchecked call"`, `"reentrancy"`, `"timestamp dependency"`, `"block number dependency"`, `"integer overflow"`, `"integer underflow"`.
- `queueCycles` must exactly equal the `rounds` input value.
- `totalExecs` must equal `round(speed × duration)`.
- `uniqExceptions` must equal the count of vulnerability types whose `number` is greater than `0`.
- For any vulnerability type not detected, set `number` to `0`, `instruction distinction` to `""`, and `test cases` to `[]`.
- The function call sequence in each test case must be the minimal ordered sequence needed to trigger the vulnerability; exclude any calls that do not contribute to reaching the vulnerable state.
- All input `value` fields must be hex-encoded strings prefixed with `"0x"`, valid for the declared Solidity type, and chosen to actively trigger the vulnerability.
- All account `address` fields must be 40-hex-digit strings prefixed with `"0x"`. All `balance` values must be non-negative integers in wei.
- `instruction distinction` must be a non-empty string if and only if `number` is greater than `0`.
- Produce exactly one valid JSON object as output with no additional text or commentary.
"""
