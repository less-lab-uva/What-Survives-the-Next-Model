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
"""