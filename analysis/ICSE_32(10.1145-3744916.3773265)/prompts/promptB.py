prompt = """
### Role
You are an expert software engineer specializing in change impact analysis for Java codebases. You understand how bugs propagate across methods and files and can reason about which code locations must be co-modified to fully address a described software defect.

### Task
Given a bug report describing a software defect, a seed method as the initial change location, a structured representation of a Java code repository with method summaries and source code, and the repository's recent commit history, predict which other methods in the repository must be changed alongside the seed method to fully resolve the described bug.

### Input
You receive a single JSON object with the following fields:

- `instance_id` (string): A unique identifier for this benchmark instance.
- `repo` (string): The repository identifier in `"organization/project"` format.
- `commit` (string): The hash of the target commit representing the change.
- `parent_commit` (string): The hash of the parent commit immediately before the change.
- `seed_file` (string): The file path of the source file containing the seed method.
- `seed_method` (string): The name of the seed method — the initial code location where the change begins.
- `focal_method_id` (string): A numeric string identifier for the seed method within the dataset.
- `issue_summary` (string): A concise title summarizing the reported bug.
- `issue_description` (string): A detailed bug report containing a description of the problem, relevant code excerpts, proposed fixes, and references to any methods or classes requiring changes.
- `seed_method_source` (string): The current source code of the seed method.
- `repository` (XML string): A structured XML representation of the repository organized by `<package>`, `<class>`, and `<method>` elements. Each `<class>` element has a `name` attribute and a `file` attribute. Each `<method>` element has a `name` attribute, a `<summary>` child with a natural-language description, and a `<source>` child with the method's source code. Some entries include comments indicating omitted sibling elements.
- `commit_history` (object): A nested JSON object. The outer key is a string formatted as `"<current_commit><sep><parent_commit>"`. Its value is a dictionary where each key is the hash of a prior commit in which the seed file was modified, and each value is a list of file paths that were also modified in that same prior commit.

### Output
Produce a JSON object with the following field:

- `impacted_methods` (array of strings): The predicted set of methods that need to be co-changed with the seed method to address the described bug. Each element must be formatted as `"ClassName,methodName"` with no spaces around the comma. Do not include the seed method itself. If no other methods are predicted to be impacted, return an empty array.

### Example
```json
{
  "examples": [
    {
      "inputs": {
        "instance_id": "instance-00050",
        "repo": "apache/ant-ivy",
        "commit": "2c932d1af2182f60a8629fc8059c3681e9ede9ac",
        "parent_commit": "89574baa05c3fde6bcda2ffb6b5dfeba080db0c6",
        "seed_file": "src/java/org/apache/ivy/core/resolve/IvyNode.java",
        "seed_method": "getConflictManager",
        "focal_method_id": "1331",
        "issue_summary": "Conflict managers ignored, when assigned to modules in Ivy configuration (setting, ivyconf.xml)",
        "issue_description": "Only conflict managers assigned in the module description (ivy.xml) are used.\nConflict managers assigned in the ivy configuration (setting, ivyconf.xml) are ignored.\nSee\nhttps://svn.apache.org/repos/asf/incubator/ivy/core/trunk/src/java/org/apache/ivy/core/resolve/IvyNode.java\npublic ConflictManager getConflictManager(ModuleId mid) {\nif (_md == null)\n{\n            throw new IllegalStateException(\"impossible to get conflict manager when data has not been loaded\");\n        }\nConflictManager cm = _md.getConflictManager(mid);\nreturn cm == null ? _settings.getDefaultConflictManager() : cm;\n}\nIf no matching conflict manager is found in the module description then the default conflict manager is returned.\nI suppose the last line should be:\nreturn cm == null ? _data.getIvy().getConflictManager(mid) : cm;\nThis will also return the default conflict manager if no matching conflict managers are found in the ivy configuration.\nPlease note (for source base 1.4.1):\nIvy.getConflictManager(ModuleId) is the only method to call\nIvy.getConflictManager(String) which is the only method to access _conflictsManager.\nAnd Ivy.getConflictManager(ModuleId) is not called from anywhere.\nThus conflict managers assigned in ivyconf.xml cannot be accessed in source base 1.4.1.\nThe Ivy configuration (setting) is as follows (parts are removed)\n<ivyconf>\n<typedef name=\"my-latest-strategy\" classname=\"...\"/>\n<latest-strategies>\n<my-latest-strategy/>\n</latest-strategies>\n<conflict-managers>\n<latest-cm name=\"my-latest-strategy\" latest=\"my-latest-strategy\"/>\n</conflict-managers>\n<modules>\n<module organisation=\"my-org\" name=\".*\" resolver=\"...\" conflict-manager=\"my-latest-strategy\"/>\n</modules>\n</ivyconf>\nAlso:\nhttps://svn.apache.org/repos/asf/incubator/ivy/core/trunk/src/java/org/apache/ivy/plugins/conflict/LatestConflictManager.java\nThe method toString() can return null. This is seen when the conflict manager is assigned as the default conflict manager in the debug output.\nI suppose the method should be:\npublic String toString()\n{\n        return String.valueOf(getStrategy());\n    }",
        "seed_method_source": "public ConflictManager getConflictManager(ModuleId mid) {\n        if (_md == null) {\n            throw new IllegalStateException(\"impossible to get conflict manager when data has not been loaded\");\n        }\n        ConflictManager cm = _md.getConflictManager(mid);\n        return cm == null ? _settings.getDefaultConflictManager() : cm;\n    }",
        "repository": "<repository>\n  <package name=\"src.java.org.apache.ivy.core.resolve\">\n    <class name=\"IvyNode\" file=\"src/java/org/apache/ivy/core/resolve/IvyNode.java\">\n      <method name=\"getId\">\n        <summary>Return the module revision id for this node.</summary>\n        <source><![CDATA[\n    public ModuleRevisionId getId() {\n    \treturn _id;\n    }\n        ]]></source>\n      </method>\n      <method name=\"isLoaded\">\n        <summary>Return true if the module descriptor has been loaded for this node.</summary>\n        <source><![CDATA[\n    public boolean isLoaded() {\n        return _md != null;\n    }\n        ]]></source>\n      </method>\n      <method name=\"getConflictManager\">\n        <summary>Return the conflict manager applicable to the given ModuleId, falling back to the default if none is set in the module descriptor.</summary>\n        <source><![CDATA[\n    public ConflictManager getConflictManager(ModuleId mid) {\n        if (_md == null) {\n            throw new IllegalStateException(\"impossible to get conflict manager when data has not been loaded\");\n        }\n        ConflictManager cm = _md.getConflictManager(mid);\n        return cm == null ? _settings.getDefaultConflictManager() : cm;\n    }\n        ]]></source>\n      </method>\n      <!-- ... (47 additional methods omitted) -->\n    </class>\n    <!-- ... (3 additional classes omitted: CallerNode, ResolveData, VisitNode) -->\n  </package>\n  <package name=\"src.java.org.apache.ivy.plugins.conflict\">\n    <class name=\"LatestConflictManager\" file=\"src/java/org/apache/ivy/plugins/conflict/LatestConflictManager.java\">\n      <method name=\"toString\">\n        <summary>Return a string representation; uses the strategy object if available.</summary>\n        <source><![CDATA[\n    public String toString() {\n        return String.valueOf(_strategy);\n    }\n        ]]></source>\n      </method>\n      <method name=\"setStrategy\">\n        <summary>Set the latest strategy instance to use for conflict resolution.</summary>\n        <source><![CDATA[\n    public void setStrategy(LatestStrategy strategy) {\n        _strategy = strategy;\n    }\n        ]]></source>\n      </method>\n      <method name=\"getStrategy\">\n        <summary>Return the latest strategy, lazily resolving it by name from settings if not already set.</summary>\n        <source><![CDATA[\n    public LatestStrategy getStrategy() {\n        if (_strategy == null) {\n            if (_strategyName != null) {\n                _strategy = getSettings().getLatestStrategy(_strategyName);\n                if (_strategy == null) {\n                    Message.error(\"unknown latest strategy: \"+_strategyName);\n                    _strategy = getSettings().getDefaultLatestStrategy();\n                }\n            } else {\n                _strategy = getSettings().getDefaultLatestStrategy();\n            }\n        }\n        return _strategy;\n    }\n        ]]></source>\n      </method>\n      <!-- ... (5 additional methods omitted) -->\n    </class>\n    <!-- ... (4 additional classes omitted: AbstractConflictManager, NoConflictManager, RegexpConflictManager, StrictConflictManager) -->\n  </package>\n  <!-- ... (12 additional packages omitted) -->\n</repository>",
        "commit_history": {
          "2c932d1af2182f60a8629fc8059c3681e9ede9ac<sep>89574baa05c3fde6bcda2ffb6b5dfeba080db0c6": {
            "89574baa05c3fde6bcda2ffb6b5dfeba080db0c6": [
              "src/java/org/apache/ivy/ant/IvyPostResolveTask.java",
              "src/java/org/apache/ivy/ant/IvyTask.java"
            ],
            "4a1334ac9c56bb94dda004f623f66603a1bf0271": [
              "src/java/org/apache/ivy/ant/IvyTask.java"
            ],
            "413accec848b1ad7b6de3b6c95c63dd751b847ac": [
              "src/java/org/apache/ivy/ant/IvyPostResolveTask.java",
              "src/java/org/apache/ivy/ant/IvyTask.java"
            ],
            "d8f288a35e63d1e9682c7e188b37c0d7e8e537a7": [
              "src/java/org/apache/ivy/core/module/descriptor/DefaultModuleDescriptor.java"
            ],
            "feb0d2f4d8fd3a5e50bb1769c14fc6034aefcdc0": [
              "src/java/org/apache/ivy/core/module/descriptor/DefaultDependencyDescriptor.java"
            ]
          }
        }
      },
      "outputs": {
        "impacted_methods": [
          "LatestConflictManager,toString"
        ]
      }
    }
  ]
}
```

### Steps

1. **Extract the change intent from the bug report.**
   Read `issue_summary` and `issue_description` carefully. Identify:
   - The core malfunction: what is broken and why it is broken
   - Every method name and class name explicitly mentioned in the report as requiring a change or as exhibiting incorrect behavior
   - Any proposed code fixes or suggested rewrites included in the report
   - Secondary issues noted alongside the primary bug (e.g., a separate method with a related defect)

   Maintain a running list of all explicitly named methods and classes as seed candidates for the impact set.

2. **Analyze the seed method.**
   Examine `seed_method_source` in light of the identified issue. Determine:
   - What the method currently does and where its logic is faulty relative to the bug description
   - What behavioral change the fix requires (e.g., a different return expression, a new branch, a changed call target)
   - Whether the fix alters the method's observable contract — its return values, thrown exceptions, or side effects — in a way that would affect callers or related methods

3. **Collect historically co-changed files from `commit_history`.**
   Parse `commit_history`. The outer key has the form `"<current_commit><sep><parent_commit>"`. Its value is a dictionary mapping prior commit hashes to lists of file paths changed in those commits. Collect all unique file paths across every entry in this inner dictionary.
   - Include files from all prior commits without filtering or deduplication by commit.
   - If the inner dictionary is empty, treat the historically co-changed file set as empty and proceed; the candidate set will be built from structural dependencies alone.
   - The seed file itself need not appear in commit_history to be included in later steps.

4. **Build the history-based candidate method set.**
   In the `repository` XML, find every `<class>` whose `file` attribute exactly matches one of the co-changed file paths from Step 3. For each such class, enumerate all `<method>` elements it contains. These form the history-based candidate set.
   - Always also include all methods in the class that contains `seed_method` (match by the `file` attribute equaling `seed_file`), as a baseline regardless of commit history.
   - If a co-changed file from Step 3 has no matching `<class>` in the repository XML, skip it.
   - Method identity is `(class name, method name)` as given by the XML attributes.

5. **Expand the candidate set via dependence coupling (up to 1 indirect hop).**
   For each method currently in the candidate set, add the following methods to the set:

   (a) **Class-member dependencies**: every other `<method>` in the same `<class>` element. This expansion is mandatory for every candidate.

   (b) **Direct calling dependencies**: any method in the repository whose name appears as a method invocation in the `<source>` of the candidate. Scan the candidate's source text for method-call patterns (e.g., `targetName(`, `.targetName(`) and match against `<method name="...">` attributes across all classes.

   (c) **Reverse direct calling dependencies**: any method in the repository whose `<source>` contains a call to the candidate method by name.

   (d) **One-hop indirect dependencies**: apply (b) and (c) once more to every method added via (b) and (c) in this step — do not recurse further beyond this single additional hop.

   Edge cases:
   - If a method name from (b) or (c) matches methods in multiple classes, include all of them.
   - Ambiguous or overloaded names: include all repository methods sharing that name.
   - The result of this step is the dependence-enhanced candidate set.

6. **Partition the dependence-enhanced candidate set into dependence clusters.**
   Treat each dependence relation from Step 5 (calling, called-by, or same-class membership) as an undirected edge and find the connected components of the resulting graph:
   - Two methods belong to the same cluster if any path of dependence edges connects them, ignoring edge direction.
   - A method with no edges to any other candidate forms a singleton cluster.
   - Clusters must be maximal: if A is connected to B and B is connected to C, all three belong to the same cluster.

7. **Generate a structured internal change plan.**
   Reason through the full scope of changes required to resolve the bug. Produce a numbered sequence of concrete change steps. Each step must specify:
   - The exact modification required and its rationale (e.g., "In `getConflictManager`, replace the fallback to the global default conflict manager with a lookup by `ModuleId` from the settings object, so per-module conflict manager configuration is honored")
   - The class name and method name to be changed
   - Any dependent downstream or parallel changes implied (e.g., "In `LatestConflictManager.toString`, replace direct access to `_strategy` with a call to `getStrategy()` to ensure the lazily-resolved strategy is used and null is not returned")

   Change plan derivation rules:
   - Always produce at least one step derived directly from the explicit fix suggestion in `issue_description`.
   - Produce a dedicated step for every method or class name called out in `issue_description` as needing a change.
   - Add further steps by reasoning about what other methods would produce incorrect behavior after the primary fix is applied to the seed method (e.g., callers whose logic depends on the old return semantics, helper methods with related defects called out in the same report).
   - Each step must name a concrete class and method, not a vague category.

8. **Predict impacted methods within each dependence cluster.**
   Process each cluster from Step 6 independently. For every method in the cluster, assess whether it belongs in the impact set using the following criteria:

   **Include** a method if any of the following holds:
   - It is the direct target of a change step from Step 7 (the step names its class and method).
   - Its behavior or output will become incorrect after the seed method's fix is applied, due to a semantic dependency on the changed behavior (e.g., it calls the seed method and relies on the old return value contract).
   - Its `<summary>` or `<source>` reveals that it implements a parallel pattern to the seed method's bug — the same defect in a sibling context — and this parallel was identified in Step 1 or Step 7.

   **Exclude** a method if:
   - Its only relationship to the change is that it calls the seed method and the fix does not alter the seed method's parameter types, return type, or thrown exceptions.
   - It is structurally connected but its `<summary>` and `<source>` show it operates on entirely unrelated data or concerns.

   **Self-consistency enforcement**: Perform the inclusion/exclusion assessment for each cluster independently at least 3 times. Retain only methods that are marked as impacted in every pass (intersection).
   - **Tie-breaking for 2-of-3 passes**: If a method appears impacted in 2 out of 3 passes, include it if and only if it is the direct target of a named change step from Step 7. Otherwise exclude it.
   - **Tie-breaking for 1-of-3 passes**: Always exclude.

9. **Aggregate across all clusters.**
   Take the union of every per-cluster impact subset produced in Step 8. This is the final predicted impact set.

10. **Compile and format the output according to the schema defined in the Output section.**
    Use the exact `<class name="...">` and `<method name="...">` attribute values from the repository XML for every entry. Return an empty array if the aggregated impact set is empty after excluding the seed method.

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- Do not include the seed method (the method named by `seed_method` located in the file named by `seed_file`) in `impacted_methods`.
- Format every element of `impacted_methods` exactly as `"ClassName,methodName"` using the exact names from the `repository` XML's `<class name="...">` and `<method name="...">` attributes, with no spaces around the comma.
- Only include methods that appear explicitly in the provided `repository` XML.
- Give weight to methods and classes explicitly named in `issue_description` as requiring changes, even if they are not structurally reachable from the seed method via calling dependencies.
- If no methods beyond the seed are impacted, return `"impacted_methods": []`.
- Output only the final JSON object with no additional keys, explanations, or reasoning traces.
- Follow the Steps above in order as your internal reasoning process.
"""