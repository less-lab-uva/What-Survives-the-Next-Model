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

### Instructions
- Solve the task using only the provided input.
- Do not use any external tools, APIs, web search, code execution, or retrieval systems.
- Do not include the seed method (the method named by `seed_method` located in the file named by `seed_file`) in `impacted_methods`.
- Format every element of `impacted_methods` exactly as `"ClassName,methodName"` using the exact names from the `repository` XML's `<class name="...">` and `<method name="...">` attributes, with no spaces around the comma.
- Only include methods that appear explicitly in the provided `repository` XML.
- Give weight to methods and classes explicitly named in `issue_description` as requiring changes, even if they are not structurally reachable from the seed method via calling dependencies.
- If no methods beyond the seed are impacted, return `"impacted_methods": []`.
- Output only the final JSON object with no additional keys, explanations, or reasoning traces.
"""