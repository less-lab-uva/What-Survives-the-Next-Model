# Note on Annotation

This document supplements the dataset section of our paper.  
It provides detailed information on the annotation objectives, guiding principles, annotator workflow, and inter-annotator agreement used in constructing the datasets.

## 0. Dataset
We conduct experiments on six datasets, with their statistics summarized as follows:
- **Functional Scenario Descriptions (FSD)** comprises 116 natural language descriptions from embedded systems, encompassing deeply nested functional behaviors such as device control, data processing, and fault handling.
- **Real Automotive Case (RAC)** contains 20 requirement scenarios from the automotive domain, representing typical control logic and communication processes.
- **PURE Dataset (PURE)** [\[Public Requirements Documents\]](https://zenodo.org/records/1414117) consists of 79 documents across multiple application domains and formats.
- **Business Process Dataset (BP)** [\[bussiness-process\]](https://github.com/lwx142857/bussiness-process) includes 30 examples of business software requirements, covering a range of operational scenarios.
- **User Stories Dataset (US)** [\[Requirements data sets (user stories)\]](https://zenodo.org/records/13880060) comprises 22 sets of user stories collected from various open-source projects, reflecting typical agile requirements.
- **LM Challenges (LMC)** [\[The Ten Lockheed Martin Cyber-Physical Challenges\]](https://github.com/hbourbouh/lm_challenges) features 10 requirements documents from the cyber-physical systems domain.

---

## 1. Annotation Goal

The goal of the annotation process is to **manually write the corresponding PlantUML activity diagram code** for each natural-language requirement text.  
Each diagram precisely captures the behavioral logic of the requirement while maintaining atomicity and structural consistency.

---

## 2. Annotation Hints and Modeling Principles
All annotators followed a standardized guideline to ensure consistent interpretation and modeling of behavioral information.
### General Principles
- **Activity atomicity:** Each activity should correspond to a single verb-triggered event (e.g., *"user logs in"*, *"system sends response"*).  
  Avoid compound actions such as *"check and save data"*—split them into separate atomic activities.
- **Control structures:** Express logical relations using PlantUML constructs:
  - `if ... else` for conditions  
  - `switch` / `case` for multi-branch conditions  
  - `fork ... fork again` for parallel flows  
  - `repeat` / `repeat while` for loops  
- **Visualization check:** Annotators may preview their code using the official [PlantUML Web Server](https://plantuml.com) to confirm that the rendered structure matches the intended behavioral logic.
- **Uncertain annotations:**  
  If an element cannot be confidently labeled, highlight it in **red** (e.g., `<font color="red">uncertain_activity</font>`) and skip it temporarily.  
  Record such cases in the shared tracking sheet, providing a short note explaining the uncertainty.

Reference: [PlantUML](https://plantuml.com/en/guide) 

---

## 3. Annotator Team and Expertise

The annotation was performed by **three domain experts** specializing in *software engineering* and *behavioral modeling*.  
Each annotator has prior experience with UML activity diagrams and textual requirements analysis.  
All annotators contributed to guideline refinement through iterative feedback and pilot trials.

---

## 4. Annotation Procedure

1. Each annotator independently labeled a subset of the data using the standardized PlantUML format.  
2. A shared subset of samples was annotated by all three experts to measure consistency.  
3. The annotations were cross-reviewed, and any discrepancies were discussed until consensus was reached.  
4. The finalized diagrams were validated syntactically (via PlantUML rendering) and semantically (for consistency with the textual requirements).  

---

## 5. Inter-Annotator Agreement

Inter-annotator agreement was quantified using **Cohen’s kappa** on the overlapping subset of annotations.  
The agreement consistently **exceeded 0.8 across all annotation dimensions**.

| Annotation Dimension | Cohen’s κ | Agreement Level |
|----------------------|-----------|----------------|
| Activity Extraction | 0.83 | High |
| Relation Labeling | 0.81 | High |
| Nested Control Structure Identification | 0.87 | High |

Discrepancies were generally caused by differences in interpreting nested or parallel behaviors and were resolved through group discussion.
