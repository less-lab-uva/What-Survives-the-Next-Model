import json
import llm_prompt
import spot
import pandas as pd
from spot_utils import *
from tqdm import tqdm
import itertools
from pydantic import BaseModel
from typing import Optional
import os

DATA_HOME_DIR = os.getenv("DATA_HOME_DIR")


with open(DATA_HOME_DIR+"/fretish_structnl_to_ltl_dict.json", "r") as json_file:
    structnl_to_ltl_dict = json.load(json_file)

prefix_nl_template_str = \
"""
To produce the structured natural language property, you compose it from a set of templates.
If the chosen option contains boolean expression placeholders (i.e., bool_exp1, bool_exp2, bool_exp3, bool_exp4), you need to produce boolean expressions that will replace the placeholders.
Boolean expressions can only contain boolean operators (e.g., !, &, |, ->, <->) and can only atomic propositions (NO NUMERICAL COMPARISON OPERATORS ALLOWED)
"""

from typing import Literal

class StructuredNLResult(BaseModel):
    explanation: str
    decision1: Literal[
        "while bool_exp1, _ABSTRACT_VAR1_", 
        "only while bool_exp1, _ABSTRACT_VAR1_",
        "before bool_exp1, _ABSTRACT_VAR1_",
        "only before bool_exp1, _ABSTRACT_VAR1_",
        "after bool_exp1, _ABSTRACT_VAR1_",
        "only after bool_exp1, _ABSTRACT_VAR1_",
        "whenever bool_exp1, _ABSTRACT_VAR1_",
        "upon bool_exp1, _ABSTRACT_VAR1_",
        "_ABSTRACT_VAR1_"
    ]
    #decision1: str
    #bool_exp1: Optional[str]
    bool_exp1: str
    decision2: Literal[
        "whenever bool_exp2, _ABSTRACT_VAR2_",
        "upon bool_exp2, _ABSTRACT_VAR2_",
        "_ABSTRACT_VAR2_"
    ]
    #decision2: str
    #bool_exp2: Optional[str]
    bool_exp2: str
    decision3: Literal[
        'immediately satisfy bool_exp3',
        'within N_DURATION ticks satisfy bool_exp3',
        'after N_DURATION ticks satisfy bool_exp3',
        'until bool_exp4, satisfy bool_exp3',
        'always satisfy bool_exp3',
        'never satisfy bool_exp3',
        'at the next timepoint satisfy bool_exp3',
        'eventually satisfy bool_exp3',
        'for N_DURATION ticks satisfy bool_exp3',
        'before bool_exp4, satisfy bool_exp3'
    ]
    #decision3: str
    bool_exp3: str
    #bool_exp4: Optional[str]
    bool_exp4: str
    N_DURATION: Optional[int]
    decision1_substring: str
    decision2_substring: str
    decision3_substring: str

class StructuredNLTranslations(BaseModel):
    translations: list[StructuredNLResult]
    
class LTLTemplateResult(BaseModel):
    explanation: str
    chosen_template_ID: int
    #chosen_LTL_template: str
    bool_exp1: str
    bool_exp2: str
    bool_exp3: str
    bool_exp4: str
    N_DURATION: Optional[int]

class LTLTemplateTranslations(BaseModel):
    translations: list[LTLTemplateResult]

structnl_dcmp_format_str = \
"""
Inputs consist of:
1. unstructured natural language (string)
2. atomic proposition + descriptions (dictionary mapping names to descriptions). You must use these atomic propositions to define the boolean expressions and account for their descriptions in your decisions.
3. nl_substring_to_decision_map. The option you choose for decision1, decision2, and decision3 should represent its corresponding substrings of the input unstructured natural language.

The Outputs consist of the arguments to the produce_structured_nl function and substrings of the input that pertain to each decision:
1. an explanation of the produced structured NL property and how it captures the input_natural_language
2. decision1 (should contain its placeholders names)
3. bool_exp1
4. decision2 (should contain its placeholders names)
5. bool_exp2
6. decision3 (should contain its placeholders names)
7. bool_exp3
8. bool_exp4
9. N_DURATION
10. decision1_substring (substring of input_natural_language that pertains to decision1)
11. decision2_substring (substring of input_natural_language that pertains to decision2)
12. decision3_substring (substring of input_natural_language that pertains to decision3)
"""

structnl_format_str = \
"""
Inputs consist of:
1. unstructured natural language (string)
2. atomic proposition + descriptions (dictionary mapping names to descriptions). You must use these atomic propositions to define the boolean expressions and account for their descriptions in your decisions.

The Outputs consist of the arguments to the produce_structured_nl function:
1. an explanation of the produced structured NL property and how it captures the input_natural_language
2. decision1 (should contain its placeholders names)
3. bool_exp1
4. decision2 (should contain its placeholders names)
5. bool_exp2
6. decision3 (should contain its placeholders names)
7. bool_exp3
8. bool_exp4
9. N_DURATION
10. decision1_substring (substring of input_natural_language that pertains to decision1)
11. decision2_substring (substring of input_natural_language that pertains to decision2)
12. decision3_substring (substring of input_natural_language that pertains to decision3)
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
7. N_DURATION
"""

decision_options_str = \
"""
decision1_options = [
    "while bool_exp1, _ABSTRACT_VAR1_",
    "before bool_exp1, _ABSTRACT_VAR1_",
    "after bool_exp1, _ABSTRACT_VAR1_",
    "whenever bool_exp1, _ABSTRACT_VAR1_",
    "upon bool_exp1, _ABSTRACT_VAR1_",
    "only while bool_exp1, _ABSTRACT_VAR1_",
    "only before bool_exp1, _ABSTRACT_VAR1_",
    "only after bool_exp1, _ABSTRACT_VAR1_",
    "_ABSTRACT_VAR1_"
]

decision2_options = [
    "whenever bool_exp2, _ABSTRACT_VAR2_",
    "upon bool_exp2, _ABSTRACT_VAR2_",
    "_ABSTRACT_VAR2_",
]

decision3_options = [
    'immediately satisfy bool_exp3',
    'within N_DURATION ticks satisfy bool_exp3',
    'after N_DURATION ticks satisfy bool_exp3',
    'until bool_exp4, satisfy bool_exp3',
    'always satisfy bool_exp3',
    'never satisfy bool_exp3',
    'at the next timepoint satisfy bool_exp3',
    'eventually satisfy bool_exp3',
    'for N_DURATION ticks satisfy bool_exp3',
    'before bool_exp4, satisfy bool_exp3'
]
"""

code_snippet = \
"""
def produce_structured_nl(
    decision1: str, bool_exp1: Optional[str],
    decision2: str, bool_exp2: Optional[str],
    decision3: str, bool_exp3: str, bool_exp4: Optional[str],
    N_DURATION: Optional[int]
) -> str:
    #Generates a structured natural language statement based on input templates and boolean expressions.
    
    #Args:
    #    decision1 (str): Template for the first decision.
    #    bool_exp1 (Optional[str]): Boolean expression for decision1.
    #    decision2 (str): Template for the second decision.
    #    bool_exp2 (Optional[str]): Boolean expression for decision2.
    #    decision3 (str): Template for the third decision.
    #    bool_exp3 (str): Boolean expression for decision3.
    #    bool_exp4 (Optional[str]): Secondary boolean expression for decision3.
    #    N_DURATION (Optional[int]): Duration value for decision3.
    #Returns:
    #    str: Structured natural language statement.

    #must be using valid options for each decision
    assert decision1 in decision1_options
    assert decision2 in decision2_options
    assert decision3 in decision3_options

    # Step 1: Process decision1 with bool_exp1
    if "bool_exp1" in decision1:
        decision1_instance = decision1.replace("bool_exp1", bool_exp1)
    else:
        decision1_instance = decision1

    # Step 2: Process decision2 with bool_exp2
    if "bool_exp2" in decision2:
        decision2_instance = decision2.replace("bool_exp2", bool_exp2)
    else:
        decision2_instance = decision2

    # Replace _ABSTRACT_VAR1_ with decision2_instance
    result = decision1_instance.replace("_ABSTRACT_VAR1_", decision2_instance)

    # Step 3: Process decision3 with bool_exp3, bool_exp4, and N_DURATION
    decision3_instance = decision3.replace("bool_exp3", bool_exp3)

    if "bool_exp4" in decision3 and bool_exp4 is not None:
        decision3_instance = decision3_instance.replace("bool_exp4", bool_exp4)

    if "N_DURATION" in decision3 and N_DURATION is not None:
        decision3_instance = decision3_instance.replace("N_DURATION", str(N_DURATION))

    # Replace _ABSTRACT_VAR2_ with decision3_instance
    result = result.replace("_ABSTRACT_VAR2_", decision3_instance)

    return result
"""
code_snippet = \
"""
def produce_structured_nl(
    decision1: str, bool_exp1: Optional[str],
    decision2: str, bool_exp2: Optional[str],
    decision3: str, bool_exp3: str, bool_exp4: Optional[str],
    N_DURATION: Optional[int]
) -> str:
    decision1_instance = decision1.replace("bool_exp1", bool_exp1)
    decision2_instance = decision2.replace("bool_exp2", bool_exp2)
    decision3_instance = decision3.replace("bool_exp3", bool_exp3).replace("bool_exp4",bool_exp4).replace("N_DURATION", str(N_DURATION))

    return decision1_instance.replace("_ABSTRACT_VAR1_", decision2_instance).replace("_ABSTRACT_VAR2_", decision3_instance)
"""
code_snippet = \
"""
def produce_structured_nl(
    decision1: str, bool_exp1: Optional[str],
    decision2: str, bool_exp2: Optional[str],
    decision3: str, bool_exp3: str, bool_exp4: Optional[str],
    N_DURATION: Optional[int]
) -> str:
    assert decision1 in decision1_options and decision2 in decision2_options and decision3 in decision3_options
    return decision1.replace("_ABSTRACT_VAR1_", decision2).replace("_ABSTRACT_VAR2_", decision3)
"""
code_snippet = \
"""
def produce_structured_nl(
    decision1: str, bool_exp1: Optional[str],
    decision2: str, bool_exp2: Optional[str],
    decision3: str, bool_exp3: str, bool_exp4: Optional[str],
    N_DURATION: Optional[int]
) -> str:
    # Step 1: Fill in decision3
    decision3_filled = decision3
    if "bool_exp3" in decision3:
        decision3_filled = decision3_filled.replace("bool_exp3", bool_exp3)
    if "bool_exp4" in decision3:
        decision3_filled = decision3_filled.replace("bool_exp4", bool_exp4)
    if "N_DURATION" in decision3:
        decision3_filled = decision3_filled.replace("N_DURATION", str(N_DURATION))

    # Step 2: Fill in decision2
    decision2_filled = decision2
    if "bool_exp2" in decision2:
        decision2_filled = decision2_filled.replace("bool_exp2", bool_exp2)
    decision2_filled = decision2_filled.replace("_ABSTRACT_VAR2_", decision3_filled)

    # Step 3: Fill in decision1
    decision1_filled = decision1
    if "bool_exp1" in decision1:
        decision1_filled = decision1_filled.replace("bool_exp1", bool_exp1)
    decision1_filled = decision1_filled.replace("_ABSTRACT_VAR1_", decision2_filled)

    return decision1_filled
"""

decision1_options = [
    "while bool_exp1, _ABSTRACT_VAR1_", 
    "only while bool_exp1, _ABSTRACT_VAR1_",
    "before bool_exp1, _ABSTRACT_VAR1_",
    "only before bool_exp1, _ABSTRACT_VAR1_",
    "after bool_exp1, _ABSTRACT_VAR1_",
    "only after bool_exp1, _ABSTRACT_VAR1_",
    "whenever bool_exp1, _ABSTRACT_VAR1_",
    "upon bool_exp1, _ABSTRACT_VAR1_",
    "_ABSTRACT_VAR1_"
]


decision2_options = [
    "whenever bool_exp2, _ABSTRACT_VAR2_",
    "upon bool_exp2, _ABSTRACT_VAR2_",
    "_ABSTRACT_VAR2_",
]

decision3_options = [
    'immediately satisfy bool_exp3',
    'within N_DURATION ticks satisfy bool_exp3',
    'after N_DURATION ticks satisfy bool_exp3',
    'until bool_exp4, satisfy bool_exp3',
    'always satisfy bool_exp3',
    'never satisfy bool_exp3',
    'at the next timepoint satisfy bool_exp3',
    'eventually satisfy bool_exp3',
    'for N_DURATION ticks satisfy bool_exp3',
    'before bool_exp4, satisfy bool_exp3'
]

df_option_names = ['timing options','timing bool exps','scope 1 options', 'scope 1 bool exps', 'scope 2 options', 'scope 2 bool exps']


decision_to_item_list = \
{
    "decision1" : ["bool_exp1"],
    "decision2" : ["bool_exp2"],
    "decision3" : ["bool_exp3", "bool_exp4", "N_DURATION"]
}

decision_order = ["decision1", "decision2", "decision3"]

from typing import Optional
def produce_structured_nl(
    decision1: str, bool_exp1: Optional[str],
    decision2: str, bool_exp2: Optional[str],
    decision3: str, bool_exp3: str, bool_exp4: Optional[str],
    N_DURATION: Optional[int]
) -> str:
    #Generates a structured natural language statement based on input templates and boolean expressions.
    
    #Args:
    #    decision1 (str): Template for the first decision.
    #    bool_exp1 (Optional[str]): Boolean expression for decision1.
    #    decision2 (str): Template for the second decision.
    #    bool_exp2 (Optional[str]): Boolean expression for decision2.
    #    decision3 (str): Template for the third decision.
    #    bool_exp3 (str): Boolean expression for decision3.
    #    bool_exp4 (Optional[str]): Secondary boolean expression for decision3.
    #    N_DURATION (Optional[int]): Duration value for decision3.
    #Returns:
    #    str: Structured natural language statement.

    #must be using valid options for each decision
    assert decision1 in decision1_options
    assert decision2 in decision2_options
    assert decision3 in decision3_options

    # Step 1: Process decision1 with bool_exp1
    if "bool_exp1" in decision1:
        decision1_instance = decision1.replace("bool_exp1", bool_exp1)
    else:
        decision1_instance = decision1

    # Step 2: Process decision2 with bool_exp2
    if "bool_exp2" in decision2:
        decision2_instance = decision2.replace("bool_exp2", bool_exp2)
    else:
        decision2_instance = decision2

    # Replace _ABSTRACT_VAR1_ with decision2_instance
    result = decision1_instance.replace("_ABSTRACT_VAR1_", decision2_instance)

    # Step 3: Process decision3 with bool_exp3, bool_exp4, and N_DURATION
    decision3_instance = decision3.replace("bool_exp3", bool_exp3)

    if "bool_exp4" in decision3 and bool_exp4 is not None:
        decision3_instance = decision3_instance.replace("bool_exp4", bool_exp4)

    if "N_DURATION" in decision3 and N_DURATION is not None:
        decision3_instance = decision3_instance.replace("N_DURATION", str(N_DURATION))

    # Replace _ABSTRACT_VAR2_ with decision3_instance
    result = result.replace("_ABSTRACT_VAR2_", decision3_instance)

    return result

def extract_structnl_from_output(output):
    arg_names = ["decision1","bool_exp1","decision2","bool_exp2","decision3","bool_exp3","bool_exp4","N_DURATION"]
    arg_dict = dict((k,None) for k in arg_names)
    for k in arg_names:
        if k in output:
            arg_dict[k] = output[k]
    return produce_structured_nl(**arg_dict)

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
    
def check_nl2structnl_format_inner(json_output,ap_dict,dcmp=None):
    bool_var_msg = f"Boolean expressions must only contain variables from the following: {str(list(ap_dict.keys()))}"
    if json_output["decision1"] not in decision1_options:
        return f"Invalid option for decision1. decision1 must be chosen from the following options: {str(decision1_options)}"
    if json_output["decision2"] not in decision2_options:
        return f"Invalid option for decision2. decision2 must be chosen from the following options: {str(decision2_options)}"
    if json_output["decision3"] not in decision3_options:
        return f"Invalid option for decision3. decision3 must be chosen from the following options: {str(decision3_options)}"
    if "bool_exp1" in json_output["decision1"]:
        err_msg = check_boolean_formula(json_output["bool_exp1"],ret_err_msg=True)
        if err_msg != "":    
            return f"bool_exp1 {json_output['bool_exp1']} is not a valid boolean expression:\n{err_msg}"
        for var in get_variables_from_formula(json_output["bool_exp1"]):
            if var not in ap_dict:
                return f"bool_exp1: {var} is not a valid atomic proposition. {bool_var_msg}"
    if "bool_exp2" in json_output["decision2"]:
        err_msg = check_boolean_formula(json_output["bool_exp2"],ret_err_msg=True)
        if err_msg != "":    
            return f"bool_exp2 {json_output['bool_exp2']} is not a valid boolean expression:\n{err_msg}"
        for var in get_variables_from_formula(json_output["bool_exp2"]):
            if var not in ap_dict:
                return f"bool_exp2: {var} is not a valid atomic proposition. {bool_var_msg}"
    if "bool_exp3" in json_output["decision3"]:
        err_msg = check_boolean_formula(json_output["bool_exp3"],ret_err_msg=True)
        if err_msg != "":    
            return f"bool_exp3 {json_output['bool_exp3']} is not a valid boolean expression:\n{err_msg}"
        for var in get_variables_from_formula(json_output["bool_exp3"]):
            if var not in ap_dict:
                return f"bool_exp3: {var} is not a valid atomic proposition. {bool_var_msg}"
    if "bool_exp4" in json_output["decision3"]:
        err_msg = check_boolean_formula(json_output["bool_exp4"],ret_err_msg=True)
        if err_msg != "":    
            return f"bool_exp4 {json_output['bool_exp4']} is not a valid boolean expression:\n{err_msg}"
        for var in get_variables_from_formula(json_output["bool_exp4"]):
            if var not in ap_dict:
                return f"bool_exp4: {var} is not a valid atomic proposition. {bool_var_msg}"
    if "N_DURATION" in json_output["decision3"] and not check_valid_nonnegative_integer(json_output["N_DURATION"]):
        return f"N_DURATION {json_output['N_DURATION']} is not a valid non-zero integer"
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
    #nl_template_str += "\nThe following list the possible options for decision1, decision2, and decision3:\n"
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
        arg_list = ["decision1","decision2","decision3","bool_exp1","bool_exp2","bool_exp3","bool_exp4","N_DURATION"]
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

def get_structnl_to_ltl_template(decision1,decision2,decision3):
    cur_structnl = decision1.replace("_ABSTRACT_VAR1_",decision2.replace("_ABSTRACT_VAR2_",decision3))
    out_ltl = structnl_to_ltl_dict[cur_structnl]
    return out_ltl

def get_ltl_from_output(output,ltl_template=None):
    if ltl_template is None:
        ltl_template = get_structnl_to_ltl_template(decision1=output["decision1"],decision2=output["decision2"],decision3=output["decision3"])
    else:
        ltl_template = ltl_template
    for decision,item_list in decision_to_item_list.items():
        for k in item_list:
            if k in output and output[k] is not None and k in ltl_template:
                if k != "N_DURATION":
                    cur_exp = spot.formula(output[k]).to_str(parenth=True)
                    if cur_exp == "1":
                        cur_exp = "TRUE"
                    elif cur_exp == "0":
                        cur_exp = "FALSE"
                    ltl_template = ltl_template.replace(k,f"({cur_exp})")
                else:
                    ltl_template = ltl_template.replace("N_DURATION+1",str(int(output[k])+1))
                    ltl_template = ltl_template.replace("N_DURATION-1",str(int(output[k])-1))
                    ltl_template = ltl_template.replace("N_DURATION",str(output[k]))
    return ltl_template

def get_ltl_from_options(option_dict):
    res = get_structnl_to_ltl_template(
        decision1=option_dict["decision1"]["option"],
        decision2=option_dict["decision2"]["option"],
        decision3=option_dict["decision3"]["option"])
    for decision,item_list in decision_to_item_list.items():
        for k in item_list:
            if k in option_dict[decision] and option_dict[decision][k] is not None and k in res:
                if k != "N_DURATION":
                    cur_exp = spot.formula(option_dict[decision][k]).to_str(parenth=True)
                    if cur_exp == "1":
                        cur_exp = "TRUE"
                    elif cur_exp == "0":
                        cur_exp = "FALSE"
                    res = res.replace(k,f"({cur_exp})")
                else:
                    res = res.replace("N_DURATION+1",str(int(option_dict[decision][k])+1))
                    res = res.replace("N_DURATION-1",str(int(option_dict[decision][k])-1))
                    res = res.replace("N_DURATION",str(option_dict[decision][k]))   
    return res

def get_dcmp_map_from_row(df_row):
    col_name_map = \
    {
        "decision3_substring":"timing substring",
        "decision2_substring":"scope 1 substring",
        "decision1_substring":"scope 2 substring",
    }
    substring_order = ['decision3_substring', 'decision2_substring', 'decision1_substring']
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
    key_list = ["bool_exp1","bool_exp2","bool_exp3","bool_exp4"]
    all_bools = []
    cur_ap_dict = {}
    for k in key_list:
        if k in output and output[k] is not None and check_boolean_formula(output[k]):
            all_bools.append(output[k])
            for var in get_variables_from_formula(output[k]):
                cur_ap_dict[var] = var
        else:
            all_bools.append(None)
    if "N_DURATION" in output["decision3"] and check_valid_nonnegative_integer(output["N_DURATION"]):
        duration_list = [output["N_DURATION"]]
    else:
        duration_list = [n_duration for n_duration in range(1,MAX_DURATION+1)]
    
    new_output_list = []
    for cur_bool in [all_bools]:
    #for cur_bool in [(output["bool_exp1"],output["bool_exp2"],output["bool_exp3"],output["bool_exp4"])]:
    #for bool_group in itertools.combinations(all_bools,4):
    #    for cur_bool in itertools.permutations(bool_group):
            for n_duration in duration_list:
                for e in itertools.product(decision1_options,decision2_options,decision3_options):
                    new_output = output.copy()
                    new_output["bool_exp1"] = cur_bool[0]
                    new_output["bool_exp2"] = cur_bool[1]
                    new_output["bool_exp3"] = cur_bool[2]
                    new_output["bool_exp4"] = cur_bool[3]
                    new_output["decision1"] = e[0]
                    new_output["decision2"] = e[1]
                    new_output["decision3"] = e[2]
                    new_output["N_DURATION"] = n_duration
                    if check_nl2structnl_format_inner(new_output,cur_ap_dict) is None:
                        new_output_list.append(new_output)
    return new_output_list
