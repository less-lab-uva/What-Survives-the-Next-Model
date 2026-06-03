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

### Steps

1. **Locate all ecrecover invocations and assess exploitability context.**
   Scan the entire source code for every call to `ecrecover()`, both direct calls and calls delegated through wrapper functions or libraries (e.g., a library `recover()` that internally calls `ecrecover()`).
   - If no `ecrecover()` invocation exists anywhere in the codebase, produce `{"Exist": false, "Vuln_type": []}` and stop.
   - If every `ecrecover()` invocation exists only within a pure utility library — one that returns the recovered address to a caller without itself performing any state mutations, token transfers, permission grants, or access-control decisions based on that address — treat the code as having no exploitable context. Produce `{"Exist": false, "Vuln_type": []}` and stop.
   - Otherwise, continue for each function that both invokes `ecrecover()` and takes a consequential action (state write, asset transfer, approval, minting, etc.) based on the verification result.

2. **Collect the full signature verification context for each site.**
   For each qualifying `ecrecover()` site from Step 1:
   - Identify all arguments passed to `ecrecover()`: the message hash (first argument) and the signature components `v`, `r`, `s`.
   - Trace the entire construction chain of the message hash: follow all variable assignments, function calls, and encoding operations (`keccak256`, `abi.encode`, `abi.encodePacked`, `sha256`, etc.) that ultimately produce the value passed as the hash. This includes helper functions, library calls, domain separator computations, and type hash constants.
   - Identify all `require()` guards, `if` conditions, and modifiers that execute before or as part of the verification in this function or its call chain.
   - Note every state variable that is read immediately before the ecrecover call (as a gate) or written immediately after (to record usage), such as nonce mappings, used-signature mappings, or claimed flags.

3. **Isolate signature-state-relevant variables.**
   Among all variables identified in Step 2:
   - Retain variables that: (a) are encoded into the message hash, (b) gate the ecrecover call via a `require` or conditional, or (c) are written to record that the signature has been consumed.
   - Discard variables that are only referenced in downstream effects after verification has already succeeded (e.g., a token amount retrieved from an external mapping after the signature check), unless they are also part of the signed message.
   - For each retained variable, record its read/write pattern relative to the `ecrecover` call: specifically whether a usage-state variable is both written after verification and read back via a require guard before the next invocation.

4. **Assess X-CRA (Cross-chain Replay Attack).**
   Examine the full message hash construction chain for the presence of a chain identifier that makes the signature binding to one specific blockchain.
   - Search for: `block.chainid`, `chainId` (a parameter or immutable state variable initialized to the deployment chain ID), or an EIP-712-style domain separator that explicitly encodes a chain ID.
   - If a chain identifier is provably included anywhere in the data that feeds into the hash function producing the ecrecover argument, do not flag X-CRA.
   - If no chain identifier is found anywhere in the hash construction path — including within library calls or domain separator helper functions — flag X-CRA.

5. **Assess X-PRA (Cross-project Replay Attack).**
   Examine the full message hash construction chain for the presence of the current contract's own address, which would bind the signature to one specific deployment.
   - Search for: `address(this)` used in hash construction, an immutable variable initialized to `address(this)` at deployment, or a domain separator that encodes the verifying contract address.
   - If `address(this)` or its equivalent is verifiably included in the hash, do not flag X-PRA.
   - If absent, flag X-PRA.

6. **Assess CASR (Contract Account Signature Replay).**
   Determine whether the contract implements or calls EIP-1271-style contract-account signature validation.
   - Look for: implementation of an `isValidSignature(bytes32, bytes)` function, calls to `isValidSignature()` on an external contract, or any code pattern that treats the signer as a contract account (identity, wallet, or smart account address) rather than a plain EOA.
   - If such a mechanism is present, check whether the specific contract account address (e.g., an `identity` parameter, a smart wallet address, or a variable representing which of many contract accounts is being verified) is included in the message hash construction.
   - If EIP-1271-style contract-account verification is present but the specific contract account address is not bound in the hash, flag CASR.
   - If the contract makes no use of EIP-1271 or contract-account verification patterns, do not flag CASR.

7. **Assess SSMI (Signature State Management Issue).**
   Reason about whether the signature verification flow reliably prevents the same signing authority from authorizing the same operation more than once.
   - Check for the presence of at least one of the following mechanisms, enforced before the consequential action takes effect:
     a. A per-signer nonce that is checked to equal an expected value and then incremented or invalidated after each successful use.
     b. A mapping keyed on the signature bytes, the message hash, or a canonical per-operation identifier, with a `require(!used[key])` guard before the action and a `used[key] = true` write after.
     c. A time-bound deadline encoded in the signed message that is verified against `block.timestamp` before the action executes.
   - Flag SSMI if none of these mechanisms are present, or if a mechanism exists but is flawed in any of the following ways:
     - A usage-tracking mapping is written (`used[key] = true`) but is never read back via a `require(!used[key])` guard before the consequential action — i.e., write-only with no enforced read.
     - The tracking key is not canonical or unique for the underlying signing authority: for example, the same private key produces two different valid tracking keys (e.g., compressed versus uncompressed public key each mapping to a different derived address), so the same signing authority can trigger the action once per key variant.
     - The state-management check can be bypassed via an alternative code path or conditional branch.
   - Do not flag SSMI if a proper, enforceable single-use mechanism is confirmed on every reachable path to the consequential action.

8. **Assess SMA (Signature Malleability Attack).**
   Check whether the code enforces the parameter restrictions needed to eliminate ECDSA signature malleability before or at the `ecrecover()` call.
   - Look for explicit `v` validation: `require(v == 27 || v == 28)` or equivalent.
   - Look for explicit `s` range validation: `require(uint256(s) <= 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0)` or any equivalent upper-bound check restricting `s` to the lower half of the secp256k1 curve order.
   - Also check whether a hardened ECDSA library is invoked that performs these checks internally: a library is hardened if it demonstrably enforces lower-`s` normalization and restricts `v`, as in well-known secure implementations (e.g., any ECDSA library that explicitly validates both `v` and `s` before returning).
   - Flag SMA if neither explicit `v`/`s` validation nor a proven-hardened library is used. If only one of the two parameters (`v` or `s`) is validated but not both, still flag SMA.
   - Do not flag SMA if both `v` and `s` are properly constrained, or if a demonstrably hardened library handles both restrictions.

9. **Check for overriding access-control mitigations.**
   For each vulnerability type flagged in Steps 4–8, reason about whether an arbitrary external caller can reach the vulnerable `ecrecover()` call through any publicly accessible execution path.
   - If the function containing the ecrecover call is protected on all paths by an unconditional privileged-role modifier (e.g., `onlyOwner`, `onlyAdmin`) that cannot be bypassed by any unprivileged address, conservatively remove that vulnerability type from the flagged set — an attacker who cannot call the function cannot exploit the flaw.
   - Apply this de-flagging only when the access restriction is unconditional and architectural. Do not de-flag based on incidental state checks that could change over time (e.g., a balance check that happens to be non-zero only for the owner) or checks unrelated to replay prevention.
   - When in doubt, retain the flag.

10. **Compile and format the output.**
    Collect all vulnerability type identifiers that remain flagged after Steps 4–9. If the set is non-empty, set `Exist = true`; otherwise set `Exist = false` and `Vuln_type = []`. Produce a JSON object with exactly the fields `Exist` and `Vuln_type` as specified in the Output section, with no additional fields, commentary, or text.

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- A contract that contains no invocation of `ecrecover()` — directly or through any wrapper — has no signature replay vulnerability; output `{"Exist": false, "Vuln_type": []}`.
- A pure utility library that only provides signature parsing or address recovery without performing any state mutations, asset transfers, or access-control decisions based on the recovered address has no exploitable context within the provided code; output `{"Exist": false, "Vuln_type": []}`.
- Include all applicable vulnerability types in `Vuln_type`; a single contract may have multiple types simultaneously.
- Output only a valid JSON object matching the Output schema. Do not include any explanation, commentary, or text outside the JSON object.
- Follow the Steps above in order as your internal reasoning process.
"""