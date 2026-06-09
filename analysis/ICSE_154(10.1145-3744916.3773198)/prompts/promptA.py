prompt = """
### Role
You are an expert smart contract security auditor specializing in digital signature verification and vulnerability detection in Solidity-based blockchain contracts.

### Task
You will receive the Solidity source code of a smart contract. Your task is to analyze it and determine whether it contains any signature replay vulnerabilities, and if so, identify which specific vulnerability types are present.

### Input
- `solidity_source_code`: A string containing the full Solidity source code of one smart contract, exactly as submitted for on-chain deployment.

### Output
A JSON object with exactly two fields:
- `Exist` (boolean): `true` if one or more signature replay vulnerabilities are present in the contract, `false` otherwise.
- `Vuln_type` (array of strings): A list of vulnerability type identifiers present in the contract. Must be drawn exclusively from the set: `"X-CRA"`, `"X-PRA"`, `"CASR"`, `"SSMI"`, `"SMA"`. If `Exist` is `false`, this must be an empty array `[]`.

### Example
```json
{
  "examples": [
    {
      "inputs": {
        "solidity_source_code": "/**\n *Submitted for verification at Etherscan.io on 2019-11-13\n*/\n\n// median.sol - Medianizer v2\n\n// Copyright (C) 2019 Maker Foundation\n\n// This program is free software: you can redistribute it and/or modify\n// it under the terms of the GNU General Public License as published by\n// the Free Software Foundation, either version 3 of the License, or\n// (at your option) any later version.\n\n// This program is distributed in the hope that it will be useful,\n// but WITHOUT ANY WARRANTY; without even the implied warranty of\n// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the\n// GNU General Public License for more details.\n\n// You should have received a copy of the GNU General Public License\n// along with this program. If not, see <http://www.gnu.org/licenses/>.\n\npragma solidity >=0.5.10;\n\ncontract LibNote {\n    event LogNote(\n        bytes4   indexed  sig,\n        address  indexed  usr,\n        bytes32  indexed  arg1,\n        bytes32  indexed  arg2,\n        bytes             data\n    ) anonymous;\n\n    modifier note {\n        _;\n        assembly {\n            // log an 'anonymous' event with a constant 6 words of calldata\n            // and four indexed topics: selector, caller, arg1 and arg2\n            let mark := msize                         // end of memory ensures zero\n            mstore(0x40, add(mark, 288))              // update free memory pointer\n            mstore(mark, 0x20)                        // bytes type data offset\n            mstore(add(mark, 0x20), 224)              // bytes size (padded)\n            calldatacopy(add(mark, 0x40), 0, 224)     // bytes payload\n            log4(mark, 288,                           // calldata\n                 shl(224, shr(224, calldataload(0))), // msg.sig\n                 caller,                              // msg.sender\n                 calldataload(4),                     // arg1\n                 calldataload(36)                     // arg2\n                )\n        }\n    }\n}\n\ncontract Median is LibNote {\n\n    // --- Auth ---\n    mapping (address => uint) public wards;\n    function rely(address usr) external note auth { wards[usr] = 1; }\n    function deny(address usr) external note auth { wards[usr] = 0; }\n    modifier auth {\n        require(wards[msg.sender] == 1, \"Median/not-authorized\");\n        _;\n    }\n\n    uint128        val;\n    uint32  public age;\n    bytes32 public constant wat = \"ethusd\"; // You want to change this every deploy\n    uint256 public bar = 1;\n\n    // Authorized oracles, set by an auth\n    mapping (address => uint256) public orcl;\n\n    // Whitelisted contracts, set by an auth\n    mapping (address => uint256) public bud;\n\n    // Mapping for at most 256 oracles\n    mapping (uint8 => address) public slot;\n\n    modifier toll { require(bud[msg.sender] == 1, \"Median/contract-not-whitelisted\"); _;}\n\n    event LogMedianPrice(uint256 val, uint256 age);\n\n    //Set type of Oracle\n    constructor() public {\n        wards[msg.sender] = 1;\n    }\n\n    function read() external view toll returns (uint256) {\n        require(val > 0, \"Median/invalid-price-feed\");\n        return val;\n    }\n\n    function peek() external view toll returns (uint256,bool) {\n        return (val, val > 0);\n    }\n\n    function recover(uint256 val_, uint256 age_, uint8 v, bytes32 r, bytes32 s) internal pure returns (address) {\n        return ecrecover(\n            keccak256(abi.encodePacked(\"\\x19Ethereum Signed Message:\\n32\", keccak256(abi.encodePacked(val_, age_, wat)))),\n            v, r, s\n        );\n    }\n\n    function poke(\n        uint256[] calldata val_, uint256[] calldata age_,\n        uint8[] calldata v, bytes32[] calldata r, bytes32[] calldata s) external\n    {\n        require(val_.length == bar, \"Median/bar-too-low\");\n\n        uint256 bloom = 0;\n        uint256 last = 0;\n        uint256 zzz = age;\n\n        for (uint i = 0; i < val_.length; i++) {\n            // Validate the values were signed by an authorized oracle\n            address signer = recover(val_[i], age_[i], v[i], r[i], s[i]);\n            // Check that signer is an oracle\n            require(orcl[signer] == 1, \"Median/invalid-oracle\");\n            // Price feed age greater than last medianizer age\n            require(age_[i] > zzz, \"Median/stale-message\");\n            // Check for ordered values\n            require(val_[i] >= last, \"Median/messages-not-in-order\");\n            last = val_[i];\n            // Bloom filter for signer uniqueness\n            uint8 sl = uint8(uint256(signer) >> 152);\n            require((bloom >> sl) % 2 == 0, \"Median/oracle-already-signed\");\n            bloom += uint256(2) ** sl;\n        }\n\n        val = uint128(val_[val_.length >> 1]);\n        age = uint32(block.timestamp);\n\n        emit LogMedianPrice(val, age);\n    }\n\n    function lift(address[] calldata a) external note auth {\n        for (uint i = 0; i < a.length; i++) {\n            require(a[i] != address(0), \"Median/no-oracle-0\");\n            uint8 s = uint8(uint256(a[i]) >> 152);\n            require(slot[s] == address(0), \"Median/signer-already-exists\");\n            orcl[a[i]] = 1;\n            slot[s] = a[i];\n        }\n    }\n\n    function drop(address[] calldata a) external note auth {\n       for (uint i = 0; i < a.length; i++) {\n            orcl[a[i]] = 0;\n            slot[uint8(uint256(a[i]) >> 152)] = address(0);\n       }\n    }\n\n    function setBar(uint256 bar_) external note auth {\n        require(bar_ > 0, \"Median/quorum-is-zero\");\n        require(bar_ % 2 != 0, \"Median/quorum-not-odd-number\");\n        bar = bar_;\n    }\n\n    function kiss(address a) external note auth {\n        require(a != address(0), \"Median/no-contract-0\");\n        bud[a] = 1;\n    }\n\n    function diss(address a) external note auth {\n        bud[a] = 0;\n    }\n\n    function kiss(address[] calldata a) external note auth {\n        for(uint i = 0; i < a.length; i++) {\n            require(a[i] != address(0), \"Median/no-contract-0\");\n            bud[a[i]] = 1;\n        }\n    }\n\n    function diss(address[] calldata a) external note auth {\n        for(uint i = 0; i < a.length; i++) {\n            bud[a[i]] = 0;\n        }\n    }\n}\n\ncontract MedianBATUSD is Median {\n    bytes32 public constant wat = \"BATUSD\";\n\n    function recover(uint256 val_, uint256 age_, uint8 v, bytes32 r, bytes32 s) internal pure returns (address) {\n        return ecrecover(\n            keccak256(abi.encodePacked(\"\\x19Ethereum Signed Message:\\n32\", keccak256(abi.encodePacked(val_, age_, wat)))),\n            v, r, s\n        );\n    }\n}"
      },
      "outputs": {
        "Exist": true,
        "Vuln_type": [
          "X-CRA",
          "X-PRA",
          "SSMI",
          "SMA"
        ]
      }
    },
    {
      "inputs": {
        "solidity_source_code": "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.0;\n\nlibrary Signature {\n  function recoverSigner(bytes32 message, bytes memory sig)\n    internal\n    pure\n    returns (address){\n    \n    uint8 v;\n    bytes32 r;\n    bytes32 s;\n    (v, r, s) = splitSignature(sig);\n    return ecrecover(message, v, r, s);\n  }\n  \n  function splitSignature(bytes memory sig)\n    internal\n    pure\n    returns (uint8, bytes32, bytes32){\n    \n    require(sig.length == 65, \"Invalid Signature\");\n    bytes32 r;\n    bytes32 s;\n    uint8 v;\n    assembly {\n    r := mload(add(sig, 32))\n        s := mload(add(sig, 64))\n        v := byte(0, mload(add(sig, 96)))\n        }\n    return (v, r, s);\n  }\n}\n\n"
      },
      "outputs": {
        "Exist": false,
        "Vuln_type": []
      }
    }
  ]
}
```

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- Only report vulnerability types from the fixed set: `"X-CRA"`, `"X-PRA"`, `"CASR"`, `"SSMI"`, `"SMA"`. Do not invent or use any other labels.
- If the contract does not use `ecrecover()` or any equivalent signature verification mechanism, set `Exist` to `false` and `Vuln_type` to `[]`.
- A contract may have multiple vulnerability types simultaneously; report all that apply.
- If `Exist` is `false`, `Vuln_type` must be an empty array.
- Output only the JSON object — no preamble, explanation, or trailing text.
"""