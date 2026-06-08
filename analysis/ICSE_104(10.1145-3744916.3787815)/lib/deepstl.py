import json
import nl2ltl
import llm_prompt

def get_LTL_prompt(input_nl,ap_dict):
    init_cmd_str = "You are an expert in translating natural language to linear temporal logic (LTL). Your job is to translate natural language to LTL using given atomic propositions.\n"
    #init_cmd_str += "You must only use LTL operators and the given atomic propositions. Recall that in LTL, G = globally, F = eventually, V = releases, X = next, U = until. You may use boolean operators (e.g., !, &, |, ->, <->) and can only use atomic propositions (NO NUMERICAL COMPARISON OPERATORS ALLOWED)\n"
    
    #format_description_str = \
    """
    Inputs consist of:
    1. input_natural_language
    2. atomic_propositions (dictionary mapping atomic proposition names to descriptions)
    
    Your output should follow this JSON schema:
    {
     "type": "object",
     "properties": { "output_LTL": { "type": "string" } },
     "required": ["output_LTL"]
    }
    """

    final_cmd_str = "Translate the following natural language to LTL and put your output in a JSON dictionary with field \"output_LTL\":\n"
    input_str = "{\n"
    input_str += f"\"atomic_propositions\":{json.dumps(ap_dict)},\n"
    input_str += f"\"input_natural_language\":\"{input_nl}\",\n"
    input_str += "}\n"
    #system_prompt = "\n".join([init_cmd_str,format_description_str])
    system_prompt = "\n".join([init_cmd_str])
    user_prompt = "\n".join([final_cmd_str,input_str])
    return system_prompt, user_prompt

def check_deepstl_format(raw_output,ap_dict):
    try:
        json_output = json.loads(raw_output)
    except:
        return "output is not valid JSON"
    err_msg = nl2ltl.check_nl2ltl_format_inner(json_output,ap_dict)
    if err_msg is not None:
        return "please output your translation addressing the following problem: " + err_msg
    return None

def format_raw_deepstl_output(raw_output,ap_dict):
    output_list = []
    json_output = json.loads(raw_output)
    if nl2ltl.check_nl2ltl_format_inner(json_output,ap_dict) is None:
        output_list.append(json_output)
    return output_list

def get_nl2ltl_translation(input_nl,ap_dict,model="gpt-4o-mini",k=1,max_retry=1,prev_outputs=None):
    system_prompt, user_prompt = get_LTL_prompt(input_nl,ap_dict)
    output = llm_prompt.prompt_loop(system_prompt, user_prompt, f"deepstl-{model}", max_retry, check_output_func=check_deepstl_format, schema=None, ap_dict=ap_dict)
    if output is not None:
        output = format_raw_deepstl_output(output,ap_dict)
        return output
    else:
        return []