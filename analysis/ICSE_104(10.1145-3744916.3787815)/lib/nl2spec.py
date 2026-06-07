import json
import llm_prompt
import nl2structnl
from spot_utils import *
from pydantic import BaseModel
from typing import Optional
from typing import Dict, List
import os
import nl2ltl

nl2spec_tutorial = [
    {
        "input_natural_language": "Globally if a holds then c is true until b.",
        "atomic_propositions": {"a":"atomic propoisition a", "c":"atomic proposition c", "b":"atomic proposition b"},
        "explanation": "The phrase 'a holds' maps to atomic proposition a. "
                       "'c is true until b' maps to the subformula c U b. "
                       "The structure 'if a holds then c is true until b' becomes the implication a -> c U b. "
                       "'Globally' applies the G (always) operator, so the final formula is G(a -> (c U b)).",
        #"explanation_dict": {
        #    "a holds": "a",
        #    "c is true until b": "c U b",
        #    "if a holds then c is true until b": "a -> c U b",
        #    "Globally": "G"
        #},
        "explanation_dict": [
            {"natural_language": "a holds", "LTL": "a"},
            {"natural_language": "c is true until b", "LTL": "c U b"},
            {"natural_language": "if a holds then c is true until b", "LTL": "a -> c U b"},
            {"natural_language": "Globally", "LTL": "G"}
        ],
        "output_LTL": "G(a -> (c U b))"
    },
    {
        "input_natural_language": "Every request r is eventually followed by a grant g.",
        "atomic_propositions": {"r":"request", "g":"grant"},
        "explanation": "The phrase 'Request r' maps to atomic proposition r, and 'grant g' maps to g. "
                       "'Every' implies a global (G) operator, and 'eventually' is represented by F. "
                       "'Followed by' expresses a temporal implication, so the final formula is G(r -> F g).",
        #"explanation_dict": {
        #    "Request r": "r",
        #    "grant g": "g",
        #    "every": "G",
        #    "eventually": "F",
        #    "followed by": "->"
        #},
        "explanation_dict": [
            {"natural_language": "Request r", "LTL": "r"},
            {"natural_language": "grant g", "LTL": "g"},
            {"natural_language": "every", "LTL": "G"},
            {"natural_language": "eventually", "LTL": "F"},
            {"natural_language": "followed by", "LTL": "->"}
        ],
        "output_LTL": "G(r -> F g)"
    }
]

class subTranslation(BaseModel):
    natural_language: str
    LTL: str
    
class nl2specResult(BaseModel):
    explanation: str
    explanation_dict: List[subTranslation]
    output_LTL: str

class nl2specTranslations(BaseModel):
    translations: List[nl2specResult]
    
def get_nl2spec_prompt(input_nl,ap_dict):
    instruction = "Translate the following natural language sentences into an LTL formula and explain your translation step by step. Remember that X means 'next', U means 'until', G means 'globally', F means 'finally', which means GF means 'infinitely often'. The formula should only contain atomic propositions or operators &, |, !, ->, <->, X, U, G, F. Your output should follow the JSON format."

    nl2spec_tutorial_str = json.dumps(nl2spec_tutorial)

    input_str = "{\n"
    input_str += f"\"input_natural_language\":\"{input_nl}\",\n"
    input_str += f"\"atomic_propositions\":{json.dumps(ap_dict)},\n"
    input_str += "}\n"
    
    system_prompt = "\n".join([instruction])
    user_prompt = "\n".join([nl2spec_tutorial_str,input_str])
    return system_prompt, user_prompt

def get_nl2spec_translation(input_nl,ap_dict,model="gpt-4o-mini",k=1,max_retry=1,prev_outputs=None):
    system_prompt, user_prompt = get_nl2spec_prompt(input_nl,ap_dict)#,k=k,prev_outputs=prev_outputs)
    output = llm_prompt.prompt_loop(system_prompt, user_prompt, model, max_retry, check_output_func=nl2ltl.check_nl2ltl_format, schema=nl2specTranslations, ap_dict=ap_dict)
    if output is not None:
        output = nl2ltl.format_raw_nl2ltl_output(output,ap_dict)
    return output