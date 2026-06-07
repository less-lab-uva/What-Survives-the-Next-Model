import json
import llm_prompt
import spot
import pandas as pd
from spot_utils import *
from tqdm import tqdm
import itertools
from pydantic import BaseModel
from typing import Literal
from typing import Optional
import os
import re

DATA_HOME_DIR = os.getenv("DATA_HOME_DIR")


with open(DATA_HOME_DIR+"/psp_dict.json", "r") as json_file:
    structnl_to_ltl_dict = json.load(json_file)

prefix_nl_template_str = \
"""
To produce the structured natural language property, you compose it from a set of templates.
If the chosen option contains boolean expression placeholders (i.e., bool_exp1, bool_exp2, bool_exp3, bool_exp4, bool_exp5, bool_exp6, bool_exp7), you need to produce boolean expressions that will replace the placeholders.
Boolean expressions can only contain boolean operators (e.g., !, &, |, ->, <->) and can only atomic propositions (NO NUMERICAL COMPARISON OPERATORS ALLOWED)
"""

class StructuredNLResult(BaseModel):
    explanation: str
    decision1: Literal[
    "Globally, _ABSTRACT_VAR1_",
    "Before bool_exp2, _ABSTRACT_VAR1_",
    "After bool_exp1, _ABSTRACT_VAR1_",
    "Between bool_exp1 and bool_exp2, _ABSTRACT_VAR1_",
    "After bool_exp1 until bool_exp2, _ABSTRACT_VAR1_",
    ]
    bool_exp1: str
    bool_exp2: str
    """
    decision2_abs: Literal[
    "it is never the case that bool_exp3 holds _TIME0_", #absence
    "it is always the case that bool_exp3 holds _TIME0_", #universality
    "bool_exp3 eventually holds _TIME0_", #existence
    "once bool_exp3 becomes satisfied it remains so for at least N_DURATION1 time units", #minduration
    "once bool_exp3 becomes satisfied it remains so for less than N_DURATION1 time units", #maxduration
    "bool_exp3 holds repeatedly every N_DURATION1 time units", #recurrence
    
    "if bool_exp3 holds, then it must have been the case that bool_exp4 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds", #timed precedence
    "if bool_exp3 holds, then it must have been the case that bool_exp4 has occurred before bool_exp3 holds", #precedence
    "bool_exp3 holds without interruption until bool_exp4 holds _TIME0_", #Until
    "if bool_exp3 has occurred, then in response bool_exp4 eventually holds _TIME0_ _CONSTRAINT0_", #response
    "if bool_exp3 has occurred, then in response bool_exp4 holds continually _TIME0_", #responseInvariance
    
    ##"bool_exp3 holds after N_DURATION0 time units", #transientState
    ##"bool_exp3 holds in the long run", #SteadyState
    
    "if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds", #timed precedenceChain1-2, error
    "if bool_exp4 and afterwards bool_exp5 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds", #precedenceChain1-2
    "if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 _UPPERTIME1_ have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds", #timed precedenceChain2-1
    "if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 have occurred before bool_exp3 holds", #precedenceChain2-1
    "if bool_exp3 has occurred, then in response _TIME0_ _CONSTRAINT0_ bool_exp4 followed by bool_exp5 _TIME1_ _CONSTRAINT1_ eventually holds", #responseChain1-2
    "if bool_exp4 followed by bool_exp5 _TIME1_ _CONSTRAINT1_ have occurred, then in response bool_exp3 eventually holds _TIME0_ _CONSTRAINT0_", #responseChain2-1, error
    ]
    
    TIME0: Literal[" ","within N_DURATION1 time units","after N_DURATION0 time units","between N_DURATION0 and N_DURATION1 time units",]

    TIME1: Literal[" ","within N_DURATION3 time units","after N_DURATION2 time units","between N_DURATION2 and N_DURATION3 time units",]

    CONSTRAINT0: Literal[" ","without bool_exp6 holding in between"]
    CONSTRAINT1: Literal[" ","without bool_exp7 holding in between"]
    UPPERTIME1: Literal[" ", "within N_DURATION1 time units",]
    """
    decision2: Literal['it is never the case that bool_exp3 holds',
 'it is never the case that bool_exp3 holds within N_DURATION1 time units',
 'it is never the case that bool_exp3 holds after N_DURATION0 time units',
 'it is never the case that bool_exp3 holds between N_DURATION0 and N_DURATION1 time units',
 'it is always the case that bool_exp3 holds',
 'it is always the case that bool_exp3 holds within N_DURATION1 time units',
 'it is always the case that bool_exp3 holds after N_DURATION0 time units',
 'it is always the case that bool_exp3 holds between N_DURATION0 and N_DURATION1 time units',
 'bool_exp3 eventually holds',
 'bool_exp3 eventually holds within N_DURATION1 time units',
 'bool_exp3 eventually holds after N_DURATION0 time units',
 'bool_exp3 eventually holds between N_DURATION0 and N_DURATION1 time units',
 'once bool_exp3 becomes satisfied it remains so for at least N_DURATION1 time units',
 'once bool_exp3 becomes satisfied it remains so for less than N_DURATION1 time units',
 'bool_exp3 holds repeatedly every N_DURATION1 time units',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 has occurred before bool_exp3 holds',
 'bool_exp3 holds without interruption until bool_exp4 holds',
 'bool_exp3 holds without interruption until bool_exp4 holds within N_DURATION1 time units',
 'bool_exp3 holds without interruption until bool_exp4 holds after N_DURATION0 time units',
 'bool_exp3 holds without interruption until bool_exp4 holds between N_DURATION0 and N_DURATION1 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds without bool_cnt_exp3 holding in between',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds within N_DURATION1 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds within N_DURATION1 time units without bool_cnt_exp3 holding in between',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds after N_DURATION0 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds after N_DURATION0 time units without bool_cnt_exp3 holding in between',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds between N_DURATION0 and N_DURATION1 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds between N_DURATION0 and N_DURATION1 time units without bool_cnt_exp3 holding in between',
 'if bool_exp3 has occurred, then in response bool_exp4 holds continually',
 'if bool_exp3 has occurred, then in response bool_exp4 holds continually within N_DURATION1 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 holds continually after N_DURATION0 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 holds continually between N_DURATION0 and N_DURATION1 time units',
 'if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds',
 'if bool_exp4 and afterwards bool_exp5 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 have occurred before bool_exp3 holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 eventually holds',
 'if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds',
 'if bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 have occurred before bool_exp3 holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 eventually holds',
 'if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds',
 'if bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 have occurred before bool_exp3 holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 eventually holds',
 'if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units and afterwards bool_exp8 within N_DURATION9 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds',
 'if bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 and afterwards bool_exp8 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units and afterwards bool_exp8 within N_DURATION9 time units have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 and afterwards bool_exp8 have occurred before bool_exp3 holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between followed by bool_exp8 within N_DURATION9 time units without bool_cnt_exp7 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units followed by bool_exp8 within N_DURATION9 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between followed by bool_exp8 without bool_cnt_exp7 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 followed by bool_exp8 eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between followed by bool_exp8 within N_DURATION9 time units without bool_cnt_exp7 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units followed by bool_exp8 within N_DURATION9 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between followed by bool_exp8 without bool_cnt_exp7 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 followed by bool_exp8 eventually holds',
 'if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units and afterwards bool_exp8 within N_DURATION9 time units and afterwards bool_exp9 within N_DURATION11 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds',
 'if bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 and afterwards bool_exp8 and afterwards bool_exp9 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units and afterwards bool_exp8 within N_DURATION9 time units and afterwards bool_exp9 within N_DURATION11 time units have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 and afterwards bool_exp8 and afterwards bool_exp9 have occurred before bool_exp3 holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between followed by bool_exp8 within N_DURATION9 time units without bool_cnt_exp7 holding in between followed by bool_exp9 within N_DURATION11 time units without bool_cnt_exp8 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units followed by bool_exp8 within N_DURATION9 time units followed by bool_exp9 within N_DURATION11 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between followed by bool_exp8 without bool_cnt_exp7 holding in between followed by bool_exp9 without bool_cnt_exp8 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 followed by bool_exp8 followed by bool_exp9 eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between followed by bool_exp8 within N_DURATION9 time units without bool_cnt_exp7 holding in between followed by bool_exp9 within N_DURATION11 time units without bool_cnt_exp8 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units followed by bool_exp8 within N_DURATION9 time units followed by bool_exp9 within N_DURATION11 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between followed by bool_exp8 without bool_cnt_exp7 holding in between followed by bool_exp9 without bool_cnt_exp8 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 followed by bool_exp8 followed by bool_exp9 eventually holds']
    
    bool_exp3: str
    bool_exp4: str
    bool_exp5: str
    bool_exp6: str
    bool_exp7: str
    bool_exp8: str
    bool_exp9: str
    bool_cnt_exp3: str
    bool_cnt_exp4: str
    bool_cnt_exp5: str
    bool_cnt_exp6: str
    bool_cnt_exp7: str
    bool_cnt_exp8: str
    N_DURATION0: Optional[int]
    N_DURATION1: Optional[int]
    N_DURATION2: Optional[int]
    N_DURATION3: Optional[int]
    N_DURATION4: Optional[int]
    N_DURATION5: Optional[int]
    N_DURATION6: Optional[int]
    N_DURATION7: Optional[int]
    N_DURATION8: Optional[int]
    N_DURATION9: Optional[int]
    N_DURATION10: Optional[int]
    N_DURATION11: Optional[int]
    decision1_substring: str
    decision2_substring: str

class StructuredNLTranslations(BaseModel):
    translations: list[StructuredNLResult]

class LTLTemplateResult(BaseModel):
    explanation: str
    chosen_template_ID: int
    bool_exp1: str
    bool_exp2: str
    bool_exp3: str
    bool_exp4: str
    bool_exp5: str
    bool_exp6: str
    bool_exp7: str
    bool_exp8: str
    bool_exp9: str
    bool_cnt_exp3: str
    bool_cnt_exp4: str
    bool_cnt_exp5: str
    bool_cnt_exp6: str
    bool_cnt_exp7: str
    bool_cnt_exp8: str
    N_DURATION0: Optional[int]
    N_DURATION1: Optional[int]
    N_DURATION2: Optional[int]
    N_DURATION3: Optional[int]
    N_DURATION4: Optional[int]
    N_DURATION5: Optional[int]
    N_DURATION6: Optional[int]
    N_DURATION7: Optional[int]
    N_DURATION8: Optional[int]
    N_DURATION9: Optional[int]
    N_DURATION10: Optional[int]
    N_DURATION11: Optional[int]

class LTLTemplateTranslations(BaseModel):
    translations: list[LTLTemplateResult]

structnl_dcmp_format_str = \
"""
Inputs consist of:
1. unstructured natural language (string)
2. atomic proposition + descriptions (dictionary mapping names to descriptions). You must use these atomic propositions to define the boolean expressions and account for their descriptions in your decisions.
3. nl_substring_to_decision_map. The option you choose for decision1 and decision2 should represent its corresponding substrings of the input unstructured natural language.

The Outputs consist of the arguments to the produce_structured_nl function and substrings of the input that pertain to each decision:
1. an explanation of the produced LTL property and how it captures the input_natural_language
2. decision1 (should contain its placeholders names)
3. bool_exp1
4. bool_exp2
4. decision2_abs (should contain its placeholders names)
5. TIME0
6. TIME1
7. CONSTRAINT0
8. CONSTRAINT1
9. UPPERTIME1
10. bool_exp3
11. bool_exp4
12. bool_exp5
13. bool_exp6
14. bool_exp7
15. N_DURATION0
16. N_DURATION1
17. N_DURATION2
18. N_DURATION3
19. decision1_substring (substring of input_natural_language that pertains to decision1)
20. decision2_substring (substring of input_natural_language that pertains to decision2)
"""

structnl_format_str = \
"""
Inputs consist of:
1. unstructured natural language (string)
2. atomic proposition + descriptions (dictionary mapping names to descriptions). You must use these atomic propositions to define the boolean expressions and account for their descriptions in your decisions.

The Outputs consist of the arguments to the produce_structured_nl function and substrings of the input that pertain to each decision:
1. an explanation of the produced LTL property and how it captures the input_natural_language
2. decision1 (should contain its placeholders names)
3. bool_exp1
4. bool_exp2
5. decision2 (should contain its placeholders names)
6. bool_exp3
7. bool_exp4
8. bool_exp5
9. bool_exp6
10. bool_exp7
11. bool_exp8
12. bool_exp9
13. bool_cnt_exp3
14. bool_cnt_exp4
15. bool_cnt_exp5
16. bool_cnt_exp6
17. bool_cnt_exp7
18. bool_cnt_exp8
19. N_DURATION0
20. N_DURATION1
21. N_DURATION2
22. N_DURATION3
23. N_DURATION4
24. N_DURATION5
25. N_DURATION6
26. N_DURATION7
27. N_DURATION8
28. N_DURATION9
29. N_DURATION10
30. N_DURATION11
19. decision1_substring (substring of input_natural_language that pertains to decision1)
20. decision2_substring (substring of input_natural_language that pertains to decision2)
"""

structnl_format_str = \
"""
Inputs consist of:
1. unstructured natural language (string)
2. atomic proposition + descriptions (dictionary mapping names to descriptions). You must use these atomic propositions to define the boolean expressions and account for their descriptions in your decisions.

The Outputs consist of the arguments to the produce_structured_nl function and substrings of the input that pertain to each decision:
1. an explanation of the produced LTL property and how it captures the input_natural_language
2. decision1 (should contain its placeholders names)
3. bool_exp1
4. bool_exp2
5. decision2 (should contain its placeholders names)
6. bool_exp3
7. bool_exp4
8. bool_exp5
9. bool_exp6
10. bool_exp7
11. bool_exp8
12. bool_exp9
13. bool_cnt_exp3
14. bool_cnt_exp4
15. bool_cnt_exp5
16. bool_cnt_exp6
17. bool_cnt_exp7
18. bool_cnt_exp8
19. N_DURATION0
20. N_DURATION1
21. N_DURATION2
22. N_DURATION3
23. N_DURATION4
24. N_DURATION5
25. N_DURATION6
26. N_DURATION7
27. N_DURATION8
28. N_DURATION9
29. N_DURATION10
30. N_DURATION11
31. decision1_substring (substring of input_natural_language that pertains to decision1)
32. decision2_substring (substring of input_natural_language that pertains to decision2)
"""

ltltemplate_format_str =\
"""
Inputs consist of:
1. unstructured natural language
2. atomic proposition + descriptions (dictionary mapping names to descriptions). You must use these atomic propositions to define the boolean expressions and account for their descriptions in your choice of LTL template.

The Outputs consist of:
1. an explanation of the produced LTL property and how it captures the input_natural_language
2. chosen_template_ID (integer) - The index of the chosen LTL template
3. bool_exp1
4. bool_exp2
5. bool_exp3
6. bool_exp4
7. bool_exp5
8. bool_exp6
9. bool_exp7
10. bool_exp8
11. bool_exp9
12. bool_cnt_exp3
13. bool_cnt_exp4
14. bool_cnt_exp5
15. bool_cnt_exp6
16. bool_cnt_exp7
17. bool_cnt_exp8
18. N_DURATION0
19. N_DURATION1
20. N_DURATION2
21. N_DURATION3
22. N_DURATION4
23. N_DURATION5
24. N_DURATION6
25. N_DURATION7
26. N_DURATION8
27. N_DURATION9
28. N_DURATION10
29. N_DURATION11
"""

decision1_options = StructuredNLResult.model_json_schema()['properties']['decision1']['enum']

decision2_options = ['it is never the case that bool_exp3 holds',
 'it is never the case that bool_exp3 holds within N_DURATION1 time units',
 'it is never the case that bool_exp3 holds after N_DURATION0 time units',
 'it is never the case that bool_exp3 holds between N_DURATION0 and N_DURATION1 time units',
 'it is always the case that bool_exp3 holds',
 'it is always the case that bool_exp3 holds within N_DURATION1 time units',
 'it is always the case that bool_exp3 holds after N_DURATION0 time units',
 'it is always the case that bool_exp3 holds between N_DURATION0 and N_DURATION1 time units',
 'bool_exp3 eventually holds',
 'bool_exp3 eventually holds within N_DURATION1 time units',
 'bool_exp3 eventually holds after N_DURATION0 time units',
 'bool_exp3 eventually holds between N_DURATION0 and N_DURATION1 time units',
 'once bool_exp3 becomes satisfied it remains so for at least N_DURATION1 time units',
 'once bool_exp3 becomes satisfied it remains so for less than N_DURATION1 time units',
 'bool_exp3 holds repeatedly every N_DURATION1 time units',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 has occurred before bool_exp3 holds',
 'bool_exp3 holds without interruption until bool_exp4 holds',
 'bool_exp3 holds without interruption until bool_exp4 holds within N_DURATION1 time units',
 'bool_exp3 holds without interruption until bool_exp4 holds after N_DURATION0 time units',
 'bool_exp3 holds without interruption until bool_exp4 holds between N_DURATION0 and N_DURATION1 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds without bool_cnt_exp3 holding in between',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds within N_DURATION1 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds within N_DURATION1 time units without bool_cnt_exp3 holding in between',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds after N_DURATION0 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds after N_DURATION0 time units without bool_cnt_exp3 holding in between',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds between N_DURATION0 and N_DURATION1 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 eventually holds between N_DURATION0 and N_DURATION1 time units without bool_cnt_exp3 holding in between',
 'if bool_exp3 has occurred, then in response bool_exp4 holds continually',
 'if bool_exp3 has occurred, then in response bool_exp4 holds continually within N_DURATION1 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 holds continually after N_DURATION0 time units',
 'if bool_exp3 has occurred, then in response bool_exp4 holds continually between N_DURATION0 and N_DURATION1 time units',
 'if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds',
 'if bool_exp4 and afterwards bool_exp5 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 have occurred before bool_exp3 holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 eventually holds',
 'if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds',
 'if bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 have occurred before bool_exp3 holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 eventually holds',
 'if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds',
 'if bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 have occurred before bool_exp3 holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 eventually holds',
 'if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units and afterwards bool_exp8 within N_DURATION9 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds',
 'if bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 and afterwards bool_exp8 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units and afterwards bool_exp8 within N_DURATION9 time units have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 and afterwards bool_exp8 have occurred before bool_exp3 holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between followed by bool_exp8 within N_DURATION9 time units without bool_cnt_exp7 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units followed by bool_exp8 within N_DURATION9 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between followed by bool_exp8 without bool_cnt_exp7 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 followed by bool_exp8 eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between followed by bool_exp8 within N_DURATION9 time units without bool_cnt_exp7 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units followed by bool_exp8 within N_DURATION9 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between followed by bool_exp8 without bool_cnt_exp7 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 followed by bool_exp8 eventually holds',
 'if bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units and afterwards bool_exp8 within N_DURATION9 time units and afterwards bool_exp9 within N_DURATION11 time units hold, then it must have been the case that bool_exp3 has occurred between N_DURATION0 and N_DURATION1 time units before bool_exp4 holds',
 'if bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 and afterwards bool_exp8 and afterwards bool_exp9 hold, then it must have been the case that bool_exp3 has occurred before bool_exp4 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 within N_DURATION3 time units and afterwards bool_exp6 within N_DURATION5 time units and afterwards bool_exp7 within N_DURATION7 time units and afterwards bool_exp8 within N_DURATION9 time units and afterwards bool_exp9 within N_DURATION11 time units have occurred between N_DURATION0 and N_DURATION1 time units before bool_exp3 holds',
 'if bool_exp3 holds, then it must have been the case that bool_exp4 and afterwards bool_exp5 and afterwards bool_exp6 and afterwards bool_exp7 and afterwards bool_exp8 and afterwards bool_exp9 have occurred before bool_exp3 holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between followed by bool_exp8 within N_DURATION9 time units without bool_cnt_exp7 holding in between followed by bool_exp9 within N_DURATION11 time units without bool_cnt_exp8 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units followed by bool_exp8 within N_DURATION9 time units followed by bool_exp9 within N_DURATION11 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between followed by bool_exp8 without bool_cnt_exp7 holding in between followed by bool_exp9 without bool_cnt_exp8 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 followed by bool_exp8 followed by bool_exp9 eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 within N_DURATION3 time units without bool_cnt_exp4 holding in between followed by bool_exp6 within N_DURATION5 time units without bool_cnt_exp5 holding in between followed by bool_exp7 within N_DURATION7 time units without bool_cnt_exp6 holding in between followed by bool_exp8 within N_DURATION9 time units without bool_cnt_exp7 holding in between followed by bool_exp9 within N_DURATION11 time units without bool_cnt_exp8 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response within N_DURATION1 time units bool_exp4 followed by bool_exp5 within N_DURATION3 time units followed by bool_exp6 within N_DURATION5 time units followed by bool_exp7 within N_DURATION7 time units followed by bool_exp8 within N_DURATION9 time units followed by bool_exp9 within N_DURATION11 time units eventually holds',
 'if bool_exp3 has occurred, then in response without bool_cnt_exp3 holding in between bool_exp4 followed by bool_exp5 without bool_cnt_exp4 holding in between followed by bool_exp6 without bool_cnt_exp5 holding in between followed by bool_exp7 without bool_cnt_exp6 holding in between followed by bool_exp8 without bool_cnt_exp7 holding in between followed by bool_exp9 without bool_cnt_exp8 holding in between eventually holds',
 'if bool_exp3 has occurred, then in response bool_exp4 followed by bool_exp5 followed by bool_exp6 followed by bool_exp7 followed by bool_exp8 followed by bool_exp9 eventually holds']

decision_to_item_list = \
{
    'decision1': ['bool_exp1', 'bool_exp2'],
    'decision2': ['bool_exp3',
    'bool_exp4',
    'bool_cnt_exp3',
    'N_DURATION0',
    'N_DURATION1',
    'bool_exp5',
    'bool_cnt_exp4',
    'N_DURATION2',
    'N_DURATION3',
    'bool_exp6',
    'bool_cnt_exp5',
    'N_DURATION4',
    'N_DURATION5',
    'bool_exp7',
    'bool_cnt_exp6',
    'N_DURATION6',
    'N_DURATION7',
    'bool_exp8',
    'bool_cnt_exp7',
    'N_DURATION8',
    'N_DURATION9',
    'bool_exp9',
    'bool_cnt_exp8',
    'N_DURATION10',
    'N_DURATION11']
}

df_option_names = ['pattern options','pattern bool exps','scope options', 'scope bool exps']

decision_order = ["decision1", "decision2"]

def extract_structnl_from_output(output):
    res = output["decision1"].replace("_ABSTRACT_VAR1_",output["decision2"])
    for decision,item_list in decision_to_item_list.items():
        for k in item_list:
            if k in output["decision1"] or k in output["decision2"]:
                res = res.replace(k,str(output[k]))
    return res

def check_nl2structnl_format(raw_output,ap_dict,dcmp=None):
    try:
        json_raw_output = json.loads(raw_output)
    except Exception as e:
        return f"{e}"
    try:
        obj = StructuredNLTranslations(**json_raw_output)
    except Exception as e:
        return f"invalid output format: {e}"
    for i in range(len(json_raw_output["translations"])):
        json_output = json_raw_output["translations"][i]
        err_msg = check_nl2structnl_format_inner(json_output,ap_dict,dcmp=dcmp)
        if err_msg is not None:
            return f"please fix your output list after addressing the following problem in the {i}-th item: " + err_msg
    return None

"""
def get_decision2_option(output):
    cur_option = output["decision2_abs"]
    cur_option = cur_option.replace("_TIME0_",output["TIME0"])
    cur_option = cur_option.replace("_TIME1_",output["TIME1"])
    cur_option = cur_option.replace("_CONSTRAINT0_",output["CONSTRAINT0"])
    cur_option = cur_option.replace("_CONSTRAINT1_",output["CONSTRAINT1"])
    cur_option = cur_option.replace("_UPPERTIME1_",output["UPPERTIME1"])
    return " ".join(cur_option.split())
"""

def check_nl2structnl_format_inner(json_output,ap_dict,dcmp=None):
    #json_output["decision2"] = get_decision2_option(json_output)
    assert json_output["decision2"] in decision2_options
    bool_var_msg = f"Boolean expressions must only contain variables from the following: {str(list(ap_dict.keys()))}"
    for decision,item_list in decision_to_item_list.items():
        for k in item_list:
            if k in json_output[decision]:
                if "N_DURATION" not in k:
                    err_msg = check_boolean_formula(json_output[k],ret_err_msg=True)
                    if err_msg != "":
                        return f"{k} is not a valid boolean expression:\n{err_msg}"
                    for var in get_variables_from_formula(json_output[k]):
                        if var not in ap_dict:
                            return f"{k}: {var} is not a valid atomic proposition. {bool_var_msg}"
                else:
                    if not check_valid_nonnegative_integer(json_output[k]):
                        return f"{k}: {json_output[k]} is not a valid non-zero integer"
    return None

def format_raw_output(raw_output,ap_dict):
    output_list = []
    json_raw_output = json.loads(raw_output)
    for json_output in json_raw_output["translations"]:
        try:
            if check_nl2structnl_format_inner(json_output,ap_dict,dcmp=None) is None and check_ltl_formula(get_ltl_from_output(json_output)):
                json_output["output_structured_natural_language"] = extract_structnl_from_output(json_output)
                json_output["output_LTL"] = get_ltl_from_output(json_output)
                output_list.append(json_output)
        except Exception as e:
            print(e)
    return output_list

def get_syntax_unique_list(output_list):
    seen = set()
    res = []
    for output in output_list:
        if output["output_structured_natural_language"] not in seen:
            res.append(output)
        seen.add(output["output_structured_natural_language"])
    return res

def get_nl2structnl_translation(input_nl,ap_dict,model="gpt-4o-mini",max_retry=1,k=1,dcmp=None,prev_outputs=None,mode=None):
    if mode is None:#model == "gemini-1.5-flash-001":
        k = 1
        prev_outputs=None
        #if prev_outputs is not None:
        #    prev_outputs = prev_outputs[-1:]
    elif mode == "reflect":
        k = min([k,50])
        prev_outputs = get_syntax_unique_list(prev_outputs)
    else:
        assert False, "nl2structnl translation mode not found!"
    system_prompt, user_prompt = get_structNL_prompt_simple(input_nl,ap_dict,dcmp=dcmp,k=k,prev_outputs=prev_outputs)
    output = llm_prompt.prompt_loop(system_prompt, user_prompt, model, max_retry, check_output_func=check_nl2structnl_format, schema=StructuredNLTranslations, ap_dict=ap_dict,dcmp=dcmp)
    if output is not None:
        output = format_raw_output(output,ap_dict)
        return output
    else:
        return []

def get_structNL_prompt_simple(input_nl,ap_dict,dcmp=None,prev_outputs=None,k=10):
    init_cmd_str = "You are an expert in Linear Temporal Logic and requirements engineering. Your job is to translate natural language requirements to structured natural language that capture the intents of the requirements.\n"
    #init_cmd_str += "The structured natural language has an underlying mapping to Linear Temporal Logic.\n"

    
    nl_template_str = prefix_nl_template_str
    #nl_template_str += "\nThe following list the possible options for decision1 and decision2:\n"
    #nl_template_str += decision_options_str
    #nl_template_str += "\nThe following python code snippet defines how the options you choose combine into the structured natural language.\n"
    #nl_template_str += code_snippet

    input_str = "{\n"
    input_str += f"\"input_natural_language\":\"{input_nl}\",\n"
    input_str += f"\"atomic_propositions\":{json.dumps(ap_dict)},\n"
    if dcmp is not None:
        inverted_dict = {}
        for key, value in dcmp.items():
            inverted_dict.setdefault(value, []).append(key)
        input_str += f"\"nl_substring_to_decision_map\":{json.dumps(inverted_dict)}"
    input_str += "}\n"
    user_str_list = []
    #final_cmd_str = "Follow the above output JSON format to provide the translation for the following:\n"
    final_cmd_str = f"provide a list of the top {k} most likely translations (ordered by most likely first to least likely last) in the specified JSON format for the following:\n"
    user_str_list.append(final_cmd_str)
    user_str_list.append(input_str)
    
    if prev_outputs is not None and len(prev_outputs) > 0:
        prev_output_str = "IMPORTANT: You must produce structured natural language different from each in the following list:\n"
        #arg_list = ["decision1","decision2","decision3"]
        #arg_list = ["output_structured_natural_language"]
        arg_list = []
        for decision,item_list in decision_to_item_list.items():
            arg_list.append(decision)
            arg_list += item_list
        prev_output_str += json.dumps([dict((k,e[k]) for k in arg_list) for e in prev_outputs])
        #prev_output_str += "\nThe input_natural_language is ambiguous, please produce the next most likely alternative translations to the structured natural language."
        #prev_output_str += "\nIf you are confident, you may reuse the same as above."
        prev_output_str += "\nThe above are incorrect. Please produce translations to structured natural language that could capture the meaning of the input_natural_langauge."
        user_str_list = [prev_output_str] + user_str_list

    #system_prompt = "\n".join([init_cmd_str,nl_template_str,structnl_format_str,structnl_example_str])
    if dcmp is None:
        system_prompt = "\n".join([init_cmd_str,nl_template_str,structnl_format_str])
    else:
        system_prompt = "\n".join([init_cmd_str,nl_template_str,structnl_dcmp_format_str])
    user_prompt = "\n".join(user_str_list)
    return system_prompt, user_prompt

def get_structnl_to_ltl_template(decision1,decision2):
    cur_structnl = decision1.replace("_ABSTRACT_VAR1_",decision2)
    out_ltl = structnl_to_ltl_dict[cur_structnl]
    return out_ltl

def get_ltl_from_output(output,ltl_template=None):
    if ltl_template is None:
        res = get_structnl_to_ltl_template(decision1=output["decision1"],decision2=output["decision2"])
    else:
        res = ltl_template
    add_list = [f"N_DURATION{i*2+1}" for i in range(1,10)]
    for i in range(len(add_list)):
        key = " - ".join(["N_DURATION1 - N_DURATION0"] + add_list[:len(add_list)-i])
        if key in res:
            total_sum = output["N_DURATION1"] - output["N_DURATION0"]
            for j in range(len(add_list)-i):
                total_sum -= output[add_list[j]]
            res = res.replace(key,str(max(0,total_sum)))
    #if "N_DURATION1 - N_DURATION0 - N_DURATION3" in res:
    #    res = res.replace("N_DURATION1 - N_DURATION0 - N_DURATION3",str(max(0,(output["N_DURATION1"] - output["N_DURATION0"]) - output["N_DURATION3"])))
    for i in range(len(add_list)):
        key = " + ".join(["N_DURATION1"] + add_list[:len(add_list)-i])
        if key in res:
            print(key)
            total_sum = output["N_DURATION1"]
            for j in range(len(add_list)-i):
                total_sum += output[add_list[j]]
            res = res.replace(key,str(max(0,total_sum)))
    #if "N_DURATION1 + N_DURATION3" in res:
    #    res = res.replace("N_DURATION1 + N_DURATION3",str(output["N_DURATION1"] + output["N_DURATION3"]))
    if "N_DURATION1 - N_DURATION0" in res:
        res = res.replace("N_DURATION1 - N_DURATION0",str(output["N_DURATION1"] - output["N_DURATION0"]))
    for decision,item_list in decision_to_item_list.items():
        for k in item_list:
            if k in res: #and (k in output["decision1"] or k in output["decision2"]):
                if "N_DURATION" not in k:
                    cur_exp = spot.formula(output[k]).to_str(parenth=True)
                    if cur_exp == "1":
                        cur_exp = "TRUE"
                    elif cur_exp == "0":
                        cur_exp = "FALSE"
                    res = res.replace(k,f"({cur_exp})")
                else:
                    res = res.replace(k,str(output[k]))   
    #res = res.replace("[0,]","")
    res = expand_lowerbounded_always(res)
    res = expand_lowerbounded_eventually(res)
    res = expand_bounded_weak_until(res)
    res = expand_bounded_until(res)
    res = filter_ltl_formula(res) #unabbreviate weak until
    return res

def get_ltl_from_options(option_dict):
    res = get_structnl_to_ltl_template(
        decision1=option_dict["decision1"]["option"],
        decision2=option_dict["decision2"]["option"])
    add_list = [f"N_DURATION{i*2+1}" for i in range(1,10)]
    for i in range(len(add_list)):
        key = " - ".join(["N_DURATION1 - N_DURATION0"] + add_list[:len(add_list)-i])
        if key in res:
            total_sum = option_dict["decision2"]["N_DURATION1"] - option_dict["decision2"]["N_DURATION0"]
            for j in range(len(add_list)-i):
                total_sum -= option_dict["decision2"][add_list[j]]
            res = res.replace(key,str(max(0,total_sum)))
    #if "N_DURATION1 - N_DURATION0 - N_DURATION3" in res:
    #    res = res.replace("N_DURATION1 - N_DURATION0 - N_DURATION3",str(max(0,(option_dict["decision2"]["N_DURATION1"] - option_dict["decision2"]["N_DURATION0"]) - option_dict["decision2"]["N_DURATION3"])))
    for i in range(len(add_list)):
        key = " + ".join(["N_DURATION1"] + add_list[:len(add_list)-i])
        if key in res:
            print(key)
            total_sum = option_dict["decision2"]["N_DURATION1"]
            for j in range(len(add_list)-i):
                total_sum += option_dict["decision2"][add_list[j]]
            res = res.replace(key,str(max(0,total_sum)))
    #if "N_DURATION1 + N_DURATION3" in res:
    #    res = res.replace("N_DURATION1 + N_DURATION3",str(option_dict["decision2"]["N_DURATION1"] + option_dict["decision2"]["N_DURATION3"]))
    if "N_DURATION1 - N_DURATION0" in res:
        res = res.replace("N_DURATION1 - N_DURATION0",str(option_dict["decision2"]["N_DURATION1"] - option_dict["decision2"]["N_DURATION0"]))
    for decision,item_list in decision_to_item_list.items():
        for k in item_list:
            if k in res and k in option_dict[decision]["option"]:
                if "N_DURATION" not in k:
                    cur_exp = spot.formula(option_dict[decision][k]).to_str(parenth=True)
                    if cur_exp == "1":
                        cur_exp = "TRUE"
                    elif cur_exp == "0":
                        cur_exp = "FALSE"
                    res = res.replace(k,f"({cur_exp})")
                else:
                    res = res.replace(k,str(option_dict[decision][k]))   
    #res = res.replace("[0,]","")
    res = expand_lowerbounded_always(res)
    res = expand_lowerbounded_eventually(res)
    res = expand_bounded_weak_until(res)
    res = expand_bounded_until(res)
    res = filter_ltl_formula(res) #unabbreviate weak until
    return res    

def get_dcmp_map_from_row(df_row):
    col_name_map = \
    {
        "decision2_substring":"pattern substring",
        "decision1_substring":"scope substring",
    }
    substring_order = ['decision2_substring', 'decision1_substring']
    group_list = []
    visited_unassigned = set()
    for substring_label in substring_order:
        cur_substring = df_row[col_name_map[substring_label]]
        if pd.isna(cur_substring):
            visited_unassigned.add(substring_label)
        else:
            new_group = set([substring_label])
            new_group.update(visited_unassigned)
            group_list.append(new_group)
            visited_unassigned = set()
    if len(visited_unassigned) > 0:
        group_list[-1].update(visited_unassigned)

    dcmp = {}
    for group in group_list:
        found_not_nan = False
        for substring_label in group:
            cur_substring = df_row[col_name_map[substring_label]]
            if not pd.isna(cur_substring):
                found_not_nan = True
                break
        assert found_not_nan
        for substring_label in group:
            dcmp[substring_label] = cur_substring

    dcmp_list = []
    for decision in decision_order:
        if dcmp[decision+"_substring"] not in dcmp_list:
            dcmp_list.append(dcmp[decision+"_substring"])
    return dcmp, dcmp_list

def get_all_possible_decision_options_for_ex(output,MAX_DURATION=5):
    key_list = ["bool_exp1","bool_exp2","bool_exp3","bool_exp4","bool_exp5","bool_exp6","bool_exp7"]
    all_bools = []
    cur_ap_dict = {}
    for k in key_list:
        if output[k] is not None and check_boolean_formula(output[k]):
            all_bools.append(output[k])
            for var in get_variables_from_formula(output[k]):
                cur_ap_dict[var] = var
        else:
            all_bools.append(None)
    
    new_output_list = []
    for cur_bool in [all_bools]:
    #for cur_bool in [(output["bool_exp1"],output["bool_exp2"],output["bool_exp3"],output["bool_exp4"])]:
    #for bool_group in itertools.combinations(all_bools,4):
    #    for cur_bool in itertools.permutations(bool_group):
            for e in itertools.product(decision1_options,decision2_options):
                new_output = output.copy()
                new_output["bool_exp1"] = cur_bool[0]
                new_output["bool_exp2"] = cur_bool[1]
                new_output["bool_exp3"] = cur_bool[2]
                new_output["bool_exp4"] = cur_bool[3]
                new_output["bool_exp5"] = cur_bool[4]
                new_output["bool_exp6"] = cur_bool[5]
                new_output["bool_exp7"] = cur_bool[6]
                new_output["decision1"] = e[0]
                new_output["decision2"] = e[1]
                if check_nl2structnl_format_inner(new_output,cur_ap_dict) is None:
                    new_output_list.append(new_output)
    return new_output_list
    
##process bounded until

def unroll_bounded_until(a,b,t1,t2):
    res_list = []
    for i in range(t1,t2+1):
        if i-1 >= 0:
            res_list.append(f"(G[0,{i-1}] ({a}) & F[{i},{i}] ({b}))")
        else:
            res_list.append(f"(F[{i},{i}] ({b}))")
    return "( " + " | ".join(res_list) + " )"

def unroll_lowerbounded_until(a,b,t1):
    if t1 > 0:
        return f"( G[0,{t1}] ({a}) & F[{t1},{t1}] (({a}) U ({b})))"
    else:
        return f"( F[{t1},{t1}] (({a}) U ({b})))"        

def extract_bounded_until_intervals_with_substrings(ltl_formula):
    BOUND_UNTIL_RE = re.compile(r'U\[\s*([^,\]]+?)\s*,\s*([^\]]+?)\s*\]')
    return [
        (m.group(0), int(m.group(1).strip()), int(m.group(2).strip()))
        for m in BOUND_UNTIL_RE.finditer(ltl_formula)
    ]

def extract_lowerbounded_until_intervals_with_substrings(ltl_formula):
    LOWERBOUND_UNTIL_RE = re.compile(r'U\[\s*([^,\]]+?)\s*,\s*\]')
    return [
        (m.group(0), int(m.group(1).strip()))
        for m in LOWERBOUND_UNTIL_RE.finditer(ltl_formula)
    ]

def get_first_wellformed_subf(ltl_formula,reverse=False):
    parenth_count = 0
    found_parenth = False
    if not reverse:
        i = 0
        incr = 1
        last_val = len(ltl_formula)-1
    else:
        i = len(ltl_formula) - 1
        incr = -1
        last_val = 0
    while True:
        if ltl_formula[i] == "(":
            parenth_count += 1
            found_parenth = True
        elif ltl_formula[i] == ")":
            parenth_count -= 1
            found_parenth = True
        if parenth_count == 0 and found_parenth:
            if not reverse:
                return ltl_formula[:i+1]
            else:
                return ltl_formula[i:]
        if i == last_val:
            break
        i += incr
    assert False, "could not find subformula surrounded by parentheses!"

def get_binary_op_arguments(ltl_formula,op):
    arg1 = get_first_wellformed_subf(ltl_formula.split(op)[0],reverse=True)
    arg2 = get_first_wellformed_subf(op.join(ltl_formula.split(op)[1:]))
    return arg1, arg2

def expand_bounded_until(ltl_formula):
    res = ltl_formula
    for full_op,t1,t2 in extract_bounded_until_intervals_with_substrings(ltl_formula):
        if full_op in res:
            arg1, arg2 = get_binary_op_arguments(res,full_op)
            res = res.replace(arg1 + full_op + arg2,unroll_bounded_until(arg1,arg2,t1,t2))
    for full_op, t1 in extract_lowerbounded_until_intervals_with_substrings(ltl_formula):
        if full_op in res:
            arg1, arg2 = get_binary_op_arguments(res,full_op)
            res = res.replace(arg1 + full_op + arg2,unroll_lowerbounded_until(arg1,arg2,t1))
    return res

def extract_bounded_weak_until_intervals_with_substrings(ltl_formula):
    BOUND_WEAK_UNTIL_RE = re.compile(r'W\[\s*([^,\]]+?)\s*,\s*([^\]]+?)\s*\]')
    return [
        (m.group(0), int(m.group(1).strip()), int(m.group(2).strip()))
        for m in BOUND_WEAK_UNTIL_RE.finditer(ltl_formula)
    ]

def extract_lowerbounded_weak_until_intervals_with_substrings(ltl_formula):
    LOWERBOUND_WEAK_UNTIL_RE = re.compile(r'W\[\s*([^,\]]+?)\s*,\s*\]')
    return [
        (m.group(0), int(m.group(1).strip()))
        for m in LOWERBOUND_WEAK_UNTIL_RE.finditer(ltl_formula)
    ]

def expand_bounded_weak_until(ltl_formula):
    res = ltl_formula
    for full_op,t1,t2 in extract_bounded_weak_until_intervals_with_substrings(ltl_formula):
        if full_op in res:
            arg1, arg2 = get_binary_op_arguments(res,full_op)
            res = res.replace(arg1 + full_op + arg2,f"( ({arg1} U[{t1},{t2}] {arg2}) | G[0,{t2}] ({arg1}) )")
    for full_op,t1 in extract_lowerbounded_weak_until_intervals_with_substrings(ltl_formula):
        if full_op in res:
            arg1, arg2 = get_binary_op_arguments(res,full_op)
            res = res.replace(arg1 + full_op + arg2,f"( ({arg1} U[{t1},] {arg2}) | G ({arg1}) )")
    return res

## process bounded G
def extract_lowerbounded_always_intervals_with_substrings(ltl_formula):
    LOWERBOUND_ALWAYS_RE = re.compile(r'G\[\s*([^,\]]+?)\s*,\s*\]')
    return [
        (m.group(0), int(m.group(1).strip()))
        for m in LOWERBOUND_ALWAYS_RE.finditer(ltl_formula)
    ]
def expand_lowerbounded_always(ltl_formula):
    res = ltl_formula
    for full_op, t1 in extract_lowerbounded_always_intervals_with_substrings(ltl_formula):
        res = res.replace(full_op,"X "*t1 + "G")
    return res

##process bounded F
def extract_lowerbounded_eventually_intervals_with_substrings(ltl_formula):
    LOWERBOUND_EVENTUALLY_RE = re.compile(r'F\[\s*([^,\]]+?)\s*,\s*\]')
    return [
        (m.group(0), int(m.group(1).strip()))
        for m in LOWERBOUND_EVENTUALLY_RE.finditer(ltl_formula)
    ]
def expand_lowerbounded_eventually(ltl_formula):
    res = ltl_formula
    for full_op, t1 in extract_lowerbounded_eventually_intervals_with_substrings(ltl_formula):
        res = res.replace(full_op,"X "*t1 + "F")
    return res

fretish_scope_map = \
{
    "_ABSTRACT_VAR1_":None,
    "after bool_exp1, _ABSTRACT_VAR1_":"after",
    "before bool_exp1, _ABSTRACT_VAR1_":"before",
    "while bool_exp1, _ABSTRACT_VAR1_":"in",
    "only while bool_exp1, _ABSTRACT_VAR1_":"only in",
    "whenever bool_exp1, _ABSTRACT_VAR1_":"whenever",
    "upon bool_exp1, _ABSTRACT_VAR1_":"upon",
}
fretish_cond_map = \
{
    "_ABSTRACT_VAR2_":None,
    "whenever bool_exp2, _ABSTRACT_VAR2_":"whenever",
    "upon bool_exp2, _ABSTRACT_VAR2_":"upon",
}
fretish_timing_map = \
{
    'until bool_exp4, satisfy bool_exp3':"until",
    "within N_DURATION ticks satisfy bool_exp3":"within",
    "at the next timepoint satisfy bool_exp3":"next",
    "eventually satisfy bool_exp3":"eventually",
    "immediately satisfy bool_exp3":"immediately",
    "always satisfy bool_exp3":"always",
    "for N_DURATION ticks satisfy bool_exp3":"for",
    "after N_DURATION ticks satisfy bool_exp3":"after",
    "before bool_exp4, satisfy bool_exp3":"before",
    "never satisfy bool_exp3":"never",
}

has_equiv_map = {
    (None,None,"never"),
    (None,None,"always"),
    (None,None,"eventually"),
    (None,None,"next"),
    (None,None,"for"),
    (None,None,"immediately"),
    (None,None,"within"),
    (None,"whenever","never"),
    (None,"whenever","always"),
    (None,"whenever","next"),
    (None,"whenever","eventually"),
    (None,"whenever","immediately"),
    (None,"whenever","within"),
    ("whenever",None,"never"),
    ("whenever",None,"always"),
    ("whenever",None,"next"),
    ("whenever",None,"eventually"),
    ("whenever",None,"immediately"),
    ("whenever",None,"within"),
    ("whenever","whenever","never"),
    ("whenever","whenever","always"),
    ("whenever","whenever","next"),
    ("whenever","whenever","eventually"),
    ("whenever","whenever","immediately"),
    ("whenever","whenever","within"),
    ("after",None,"eventually"),
    ("after",None,"immediately"),
    ("only in",None,"eventually"),
    ("in",None,"always"),
    ("in",None,"never"),
    ("in",None,"eventually"),
    ("in",None,"immediately")
}

diff_map = \
{
    (None,None,"until"):{
        "decision1":"Globally, _ABSTRACT_VAR1_",
        "decision2":"bool_exp3 holds without interruption until bool_exp4 holds",
        "bool_exp3":"bool_exp3",
        "bool_exp4":"bool_exp4"},

    (None,"whenever","until"):{
        "decision1":"After bool_exp1, _ABSTRACT_VAR1_",
        "decision2":"bool_exp3 holds without interruption until bool_exp4 holds",
        "bool_exp1":"bool_exp2",
        "bool_exp3":"bool_exp3",
        "bool_exp4":"bool_exp4",
        },

    ("after",None,"within"):{
        "decision1":"After bool_exp1, _ABSTRACT_VAR1_",
        "decision2":"bool_exp3 eventually holds between N_DURATION0 and N_DURATION1 time units",
        "bool_exp1":"(bool_exp1) & X !(bool_exp1)",
        "bool_exp3":"bool_exp3",
        "N_DURATION0":0,
        "N_DURATION1":"N_DURATION"
        },

    ("after",None,"next"):{
        "decision1":"After bool_exp1, _ABSTRACT_VAR1_",
        "decision2":"bool_exp3 eventually holds between N_DURATION0 and N_DURATION1 time units",
        "bool_exp1":"(bool_exp1) & X !(bool_exp1)",
        "bool_exp3":"bool_exp3",
        "N_DURATION0":1,
        "N_DURATION1":1,
        },

    ("before",None,"eventually"):{
        "decision1":"Before bool_exp2, _ABSTRACT_VAR1_",
        "decision2":"bool_exp3 eventually holds",
        "bool_exp2":"!(bool_exp1) & X (bool_exp1)",
        "bool_exp3":"bool_exp3",
        },

    ("before",None,"within"):{
        "decision1":"Before bool_exp2, _ABSTRACT_VAR1_",
        "decision2":"bool_exp3 eventually holds between N_DURATION0 and N_DURATION1 time units",
        "bool_exp2":"!(bool_exp1) & X (bool_exp1)",
        "bool_exp3":"bool_exp3",
        "N_DURATION0":0,
        "N_DURATION1":"N_DURATION"
        },

    ("before",None,"immediately"):{
        "decision1":"Before bool_exp2, _ABSTRACT_VAR1_",
        "decision2":"bool_exp3 eventually holds between N_DURATION0 and N_DURATION1 time units",
        "bool_exp2":"!(bool_exp1) & X (bool_exp1)",
        "bool_exp3":"bool_exp3",
        "N_DURATION0":0,
        "N_DURATION1":0,
        },

    ("in",None,"next"):{
        "decision1":"After bool_exp1 until bool_exp2, _ABSTRACT_VAR1_",
        "decision2":"bool_exp3 eventually holds between N_DURATION0 and N_DURATION1 time units",
        "bool_exp1":"(bool_exp1)",
        "bool_exp2":"!(bool_exp1)",
        "bool_exp3":"bool_exp3",
        "N_DURATION0":1,
        "N_DURATION1":1,
        },

    ("in",None,"within"):{
        "decision1":"After bool_exp1 until bool_exp2, _ABSTRACT_VAR1_",
        "decision2":"bool_exp3 eventually holds between N_DURATION0 and N_DURATION1 time units",
        "bool_exp1":"(bool_exp1)",
        "bool_exp2":"!(bool_exp1)",
        "bool_exp3":"bool_exp3",
        "N_DURATION0":0,
        "N_DURATION1":"N_DURATION",        
        },

    ("in","whenever","immediately"):{
        "decision1":"After bool_exp1 until bool_exp2, _ABSTRACT_VAR1_",
        "decision2":"if bool_exp3 has occurred, then in response bool_exp4 eventually holds between N_DURATION0 and N_DURATION1 time units",
        "bool_exp1":"(bool_exp1)",
        "bool_exp2":"!(bool_exp1)",
        "bool_exp3":"bool_exp2",
        "bool_exp4":"bool_exp3",
        "N_DURATION0":0,
        "N_DURATION1":0,
        },

    ("in","whenever","next"):{
        "decision1":"After bool_exp1 until bool_exp2, _ABSTRACT_VAR1_",
        "decision2":"if bool_exp3 has occurred, then in response bool_exp4 eventually holds between N_DURATION0 and N_DURATION1 time units",
        "bool_exp1":"(bool_exp1)",
        "bool_exp2":"!(bool_exp1)",
        "bool_exp3":"bool_exp2",
        "bool_exp4":"bool_exp3",
        "N_DURATION0":1,
        "N_DURATION1":1,
        },

    ("in","whenever","eventually"):{
        "decision1":"After bool_exp1 until bool_exp2, _ABSTRACT_VAR1_",
        "decision2":"if bool_exp3 has occurred, then in response bool_exp4 eventually holds",
        "bool_exp1":"(bool_exp1)",
        "bool_exp2":"!(bool_exp1)",
        "bool_exp3":"bool_exp2",
        "bool_exp4":"bool_exp3",
        },

    ("in","whenever","within"):{
        "decision1":"After bool_exp1 until bool_exp2, _ABSTRACT_VAR1_",
        "decision2":"if bool_exp3 has occurred, then in response bool_exp4 eventually holds between N_DURATION0 and N_DURATION1 time units",
        "bool_exp1":"(bool_exp1)",
        "bool_exp2":"!(bool_exp1)",
        "bool_exp3":"bool_exp2",
        "bool_exp4":"bool_exp3",
        "N_DURATION0":0,
        "N_DURATION1":"N_DURATION",
        },    
}

def get_fretish_to_PSP(fretish_output):
    t_key = (fretish_scope_map[fretish_output["decision1"]],fretish_cond_map[fretish_output["decision2"]],fretish_timing_map[fretish_output["decision3"]])
    if t_key in diff_map:
        psp_output = diff_map[t_key].copy()
        for decision,item_list in decision_to_item_list.items():
            for item in item_list:
                if item not in psp_output:
                    psp_output[item] = None
                elif isinstance(psp_output[item],str):
                    for fretish_item in ["bool_exp1","bool_exp2","bool_exp3","bool_exp4","N_DURATION"]:
                        if fretish_item in psp_output[item]:
                            if "N_DURATION" not in fretish_item:
                                psp_output[item] = psp_output[item].replace(fretish_item,f"({fretish_output[fretish_item]})")
                            else:
                                assert isinstance(fretish_output[fretish_item],int)
                                psp_output[item] = fretish_output[fretish_item]
        return psp_output
    else:
        return None