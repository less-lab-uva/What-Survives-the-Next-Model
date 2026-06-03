prompt = """
### Role
You are an expert smart contract security auditor specializing in digital signature verification and cryptographic vulnerability analysis in Solidity.

### Task
You receive the full Solidity source code of a smart contract and must determine whether the contract contains any signature replay vulnerabilities, identifying every distinct vulnerability type that is present.

### Input
- `solidity_source_code` (string): The complete Solidity source code of the smart contract under analysis.

### Output
A JSON object with exactly two fields:
- `Exist` (boolean): `true` if at least one signature replay vulnerability is present in the contract; `false` otherwise.
- `Vuln_type` (array of strings): A list of detected vulnerability type identifiers. Must be an empty array `[]` when `Exist` is `false`. Each element must be exactly one of the following identifiers:
  - `"X-CRA"`: Cross-chain Replay Attack — a valid signature can be replayed on a different blockchain because no chain identifier (e.g., `block.chainid`) is bound into the signed message hash.
  - `"X-PRA"`: Cross-project Replay Attack — a valid signature can be replayed against a different contract instance with the same code because no contract address (e.g., `address(this)`) is bound into the signed message hash.
  - `"CASR"`: Contract Account Signature Replay — when a contract account signs on behalf of an EOA (EIP-1271 style), the same signature can be accepted by multiple contract accounts of the same EOA because no specific contract account address is bound into the signed message hash.
  - `"SSMI"`: Signature State Management Issue — the signature verification flow lacks a robust mechanism to prevent the same signature or signing authority from being used more than once (e.g., absent or flawed nonce, usage-record mapping, or deadline enforcement).
  - `"SMA"`: Signature Malleability Attack — the ECDSA signature parameters `v` and `s` are not properly restricted, allowing an attacker to craft a mathematically equivalent alternative valid signature for the same message.
A single contract may have multiple types simultaneously.

### Example

{
    "examples": [
      {
        "inputs": {
          "solidity_source_code": "pragma solidity ^0.4.20;\n\nlibrary SafeMath {\n  function \n  mul(uint256 a, uint256 b) internal pure returns (uint256) {\n    uint256 c = a * b;\n    \n  assert(a == 0 || c / a == b);\n    return c;\n  }\n  function div(uint256 a, uint256 b) \n  internal pure returns (uint256) {\n    uint256 c = a / b;\n    return c;\n  }\n  function \n  sub(uint256 a, uint256 b) internal pure returns (uint256) {\n    assert(b <= a);\n    return a \n  - b;\n  }\n  function add(uint256 a, uint256 b) internal pure returns (uint256) {\n    uint256\n  c = a + b;\n    assert(c >= a);\n    return c;\n  }\n}\n\ncontract Ownable {\n  address public\n  owner;\n  event OwnershipTransferred(address indexed previousOwner, address indexed\n  newOwner);\n  function Ownable() internal { owner = msg.sender; }\n  modifier onlyOwner() {\n  require(msg.sender == owner); _; }\n  function transferOwnership(address newOwner) onlyOwner\n  public {\n    require(newOwner != address(0));\n    OwnershipTransferred(owner, newOwner);\n\n  owner = newOwner;\n  }\n}\n\ncontract tokenInterface {\n  function balanceOf(address _owner)\n  public constant returns (uint256 balance);\n  function transfer(address _to, uint256 _value)\n  public returns (bool);\n}\n\ncontract Library {\n  function createBSMHash(string payload) pure\n  internal returns (bytes32) {\n    string memory prefix = \"\\x18Bitcoin Signed Message:\\n\";\n\n     return sha256(sha256(prefix, bytes1(bytes(payload).length), payload));\n  }\n  function\n  validateBSM(string payload, address key, uint8 v, bytes32 r, bytes32 s) internal pure returns\n  (bool) {\n    return key == ecrecover(createBSMHash(payload), v, r, s);\n  }\n  function\n  btcAddrPubKeyUncompr(bytes32 _xPoint, bytes32 _yPoint) internal pure returns (bytes20\n  hashedPubKey) {\n    bytes1 startingByte = 0x04;\n    return ripemd160(sha256(startingByte,\n  _xPoint, _yPoint));\n  }\n  function btcAddrPubKeyCompr(bytes32 _x, bytes32 _y) internal pure\n  returns (bytes20 hashedPubKey) {\n    bytes1 _startingByte;\n    if (uint256(_y) % 2 == 0) {\n  _startingByte = 0x02; } else { _startingByte = 0x03; }\n    return\n  ripemd160(sha256(_startingByte, _x));\n  }\n  function ethAddressPublicKey(bytes32 _xPoint,\n  bytes32 _yPoint) internal pure returns (address ethAddr) {\n    return\n  address(keccak256(_xPoint, _yPoint));\n  }\n  function toAsciiString(address x) internal pure\n  returns (string) {\n    bytes memory s = new bytes(42);\n    s[0] = 0x30; s[1] = 0x78;\n    for\n  (uint i = 0; i < 20; i++) {\n      byte b = byte(uint8(uint(x) / (2**(8*(19 - i)))));\n\n  byte hi = byte(uint8(b) / 16);\n      byte lo = byte(uint8(b) - 16 * uint8(hi));\n\n  s[2+2*i] = char(hi); s[2+2*i+1] = char(lo);\n    }\n    return string(s);\n  }\n  function\n  char(byte b) internal pure returns (byte c) {\n    if (b < 10) return byte(uint8(b) + 0x30);\n\n    else return byte(uint8(b) + 0x57);\n  }\n}\n\ncontract Swap is Ownable, Library {\n  using\n  SafeMath for uint256;\n  tokenInterface public tokenContract;\n  Data public dataContract;\n\n  mapping(address => bool) claimed;\n\n  function Swap(address _tokenAddress) public {\n\n  tokenContract = tokenInterface(_tokenAddress);\n  }\n  function claim(address _ethAddrReceiver,\n  bytes32 _x, bytes32 _y, uint8 _v, bytes32 _r, bytes32 _s) public returns (bool) {\n\n  require(dataContract != address(0));\n    address btcAddr0x;\n    btcAddr0x =\n  address(btcAddrPubKeyCompr(_x, _y));\n    if (dataContract.CftBalanceOf(btcAddr0x) == 0 ||\n  claimed[btcAddr0x]) {\n      btcAddr0x = address(btcAddrPubKeyUncompr(_x, _y));\n    }\n\n  require(dataContract.CftBalanceOf(btcAddr0x) != 0);\n    require(!claimed[btcAddr0x]);\n\n  address checkEthAddr0x = address(ethAddressPublicKey(_x, _y));\n\n  require(validateBSM(toAsciiString(_ethAddrReceiver), checkEthAddr0x, _v, _r, _s));\n    uint256\n  tokenAmount = dataContract.CftBalanceOf(btcAddr0x) * 10**10 / 2;\n    claimed[btcAddr0x] =\n  true;\n    tokenContract.transfer(_ethAddrReceiver, tokenAmount);\n    return true;\n  }\n\n  function withdrawTokens(address to, uint256 value) public onlyOwner returns (bool) {\n\n  return tokenContract.transfer(to, value);\n  }\n  function setTokenContract(address\n  _tokenContract) public onlyOwner {\n    tokenContract = tokenInterface(_tokenContract);\n  }\n\n  function setDataContract(address _tokenContract) public onlyOwner {\n    dataContract =\n  Data(_tokenContract);\n  }\n  function () public payable { revert(); }\n}\n\ncontract Data {\n\n  mapping(address => uint256) public CftBalanceOf;\n  function Data() public {}\n}"
        },
        "outputs": {
          "Exist": true,
          "Vuln_type": ["X-CRA", "X-PRA", "SSMI", "SMA"]
        }
      },
      {
        "inputs": {
          "solidity_source_code": "// SPDX-License-Identifier: MIT\npragma solidity \n  ^0.8.0;\n\nlibrary Signature {\n  function recoverSigner(bytes32 message, bytes memory sig)\n  \n   internal\n    pure\n    returns (address) {\n    uint8 v;\n    bytes32 r;\n    bytes32 s;\n  \n   (v, r, s) = splitSignature(sig);\n    return ecrecover(message, v, r, s);\n  }\n\n  function \n  splitSignature(bytes memory sig)\n    internal\n    pure\n    returns (uint8, bytes32, bytes32)\n  {\n    require(sig.length == 65, \"Invalid Signature\");\n    bytes32 r;\n    bytes32 s;\n\n  uint8 v;\n    assembly {\n      r := mload(add(sig, 32))\n      s := mload(add(sig, 64))\n\n  v := byte(0, mload(add(sig, 96)))\n    }\n    return (v, r, s);\n  }\n}"
        },
        "outputs": {
          "Exist": false,
          "Vuln_type": []
        }
      }
    ]
}

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- A contract that contains no invocation of `ecrecover()` — directly or through any wrapper — has no signature replay vulnerability; output `{"Exist": false, "Vuln_type": []}`.
- A pure utility library that only provides signature parsing or address recovery without performing any state mutations, asset transfers, or access-control decisions based on the recovered address has no exploitable context within the provided code; output `{"Exist": false, "Vuln_type": []}`.
- Include all applicable vulnerability types in `Vuln_type`; a single contract may have multiple types simultaneously.
- Output only a valid JSON object matching the Output schema. Do not include any explanation, commentary, or text outside the JSON object.
"""