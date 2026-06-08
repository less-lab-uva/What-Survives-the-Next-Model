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

### Steps

1. **Parse every structural element from the source code.**
   - Record the Solidity compiler version from the `pragma` directive. Versions before `0.8.0` have no built-in arithmetic overflow or underflow protection.
   - List every function: name, visibility (`public`, `private`, `internal`, `external`), `payable` flag, parameter names and their Solidity types.
   - List every state variable: name, type, initial value if declared, and visibility.
   - Map every conditional branch (`if`, `require`, `assert`): which state variable(s) it tests, the comparison operator, and the function that contains it.
   - Note every arithmetic operation on integer types (addition, subtraction, multiplication) and every external call (`.call()`, `.send()`, `.transfer()`).

2. **Identify inter-function state dependencies and offsetting relationships.**
   - For each state variable, record which functions read it and which functions write it.
   - Identify **offsetting pairs**: two functions that modify the same state variable in opposing directions — one accumulates (increments or adds) while the other neutralizes (decrements, resets to zero, or subtracts the accumulated amount). Calling the neutralizing function mid-sequence resets critical state and prevents the accumulating path from crossing any threshold gating a vulnerable branch.
   - For each conditional branch that guards a potentially vulnerable operation, trace the full **dependency chain**: the complete ordered sequence of function calls required to make the branch condition true, accounting for (a) functions that may need to be called multiple times to cross a numeric threshold, and (b) intermediate calls that would offset and invalidate the accumulated state if inserted.

3. **Classify the contract against each of the six vulnerability types.**
   - **Integer underflow**: Any subtraction on an unsigned integer type (`uint`, `uint8`, …, `uint256`) in Solidity <0.8.0 where the subtrahend can exceed the minuend, causing the result to wrap around to a very large number.
   - **Integer overflow**: Any addition or multiplication on an integer type in Solidity <0.8.0 where the result can exceed the type's maximum representable value, wrapping around to a small number.
   - **Reentrancy**: Any function that performs an external call (`.call{value:...}()`, `.send()`, `.transfer()`) before it has finished updating its own state variables, violating the checks-effects-interactions pattern.
   - **Unchecked call**: Any use of `.call()` or `.send()` whose Boolean return value is not captured in a variable and explicitly checked.
   - **Timestamp dependency**: Any conditional branch or assignment that reads `block.timestamp` or the alias `now`.
   - **Block number dependency**: Any conditional branch or assignment that reads `block.number`.
   - For each type, record the specific function and operation that is vulnerable. If no instance exists, mark as not detected.

4. **Construct the minimal triggering function call sequence for each detected vulnerability.**
   - Start with the function that directly executes the vulnerable operation (the last call in the sequence).
   - Prepend, in order, only those prerequisite function calls identified in Step 2 that are strictly required to satisfy the branch conditions leading to the vulnerable operation.
   - **Exclude** any function from the sequence whose execution would invoke an offsetting operation that resets critical accumulated state, even if that function appears elsewhere in legitimate usage.
   - If a single function must be called more than once consecutively to push a state variable past a required threshold, include it that many times in sequence.
   - **Tie-breaking rule**: When two sequences of equal length both trigger the same vulnerability, select the one that exercises a greater number of distinct conditional branches in the contract.
   - **Edge case — no prerequisites**: If the vulnerability is directly triggerable in one call with no prior state setup, the sequence contains exactly that one call.

5. **Select concrete argument values for every function call in each test case.**
   - Choose values that make the triggering condition true:
     - **Integer underflow**: Choose a subtrahend strictly greater than the current value of the unsigned state variable (e.g., if a `uint` state variable initializes to `1`, pass `2` so the subtraction wraps; encode as `"0x2"`).
     - **Integer overflow**: Choose addends or multipliers whose result exceeds `2^256 − 1` for `uint256` (or the analogous maximum for smaller types).
     - **Reentrancy / unchecked call**: Use the test account address for any address-typed argument; ensure the account balance covers any required value transfer.
     - **Timestamp / block number dependency**: Use `"0x0"` for numeric arguments unless the branch requires a specific nonzero value, in which case use `"0x1"`.
   - Encode every argument value as a hex string prefixed with `"0x"`.
   - For each test case, assign one account with address `"0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"` and balance `100000000000000000000` (100 ETH in wei), unless the contract logic requires a higher balance to satisfy a payable condition.

6. **Generate the instruction distinction identifier for each detected vulnerability.**
   - Construct a 3–5-character alphanumeric string using the pattern `[leading digit(s)][letter][trailing digit(s)]`:
     - **Leading digit(s)**: The 1-based index of the vulnerable function in the order functions appear in the source (first function defined = `1`, second = `2`, etc.).
     - **Letter**: Instance counter within that function, starting at `a` for the first or only vulnerable operation, `b` for a second distinct operation, and so on.
     - **Trailing digit(s)**: Approximate 1-based index of the vulnerable operation within the function body (first operation = `1`, second = `2`; for operations inside nested blocks, append an extra digit reflecting nesting depth, e.g., `12` for the second operation inside a nested conditional).
   - Example derivation: `"1a3"` means the first function in the file, first vulnerable instance in that function, third instruction position within the function.
   - Use `""` for every vulnerability type whose `number` is `0`.

7. **Estimate the fuzzing execution statistics.**
   - **`speed`**: Begin with a baseline of `50.0` executions per second. Subtract up to `10.0` for contracts with more than eight functions or more than eight distinct conditional branches (apply both deductions if both conditions hold). Add up to `5.0` for contracts with fewer than three functions and at most two conditional branches.
   - **`totalExecs`**: Compute as `round(speed × duration)`.
   - **`queueCycles`**: Copy the `rounds` input value exactly.
   - **`uniqExceptions`**: Count the number of the six vulnerability types whose `number` is greater than `0`.
   - **`coverage`**: Estimate based on structural complexity:
     - 1–3 functions and ≤2 conditional branches: 0.90–1.0. Use the upper bound when all branches in the contract are reachable by the generated test cases.
     - 4–8 functions or 3–8 conditional branches: 0.65–0.85. Use the upper bound when the generated sequences cover all vulnerable paths without leaving reachable branches untouched.
     - More than 8 functions or more than 8 conditional branches: 0.40–0.65. Use the lower end when complex nested conditions remain unreachable without additional state setup not captured by the generated sequences.

8. **Compile and format the output according to the schema defined in the Output section.**
   - Assemble the complete JSON object, populating every required field.
   - Before finalizing, verify: `queueCycles == rounds`; `totalExecs == round(speed × duration)`; `uniqExceptions` equals the count of types with `number > 0`; all six vulnerability type keys are present with correctly structured values.
   - Output only the JSON object with no surrounding text or commentary.

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
- Follow the Steps above in order as your internal reasoning process.
"""
