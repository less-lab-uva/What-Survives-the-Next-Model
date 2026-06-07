import json
import llm_prompt
import nl2structnl
from spot_utils import *
from pydantic import BaseModel
from typing import Optional
import os

DATA_HOME_DIR = os.getenv("DATA_HOME_DIR")

def get_structnl_ltl_list():
    if os.getenv("STRUCTNL_MODE") == "fretish":
        with open(DATA_HOME_DIR+"/all_fretish_templates.json", "r") as json_file:
            structnl_ltl_list = json.load(json_file)
        for i in range(len(structnl_ltl_list)):
            new_ltl = structnl_ltl_list[i]["LTL"].replace("MODE_EXP","bool_exp1").replace("CONDITION_EXP","bool_exp2").replace("RES","bool_exp3").replace("STOP_CONDITION","bool_exp4")
            new_structnl = structnl_ltl_list[i]["fretish"].replace("MODE_EXP","bool_exp1").replace("CONDITION_EXP","bool_exp2").replace("RES","bool_exp3").replace("STOP_CONDITION","bool_exp4")
            structnl_ltl_list[i]["LTL"] = new_ltl
            structnl_ltl_list[i]["structnl"] = new_structnl
        return structnl_ltl_list
    elif os.getenv("STRUCTNL_MODE") == "SPS":        
        with open(DATA_HOME_DIR+"/sps_structnl_to_ltl_dict.json", "r") as json_file:
            structnl_to_ltl_dict = json.load(json_file)
        i = 0
        structnl_ltl_list = []
        for k,v in structnl_to_ltl_dict.items():
            structnl_ltl_list.append({"structnl":k,"LTL":v})
            i += 1
        return structnl_ltl_list
    elif os.getenv("STRUCTNL_MODE") == "PSP":
        with open(DATA_HOME_DIR+"/psp_dict.json", "r") as json_file:
            structnl_to_ltl_dict = json.load(json_file)
        i = 0
        structnl_ltl_list = []
        for k,v in structnl_to_ltl_dict.items():
            structnl_ltl_list.append({"structnl":k,"LTL":v})
            i += 1
        return structnl_ltl_list
    else:
        assert False, "unknown structnl"
structnl_ltl_list = get_structnl_ltl_list()

def get_templates_prompt_str(include_nl=False):
    global structnl_ltl_list
    if not include_nl:
        template_ltl_str = "You must use one of the following LTL templates and replace the atomic propositions with boolean expressions (and set N_DURATION to a fixed integer value greater than 0):\n"
        template_ltl_str += "If the chosen option contains boolean expression placeholders (i.e., bool_exp1, bool_exp2, bool_exp3, bool_exp4), you need to produce boolean expressions that will replace the placeholders. Boolean expressions can only contain boolean operators (e.g., !, &, |, ->, <->)\n"
        #template_ltl_str += "When choosing the LTL template, please provide the index of the chosen LTL template\n"
        template_ltl_str += "index:\tLTL\n"
        for i in range(len(structnl_ltl_list)):
            out_ltl = structnl_ltl_list[i]["LTL"]
            template_ltl_str += f"{i}\t{out_ltl}\n"
    else:
        template_ltl_str = "You must use one of the following LTL templates and replace the atomic propositions with boolean expressions (and set N_DURATION to a fixed integer value greater than 0):\n"
        #template_ltl_str += "When choosing the LTL template, please provide the index of the LTL template\n"
        template_ltl_str += "index\tNatural Language Meaning\tLTL\n"
        for i in range(len(structnl_ltl_list)):
            out_ltl = structnl_ltl_list[i]["LTL"]
            out_structnl = structnl_ltl_list[i]["structnl"]
            template_ltl_str += f"{i}\t{out_structnl}:\t{out_ltl}\n"
    return template_ltl_str

def get_LTLtemplate_prompt(input_nl,ap_dict,k=1,prev_outputs=None):
    init_cmd_str = "Your job is to translate natural language to LTL.\n"
    #init_cmd_str += "You must only use LTL operators and atomic propositions (NO NUMERICAL COMPARISON OPERATORS ALLOWED). Recall that in LTL, G = globally, F = eventually, V = releases, X = next, U = until, G[0,N_DURATION] = holds for N_DURATION time steps\n"
        
    template_ltl_str = get_templates_prompt_str(include_nl=False)
    
    format_description_str = nl2structnl.ltltemplate_format_str

    #final_cmd_str = \
    #"""
    #Follow the above output JSON format to provide the translation for the following:
    #"""
    final_cmd_str = f"provide a list of the top {k} most likely translations (ordered by most likely first to least likely last) in the above output JSON format for the following:\n"
    input_str = "{\n"
    input_str += f"\"input_natural_language\":\"{input_nl}\",\n"
    input_str += f"\"atomic_propositions\":{json.dumps(ap_dict)},\n"
    input_str += "}\n"
    if prev_outputs is not None and len(prev_outputs) > 0:
        prev_output_str = "IMPORTANT: You must choose different templates or boolean expressions so that output_LTL is not the same as any of the following:\n"
        #arg_list = ["output_LTL"]
        arg_list = ["chosen_template_ID"]
        #arg_list = ["chosen_template_ID","chosen_LTL_template","bool_exp1","bool_exp2","bool_exp3","bool_exp4","N_DURATION"]
        #arg_list = ["chosen_LTL_template"]
        prev_output_str += json.dumps([dict((k,e[k]) for k in arg_list) for e in prev_outputs])
        #prev_output_str += "\nIf you are confident, you may reuse the same as above."
        #prev_output_str += "\nThe input_natural_language is ambiguous, please produce the next most likely alternative translations."
        prev_output_str += "\nThe above are incorrect, and input_natural_language is ambiguous. Please produce the LTL property that captures the meaning of the input_natural_langauge."
    else:
        prev_output_str = ""
    system_prompt = "\n".join([init_cmd_str,template_ltl_str,format_description_str])
    user_prompt = "\n".join([final_cmd_str,input_str,prev_output_str])
    return system_prompt, user_prompt

class LTLResult(BaseModel):
    explanation: str
    output_LTL: str

class LTLTranslations(BaseModel):
    translations: list[LTLResult]
    
def get_LTL_prompt(input_nl,ap_dict,k=1,prev_outputs=None):
    init_cmd_str = "You are an expert in translating natural language to linear temporal logic (LTL). Your job is to translate natural language to LTL.\n"
    init_cmd_str += "You must only use LTL operators and atomic propositions (NO NUMERICAL COMPARISON OPERATORS ALLOWED). Recall that in LTL, G = globally, F = eventually, V = releases, X = next, U = until, G[0:1] p = p & Xp, F[0:1] p = p | Xp. You may use boolean operators (e.g., !, &, |, ->, <->) and can only use atomic propositions (NO NUMERICAL COMPARISON OPERATORS ALLOWED)\n"
    
    format_description_str = \
    """
    Inputs consist of:
    1. unstructured natural language (string)
    2. atomic proposition + descriptions (dictionary mapping names to descriptions)
    
    The Outputs consist of:
    1. an explanation of the produced LTL property and how it captures the input_natural_language and explanation of why the previously given (if present) LTL properties may not capture the input_natural_language
    2. output_LTL
    """

    #final_cmd_str = \
    #"""
    #Follow the above output JSON format to provide the translation for the following:
    #"""
    final_cmd_str = f"provide a list of the top {k} most likely translations (ordered by most likely first to least likely last) in the above output JSON format for the following:\n"
    input_str = "{\n"
    input_str += f"\"input_natural_language\":\"{input_nl}\",\n"
    input_str += f"\"atomic_propositions\":{json.dumps(ap_dict)},\n"
    input_str += "}\n"
    if prev_outputs is not None and len(prev_outputs) > 0:
        prev_output_str = "IMPORTANT: You produce an output_LTL semantically different from all of the following:\n"
        arg_list = ["output_LTL"]
        prev_output_str += json.dumps([dict((k,e[k]) for k in arg_list) for e in prev_outputs])
        #prev_output_str += "\nIf you are confident, you may reuse the same as above."
        prev_output_str += "\nThe above are incorrect. The output you produce must be as different as possible. You must produce another LTL property semantically different from the ones above that could capture the meaning of the input_natural_langauge."

    else:
        prev_output_str = ""
    system_prompt = "\n".join([init_cmd_str,format_description_str])
    user_prompt = "\n".join([final_cmd_str,input_str,prev_output_str])
    return system_prompt, user_prompt

def check_nl2ltltemplate_format(raw_output,ap_dict,dcmp=None):
    try:
        json_raw_output = json.loads(raw_output)
    except:
        return "output is not valid JSON"
    try:
        obj = nl2structnl.LTLTemplateTranslations(**json_raw_output)
    except Exception as e:
        return f"invalid output format: {e}"
    for json_output in json_raw_output["translations"]:
        err_msg = check_nl2ltltemplate_format_inner(json_output,ap_dict)
        if err_msg is not None:
            return "please output your full list after addressing the following problem: " + err_msg
    return None

def check_nl2ltltemplate_format_inner(json_output,ap_dict):
    if os.getenv("STRUCTNL_MODE") == "fretish":
        idx = json_output["chosen_template_ID"]
        if idx < 0 or idx >= len(structnl_ltl_list):
            return "chosen_template_ID is not valid"
        json_output["chosen_LTL_template"] = structnl_ltl_list[idx]["LTL"]
        bool_var_msg = f"Boolean expressions must only contain variables from the following: {str(list(ap_dict.keys()))}"
        bool_exp_list = [f"bool_exp{i}" for i in range(1,5)]
        for bool_name in bool_exp_list:
            if bool_name in json_output["chosen_LTL_template"]:
                if bool_name not in json_output:
                    return f"The chosen LTL template requires {bool_name} to be defined"
                err_msg = check_boolean_formula(json_output[bool_name],ret_err_msg=True)
                if err_msg != "":    
                    return f"{bool_name} {json_output[bool_name]} is not a valid boolean expression:\n{err_msg}"
                for var in get_variables_from_formula(json_output[bool_name]):
                    if var not in ap_dict:
                        return f"{bool_name}: {var} is not a valid atomic proposition. {bool_var_msg}"  
        if "N_DURATION" in json_output["chosen_LTL_template"] and not check_valid_nonnegative_integer(json_output["N_DURATION"]):
            return f"N_DURATION {json_output['N_DURATION']} is not a valid integer"
        return None
    elif os.getenv("STRUCTNL_MODE") == "SPS":
        idx = json_output["chosen_template_ID"]
        if idx < 0 or idx >= len(structnl_ltl_list):
            return "chosen_template_ID is not valid"
        json_output["chosen_LTL_template"] = structnl_ltl_list[idx]["LTL"]
        bool_var_msg = f"Boolean expressions must only contain variables from the following: {str(list(ap_dict.keys()))}"
        bool_exp_list = [f"bool_exp{i}" for i in range(1,7)]
        for bool_name in bool_exp_list:
            if bool_name in json_output["chosen_LTL_template"]:
                if bool_name not in json_output:
                    return f"The chosen LTL template requires {bool_name} to be defined"
                err_msg = check_boolean_formula(json_output[bool_name],ret_err_msg=True)
                if err_msg != "":    
                    return f"{bool_name} is not a valid boolean expression:\n{err_msg}"
                for var in get_variables_from_formula(json_output[bool_name]):
                    if var not in ap_dict:
                        return f"{bool_name}: {var} is not a valid atomic proposition. {bool_var_msg}"             
        return None    
    elif os.getenv("STRUCTNL_MODE") == "PSP":
        idx = json_output["chosen_template_ID"]
        if idx < 0 or idx >= len(structnl_ltl_list):
            return "chosen_template_ID is not valid"
        json_output["chosen_LTL_template"] = structnl_ltl_list[idx]["LTL"]
        bool_var_msg = f"Boolean expressions must only contain variables from the following: {str(list(ap_dict.keys()))}"
        for decision,item_list in nl2structnl.decision_to_item_list.items():
            for k in item_list:
                if k in json_output["chosen_LTL_template"]:
                    if "N_DURATION" not in k:
                        err_msg = check_boolean_formula(json_output[k],ret_err_msg=True)
                        if err_msg != "":
                            return f"{k} is not a valid boolean expression:\n{err_msg}"
                        for var in get_variables_from_formula(json_output[k]):
                            if var not in ap_dict:
                                return f"{k}: {var} is not a valid atomic proposition. {bool_var_msg}"
                    else:
                        if not check_valid_nonnegative_integer(json_output[k]):
                            return f"{k} {json_output[k]} is not a valid non-zero integer"
    else:
        assert False
    
def format_raw_nl2ltltemplate_output(raw_output,ap_dict):
    global structnl_ltl_list
    output_list = []
    json_raw_output = json.loads(raw_output)
    for cur_output in json_raw_output["translations"]:
        if ap_dict is None or check_nl2ltltemplate_format_inner(cur_output,ap_dict) is None:
            idx = cur_output["chosen_template_ID"]
            structnl_template = structnl_ltl_list[idx]["structnl"]
            ltl_template = structnl_ltl_list[idx]["LTL"]
            cur_output["chosen_LTL_template"] = ltl_template
            #ltl_template = cur_output["chosen_LTL_template"]
            """
            for decision,item_list in nl2structnl.decision_to_item_list.items():
                for k in item_list:
                    if k not in ltl_template:
                        cur_output[k] = None
                    if k in cur_output and cur_output[k] is not None:
                        #structnl_template = structnl_template.replace(k,str(cur_output[k]))
                        if "N_DURATION" not in k:
                            cur_exp = spot.formula(cur_output[k]).to_str(parenth=True)
                            if cur_exp == "1":
                                cur_exp = "TRUE"
                            elif cur_exp == "0":
                                cur_exp = "FALSE"
                            ltl_template = ltl_template.replace(k,f"({cur_exp})")
                            #ltl_template = ltl_template.replace(k,f"({str(cur_output[k])})")
                        else:
                            ltl_template = ltl_template.replace("N_DURATION+1",str(cur_output[k]+1))
                            ltl_template = ltl_template.replace("N_DURATION-1",str(cur_output[k]-1))
                            ltl_template = ltl_template.replace("N_DURATION",str(cur_output[k]))
            """
            ltl_template = nl2structnl.get_ltl_from_output(cur_output,ltl_template=ltl_template)
            #cur_output["structnl"] = structnl_template
            cur_output["output_LTL"] = ltl_template
            output_list.append(cur_output)
    return output_list

def get_nl2ltltemplate_translation(input_nl,ap_dict,model="gpt-4o-mini",max_retry=1,k=1,prev_outputs=None):
    if True:#model == "gemini-1.5-flash-001":
        k = 1
        prev_outputs=None
    system_prompt, user_prompt = get_LTLtemplate_prompt(input_nl,ap_dict,k=k,prev_outputs=prev_outputs)
    output = llm_prompt.prompt_loop(system_prompt, user_prompt, model, max_retry, check_output_func=check_nl2ltltemplate_format, schema=nl2structnl.LTLTemplateTranslations, ap_dict=ap_dict)
    if output is not None:
        output = format_raw_nl2ltltemplate_output(output,ap_dict)
        return output
    else:
        return []

def get_all_possible_ltltemplates_for_ex(output,MAX_DURATION=5):
    global structnl_ltl_list
    if os.getenv("STRUCTNL_MODE") == "fretish":
        key_list = ["bool_exp1","bool_exp2","bool_exp3","bool_exp4"]
        all_bools = []
        for k in key_list:
            if k in output and output[k] is not None and check_boolean_formula(output[k]):
                all_bools.append(output[k])
            else:
                all_bools.append(None)
        if "N_DURATION" in output["chosen_LTL_template"] and check_valid_nonnegative_integer(output["N_DURATION"]):
            duration_list = [output["N_DURATION"]]
        else:
            duration_list = [n_duration for n_duration in range(1,MAX_DURATION+1)]
    
        new_output_list = []
        for cur_bool in [all_bools]:
        #for cur_bool in [(output["bool_exp1"],output["bool_exp2"],output["bool_exp3"],output["bool_exp4"])]:
        #for bool_group in itertools.combinations(all_bools,4):
        #    for cur_bool in itertools.permutations(bool_group):
                for n_duration in range(1,MAX_DURATION+1):
                    for idx in range(len(structnl_ltl_list)):
                        new_output = output.copy()
                        new_output["bool_exp1"] = cur_bool[0]
                        new_output["bool_exp2"] = cur_bool[1]
                        new_output["bool_exp3"] = cur_bool[2]
                        new_output["bool_exp4"] = cur_bool[3]
                        new_output["N_DURATION"] = n_duration
                        new_output["chosen_template_ID"] = idx
                        new_output["chosen_LTL_template"] = structnl_ltl_list[idx]["LTL"]
                        new_output = format_raw_nl2ltltemplate_output(json.dumps({"translations":[new_output]}),ap_dict=None)[0]
                        new_output_list.append(new_output)
        return new_output_list
    elif os.getenv("STRUCTNL_MODE") == "SPS":
        key_list = ["bool_exp1","bool_exp2","bool_exp3","bool_exp4","bool_exp5","bool_exp6"]
        all_bools = []
        for k in key_list:
            if k in output and output[k] is not None and check_boolean_formula(output[k]):
                all_bools.append(output[k])
            else:
                all_bools.append(None)
        
        new_output_list = []
        for cur_bool in [all_bools]:
        #for cur_bool in [(output["bool_exp1"],output["bool_exp2"],output["bool_exp3"],output["bool_exp4"])]:
        #for bool_group in itertools.combinations(all_bools,4):
        #    for cur_bool in itertools.permutations(bool_group):
                for idx in range(len(structnl_ltl_list)):
                    new_output = output.copy()
                    new_output["bool_exp1"] = cur_bool[0]
                    new_output["bool_exp2"] = cur_bool[1]
                    new_output["bool_exp3"] = cur_bool[2]
                    new_output["bool_exp4"] = cur_bool[3]
                    new_output["bool_exp5"] = cur_bool[4]
                    new_output["bool_exp6"] = cur_bool[5]
                    new_output["chosen_template_ID"] = idx
                    new_output["chosen_LTL_template"] = structnl_ltl_list[idx]["LTL"]
                    new_output = format_raw_nl2ltltemplate_output(json.dumps({"translations":[new_output]}),ap_dict=None)[0]
                    new_output_list.append(new_output)
        return new_output_list
    else:
        assert False

def check_nl2ltl_format(raw_output,ap_dict,dcmp=None):
    try:
        json_raw_output = json.loads(raw_output)
    except:
        return "output is not valid JSON"
    try:
        obj = LTLTranslations(**json_raw_output)
    except Exception as e:
        return f"invalid output format: {e}"
    for json_output in json_raw_output["translations"]:
        err_msg = check_nl2ltl_format_inner(json_output,ap_dict)
        if err_msg is not None:
            return "please output your full list after addressing the following problem: " + err_msg
    return None

def check_nl2ltl_format_inner(json_output,ap_dict):
    if "output_LTL" not in json_output:
        return "missing output_LTL"
    f_str = json_output["output_LTL"]
    bool_var_msg = f"Boolean expressions must only contain variables from the following: {str(list(ap_dict.keys()))}"
    err_msg = check_ltl_formula(f_str,ret_err_msg=True)
    if err_msg != "":
        return f"output_LTL is not well-formed:\n{err_msg}"    
        #return "output_LTL is not well-formed"
    for var in get_variables_from_formula(f_str):
        if var not in ap_dict:
            return f"{var} is not a valid atomic proposition. {bool_var_msg}"
    return None

def format_raw_nl2ltl_output(raw_output,ap_dict):
    output_list = []
    json_raw_output = json.loads(raw_output)
    for json_output in json_raw_output["translations"]:
        if check_nl2ltl_format_inner(json_output,ap_dict) is None:
            output_list.append(json_output)
    return output_list

def get_nl2ltl_translation(input_nl,ap_dict,model="gpt-4o-mini",k=1,max_retry=1,prev_outputs=None):
    if True:#model == "gemini-1.5-flash-001":
        k = 1
        prev_outputs=None
    system_prompt, user_prompt = get_LTL_prompt(input_nl,ap_dict,k=k,prev_outputs=prev_outputs)
    output = llm_prompt.prompt_loop(system_prompt, user_prompt, model, max_retry, check_output_func=check_nl2ltl_format, schema=LTLTranslations, ap_dict=ap_dict)
    if output is not None:
        output = format_raw_nl2ltl_output(output,ap_dict)
        return output
    else:
        return []