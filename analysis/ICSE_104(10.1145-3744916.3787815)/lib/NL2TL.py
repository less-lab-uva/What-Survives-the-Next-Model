import json
import llm_prompt
import nl2structnl
from spot_utils import *
from pydantic import BaseModel, create_model
from typing import Optional
from typing import Dict, List
import os
import nl2ltl
import deepstl

NL2LTL_ap_recognition_tutorial = [
    {
        "sentence": "walk until whenever travel to flag",
        "ap_phrases": ["walk", "travel to flag"]
    },
    {
        "sentence": "forever touch flag and drop orange",
        "ap_phrases": ["touch flag", "drop orange"]
    },
    {
        "sentence": "drop by or whenever go to flag",
        "ap_phrases": ["drop by", "go to flag"]
    },
    {
        "sentence": "at some time procure pear or stop by flag",
        "ap_phrases": ["procure pear", "stop by flag"]
    },
    {
        "sentence": "never drop pear means that at any time go to flag",
        "ap_phrases": ["drop pear", "go to flag"]
    },
    {
        "sentence": "never drop apple or secure apple",
        "ap_phrases": ["drop apple", "secure apple"]
    },
    {
        "sentence": "do not let go pear or whenever start going to house",
        "ap_phrases": ["let go pear", "start going to house"]
    }
]

NL2TL_translation_tutorial = \
"""
You must express your answer in the natural language operators listed above. The following is an example formula:
( globally ( ( prop_1 and prop_2 ) imply ( not ( prop_3 ) or prop_2 ) ) )
"""

nl_to_ltl_ascii = {
    'negation': '!',       # not
    'not': '!',       # not
    'imply': '->',         # implication
    'implies': '->',         # implication
    'and': '&',            # and
    'or': '|',             # or
    'equal': '<->',        # equivalence
    'until': 'U',          # until
    'globally': 'G',       # always
    'finally': 'F'         # eventually
}

def swap_nl_to_ltl_formula(nl_formula):
    ltl_formula = nl_formula
    for k,v in nl_to_ltl_ascii.items():
        ltl_formula = ltl_formula.replace(k,v)
    return ltl_formula

class APRecognitionResult(BaseModel):
    ap_phrases: List[str]

"""
class BoolExpMapping(BaseModel):
    natural_language: str
    bool_exp: str

class BoolExpMappingResult(BaseModel):
    boolean_expressions: List[BoolExpMapping]
"""

class NL2TLResult(BaseModel):
    explanation: str
    output_LTL: str

#class NL2TLTranslations(BaseModel):
#    translations: List[NL2TLResult]

def get_NL2TL_ap_recognition_prompt(input_nl,ap_dict):
    #instruction = "Detect the ap_phrases or tasks in the sentence. The examples are as follows:"
    instruction = "For translating natural language requirements to LTL, extract the phrases in the sentence that correspond to atomic propositions."
    
    tutorial_str = "The examples are as follows:"
    tutorial_str += json.dumps(NL2LTL_ap_recognition_tutorial)
    
    input_str = "\n\nfor the following sentence, you should list the phrases (i.e., substrings of the sentence) that correspond to an atomic proposition:"
    input_str += "\n{\n"
    input_str += f"\"sentence\":\"{input_nl}\",\n"
    #input_str += f"\"atomic_propositions\":{json.dumps(ap_dict)},\n"
    input_str += "}\n"    
    
    system_prompt = "\n".join([instruction])
    user_prompt = "\n".join([tutorial_str,input_str])
    return system_prompt, user_prompt

def check_ap_format(raw_output,input_nl):
    try:
        json_output = json.loads(raw_output)
    except:
        print("in ap check")
        return "output is not valid JSON"
    try:
        obj = APRecognitionResult(**json_output)
    except Exception as e:
        return f"invalid output format: {e}"
    json_output = json_output["ap_phrases"]
    if len(json_output) == 0:
        return "must identify at least one atomic proposition"
    for substring in json_output:
        if substring.lower() not in input_nl.lower():
            return f"'{substring}' is not a substring of the sentence '{input_nl}', all outputs must be a substring."
    return None

def check_bool_exp_format(raw_output,ap_phrases,ap_dict):
    bool_var_msg = f"Boolean expressions must only contain variables from the following: {str(list(ap_dict.keys()))}"
    try:
        json_output = json.loads(raw_output)
    except:
        print("in bool_exp check")
        print(raw_output)
        return "output is not valid JSON"
    found_set = set()
    for entry in ap_phrases:
        if entry in json_output:
            found_set.add(entry)
            bool_exp = json_output[entry]
            err_msg = check_boolean_formula(bool_exp,ret_err_msg=True)
            if err_msg != "":    
                return f"invalid boolean expression:\n{err_msg}"
            for var in get_variables_from_formula(bool_exp):
                if var not in ap_dict:
                    return f"bool_exp1: {var} is not a valid atomic proposition. {bool_var_msg}"
    """
    try:
        obj = BoolExpMappingResult(**json_output)
    except Exception as e:
        return f"invalid output format: {e}"
    boolean_expressions = json_output["boolean_expressions"]
    found_set = set()
    for entry in boolean_expressions:
        if entry["natural_language"] not in ap_phrases:
            return f"\"{entry['natural_language']}\" is not one of the options"
        found_set.add(entry["natural_language"])
        bool_exp = entry["bool_exp"]
        err_msg = check_boolean_formula(bool_exp,ret_err_msg=True)
        if err_msg != "":    
            return f"invalid boolean expression:\n{err_msg}"
        for var in get_variables_from_formula(bool_exp):
            if var not in ap_dict:
                return f"bool_exp1: {var} is not a valid atomic proposition. {bool_var_msg}"
    """
    missing_set = found_set - set(ap_phrases)
    if len(missing_set) > 0:
        return f"missing boolean expressions for the following phrases: {json.dumps(missing_set)}"
    return None
    
def check_NL2TL_format(raw_output,ap_dict):
    try:
        json_raw_output = json.loads(raw_output)
    except:
        print("in translation check")
        return "output is not valid JSON"
    try:
        obj = NL2TLResult(**json_raw_output)
    except Exception as e:
        return f"invalid output format: {e}"
    #for json_output in json_raw_output["translations"]:
    json_output = json_raw_output
    json_output["output_LTL"] = swap_nl_to_ltl_formula(json_output["output_LTL"])
    err_msg = nl2ltl.check_nl2ltl_format_inner(json_output,ap_dict)
    if err_msg is not None:
        return "please output your full list after addressing the following problem: " + err_msg
    return None

def get_lifted_NL(input_nl,ap_phrases):
    ap_list = []
    lifted_nl = input_nl
    for i in range(len(ap_phrases)):
        cur_ap = f"prop_{i}"
        lifted_nl = lifted_nl.replace(ap_phrases[i],cur_ap)
        ap_list.append(cur_ap)
    return lifted_nl, ap_list

def get_NL2TL_translation_prompt(input_nl,ap_list):
    #instruction = "Try to transform the following natural languages into linear temporal logics, the operators in the linear temporal logic are: not, imply, and, equal, until, globally, finally, or . You should use infix notation and must only use the given atomic propositions. Your output should follow the JSON format (explanation and output_LTL)."
    instruction = "You are an expert in translating natural language to linear temporal logic (LTL). Your job is to translate natural language to LTL.\n"
    instruction += "You must only use LTL operators and atomic propositions (NO NUMERICAL COMPARISON OPERATORS ALLOWED). Recall that in LTL, G = globally, F = eventually, V = releases, X = next, U = until, G[0:1] p = p & Xp, F[0:1] p = p | Xp. You may use boolean operators (e.g., !, &, |, ->, <->) and can only use atomic propositions (NO NUMERICAL COMPARISON OPERATORS ALLOWED)\n"
    
    #tutorial_str = NL2TL_translation_tutorial

    input_str = "{\n"
    input_str += f"\"input_natural_language\":\"{input_nl}\",\n"
    input_str += f"\"atomic_propositions\":{json.dumps(ap_list)},\n"
    input_str += "}\n"
    
    system_prompt = "\n".join([instruction])
    #user_prompt = "\n".join([tutorial_str,input_str])
    user_prompt = "\n".join([input_str])
    return system_prompt, user_prompt

def get_NL2TL_bool_exp_prompt(ap_phrases,ap_dict):
    instruction = "You are formalizing natural language requirements. For each of the natural language phrases in the list, formulate boolean expressions (i.e., with boolean operators: &, |, !, ->, <->) that capture them. You must use the given atomic propositions and follow the JSON format (natural_language and bool_exp)."
    input_str = "{\n"
    input_str += f"\"natural_language_phrases\":{json.dumps(ap_phrases)},\n"
    input_str += f"\"atomic_propositions\":{json.dumps(ap_dict)},\n"
    input_str += "}\n"    

    system_prompt = "\n".join([instruction])
    user_prompt = "\n".join([input_str])
    return system_prompt, user_prompt

def get_ltl_from_NL2TL_output(output,ap_phrases,abs_ap_list,boolean_expressions):
    #output_ltl = swap_nl_to_ltl_formula(output["output_LTL"])
    output_ltl = output["output_LTL"]
    for entry in boolean_expressions:
        #nl_phrase = entry["natural_language"]
        #bool_exp = entry["bool_exp"]
        nl_phrase = entry
        bool_exp = boolean_expressions[nl_phrase]
        if nl_phrase not in ap_phrases:
            continue
        cur_abs_ap = abs_ap_list[ap_phrases.index(nl_phrase)]
        output_ltl = output_ltl.replace(cur_abs_ap,f"({bool_exp})")
    return output_ltl

def format_NL2TL_output(raw_output,ap_dict,ap_phrases,abs_ap_list,boolean_expressions):
    output_list = []
    #json_raw_output = json.loads(raw_output)
    #for json_output in json_raw_output["translations"]:
    json_output = json.loads(raw_output)
    json_output["output_LTL"] = get_ltl_from_NL2TL_output(json_output,ap_phrases,abs_ap_list,boolean_expressions)
    if nl2ltl.check_nl2ltl_format_inner(json_output,ap_dict) is None:
        output_list.append(json_output)
    return output_list

def get_NL2TL_translation(input_nl,ap_dict,model="gpt-4o-mini",k=1,max_retry=1,prev_outputs=None,mode="PT"):
    assert mode in ["PT","FT"], "NL2TL mode invalid!"
    system_prompt, user_prompt = get_NL2TL_ap_recognition_prompt(input_nl,ap_dict)
    recog_output = llm_prompt.prompt_loop(system_prompt, user_prompt, model, max_retry, check_output_func=check_ap_format, schema=APRecognitionResult,input_nl=input_nl)
    if recog_output is None:
        return []
    ap_phrases = json.loads(recog_output)["ap_phrases"]
    lifted_nl,abs_ap_list = get_lifted_NL(input_nl,ap_phrases)
    abs_ap_dict = dict((k,k) for k in abs_ap_list)
    #print("lifted nl:",lifted_nl)
    system_prompt, user_prompt = get_NL2TL_bool_exp_prompt(ap_phrases,ap_dict)
    
    fields = {name:(str,...) for name in ap_phrases}
    BooleanExpressionsResponse = create_model("BooleanExpressionsResponse", **fields)
    
    boolexp_output = llm_prompt.prompt_loop(system_prompt, user_prompt, model, max_retry, check_output_func=check_bool_exp_format, 
                                            schema=BooleanExpressionsResponse,
                                            #schema=BoolExpMappingResult,
                                            ap_phrases=ap_phrases,ap_dict=ap_dict)    
    if boolexp_output is None:
        return []
    #boolean_expressions = json.loads(boolexp_output)["boolean_expressions"]
    boolean_expressions = json.loads(boolexp_output)
    if mode == "PT":
        system_prompt, user_prompt = get_NL2TL_translation_prompt(lifted_nl,abs_ap_list)
        translation_output = llm_prompt.prompt_loop(system_prompt, user_prompt, model, max_retry, check_output_func=check_NL2TL_format, schema=NL2TLResult, ap_dict=abs_ap_dict)
    elif mode == "FT":
        system_prompt, user_prompt = deepstl.get_LTL_prompt(lifted_nl,abs_ap_dict)
        translation_output = llm_prompt.prompt_loop(system_prompt, user_prompt, f"deepstl-{model}", max_retry, check_output_func=deepstl.check_deepstl_format, schema=None, ap_dict=abs_ap_dict)
    if translation_output is None:
        return []
    output = format_NL2TL_output(translation_output,ap_dict,ap_phrases,abs_ap_list,boolean_expressions)
    return output