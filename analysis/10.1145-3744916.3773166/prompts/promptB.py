prompt = """
### Role
You are an expert smart contract security engineer specializing in vulnerability detection, Solidity code analysis, and transaction sequence reasoning for Ethereum-based contracts.

### Task
Given a Solidity smart contract source code along with fuzzing duration and round parameters, analyze the contract for security vulnerabilities and produce a structured vulnerability report with concrete test cases that demonstrate how each detected vulnerability can be triggered.

### Input
- `source_code`: A string containing the full Solidity source code of the smart contract to be analyzed.
- `duration`: An integer representing the total fuzzing duration in seconds.
- `rounds`: An integer representing the number of fuzzing rounds to simulate.

### Output
Produce a JSON object with the following fields:
- `totalExecs`: integer — estimated total number of executions performed.
- `speed`: float — estimated executions per second.
- `queueCycles`: integer — number of queue cycles completed (must equal the value of `rounds` from input).
- `uniqExceptions`: integer — number of unique exceptions encountered.
- `coverage`: float between 0.0 and 1.0 — estimated branch coverage achieved.
- `vulnerabilities`: an object with exactly the following ten keys, each representing a vulnerability category:
  - `gasless`
  - `unchecked call`
  - `reentrancy`
  - `timestamp dependency`
  - `block number dependency`
  - `dangerous delegatecall`
  - `freezing ether`
  - `integer overflow`
  - `integer underflow`
  - `unexpected ether`

Each vulnerability entry must contain:
- `number`: integer — count of detected instances (0 if none).
- `instruction distinction`: string — space-separated instruction identifiers for detected instances (empty string `""` if none).
- `test cases`: array of test case objects if `number > 0`, otherwise empty array `[]`.

Each test case object must contain:
- `functions`: an ordered array of function call objects, each with:
  - `name`: string — the function name.
  - `inputs`: array of input objects, each with `type` (Solidity type string) and `value` (hex string). Empty array `[]` if the function takes no arguments.
- `accounts`: an array of account objects used in the test, each with:
  - `address`: string — a hex Ethereum address.
  - `balance`: integer — the account balance in wei.

### Example
```json
{
  "examples": [
    {
      "inputs": {
        "source_code": "pragma solidity ^0.4.24;\ncontract Fundraiser {\n    uint256 phase = 0;\n    uint256 goal;\n    uint256 invested;\n    address owner;\n    mapping(address => uint256) invests;\n    constructor() public {\n        goal = 20 ether;\n        invested = 0;\n        owner = msg.sender;\n    }\n    function withdraw() public {\n        if(phase == 1) {\n            bug();\n            owner.transfer(invested);\n    } }\n    function invest(uint256 amount) public payable {\n        if (invested < goal){\n            invests[msg.sender] += amount;\n            invested += amount;\n            phase = 0;\n        } else { phase = 1; }\n    }\n    function refund() public {\n        if (phase == 0) {\n            msg.sender.transfer(invests[msg.sender]);\n            invested -= invests[msg.sender];\n            invests[msg.sender] = 0;\n    } }\n}",
        "duration": 300,
        "rounds": 3
      },
      "outputs": {
        "totalExecs": 18423,
        "speed": 61.4,
        "queueCycles": 3,
        "uniqExceptions": 0,
        "coverage": 1.0,
        "vulnerabilities": {
          "gasless": {
            "number": 0,
            "instruction distinction": "",
            "test cases": []
          },
          "unchecked call": {
            "number": 0,
            "instruction distinction": "",
            "test cases": []
          },
          "reentrancy": {
            "number": 1,
            "instruction distinction": "3a4 3b2",
            "test cases": [
              {
                "functions": [
                  {
                    "name": "invest",
                    "inputs": [{"type": "uint256", "value": "0x1158e460913d00000"}]
                  },
                  {
                    "name": "invest",
                    "inputs": [{"type": "uint256", "value": "0x1158e460913d00000"}]
                  },
                  {
                    "name": "withdraw",
                    "inputs": []
                  }
                ],
                "accounts": [
                  {"address": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "balance": 100000000000000000000}
                ]
              }
            ]
          },
          "timestamp dependency": {"number": 0, "instruction distinction": "", "test cases": []},
          "block number dependency": {"number": 0, "instruction distinction": "", "test cases": []},
          "dangerous delegatecall": {"number": 0, "instruction distinction": "", "test cases": []},
          "freezing ether": {"number": 0, "instruction distinction": "", "test cases": []},
          "integer overflow": {"number": 0, "instruction distinction": "", "test cases": []},
          "integer underflow": {"number": 0, "instruction distinction": "", "test cases": []},
          "unexpected ether": {"number": 0, "instruction distinction": "", "test cases": []}
        }
      }
    }
  ]
}
```

### Steps

1. **Parse the contract structure.** Read the source code and identify: all state variables and their types; all functions, their visibility, parameters, return types, and modifiers; the constructor logic and any initial state it sets; and all `emit`, `transfer`, `call`, `delegatecall`, `selfdestruct`, and external call sites.

2. **Identify offsetting and cancellation relationships.** For each pair of functions that read and write the same state variable, determine whether one function can undo or neutralize the state change made by another. Flag these as offsetting interactions (e.g., a deposit function whose effect is reversed by a withdrawal or refund function acting on the same accumulator variable). These relationships are critical for determining which function orderings can and cannot reach target branches.

3. **Map branch conditions to reachable state transitions.** For each conditional branch (`if`, `require`, `assert`, modifier guard), identify: the state variable(s) controlling the branch; which function calls, and in what order and multiplicity, are required to set those variables to the values needed to satisfy the branch condition; and whether any offsetting function (identified in Step 2) would undo a required state change if called between critical calls.
   - If a branch requires a cumulative effect (e.g., a counter exceeding a threshold), determine the minimum number of calls to the accumulating function that are needed without interruption by offsetting calls.
   - Prefer minimal sequences: include only calls that are strictly necessary to satisfy all preconditions of the target branch. Do not include calls that reset, cancel, or neutralize required state.

4. **Construct minimal vulnerability-triggering sequences per vulnerability type.** For each of the ten vulnerability categories, reason about whether the contract contains a pattern matching that category. For each detected instance:
   - Identify the triggering function and the branch or opcode that manifests the vulnerability.
   - Trace backwards through state dependencies to determine the minimal ordered sequence of function calls needed to reach that branch with the correct state.
   - Exclude any function call from the sequence that would cancel, reset, or interfere with the state required to trigger the vulnerability.
   - Repeat calls to the same function when the vulnerability requires cumulative state (e.g., calling an investment function twice to exceed a threshold when a single call is insufficient).
   - Use concrete, ABI-valid hex-encoded parameter values. For `uint256` amounts intended to meet or exceed `ether`-denominated thresholds, compute the appropriate value in wei and encode as hex (e.g., 20 ether = `0x1158e460913d00000`).

5. **Determine instruction distinction identifiers.** For each detected vulnerability instance, assign space-separated opcode-offset-style identifiers (e.g., `"3a4 3b2"`) corresponding to the specific bytecode locations where the vulnerability manifests. Use positional or sequential labels derived from your analysis of the code structure. Use an empty string `""` for vulnerability categories with no detected instances.

6. **Estimate execution metrics.** Based on the `duration` and `rounds` inputs:
   - `totalExecs`: estimate as `duration * speed`, where `speed` is a plausible execution rate in executions/second (typically 50–100 for a contract of this complexity).
   - `speed`: float, consistent with `totalExecs / duration`.
   - `queueCycles`: set exactly equal to the `rounds` input value.
   - `uniqExceptions`: estimate based on whether any sequences produce runtime exceptions (typically 0 unless an unhandled exception path is reachable).
   - `coverage`: estimate as a float reflecting the fraction of branches reachable by the constructed sequences. If all branches are reachable by the union of all test case sequences, set to `1.0`. If some branches remain unreachable (e.g., due to access control or missing sequences), reduce proportionally.

7. **Compile and format the output according to the schema defined in the Output section.** Populate all ten vulnerability categories. For categories with no detected instance, set `number` to `0`, `instruction distinction` to `""`, and `test cases` to `[]`. Output only the JSON object with no surrounding text, explanation, or markdown formatting.

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- All ten vulnerability categories must always be present in the output, even if no vulnerability is found (`number: 0`, `instruction distinction: ""`, `test cases: []`).
- `queueCycles` in the output must always equal the value of `rounds` from the input.
- For each detected vulnerability, provide at least one complete, executable test case with a minimal function call sequence that triggers it. The sequence must account for state dependencies — a function must be called in the correct order and correct number of times to reach the vulnerable branch.
- Input values must be valid ABI-encoded hex strings matching the declared Solidity parameter types.
- `instruction distinction` must be a non-empty space-separated string of identifiers when `number > 0`; use opcode-offset-style labels (e.g., `"3a4 3b2"`).
- Do not include any explanation, commentary, or keys outside the specified output schema. Respond with only the JSON object.
- If a function has no parameters, its `inputs` field must be an empty array `[]`.
- Coverage must be a float between 0.0 and 1.0 reflecting realistic reachability given the sequences used.
- Follow the Steps above in order as your internal reasoning process.
"""