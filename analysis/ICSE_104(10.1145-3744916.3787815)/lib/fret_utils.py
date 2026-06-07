import subprocess
import itertools

def call_fret_formalize(fretish_str):
    try:
        command = [
            "npm", "run", "--prefix", "/Users/USERNAMEHERE/fret/fret-electron", "--silent", "start-cli", "--", "formalize", "-l", "ft-inf",
            fretish_str
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.stdout != 'No\n':
            return result.stdout, result.stderr
        else:
            return "", "invalid FRETish"
    except Exception as e:
        return str(e), None

def generate_all_scope_options(scope_mode_list):
    scope_options = [""]
    for mode in scope_mode_list:
        #for scope_option in ["before", "only before", "while", "when not in", "only while", "after", "only after"]:
        for scope_option in ["only before", "while", "only while", "after", "only after"]:
        #for scope_option in ["while", "only while"]:
            scope_options.append(scope_option + " " + mode)
    return scope_options

def generate_all_condition_options(condition_exp_list):
    condition_options = [
        ""
    ]
    for condition_option in ["upon","whenever"]:
        for condition_exp in condition_exp_list:
            condition_options.append(condition_option + " " + condition_exp)
    return list(set(condition_options))

def generate_all_timing_options(stop_cond_list,additional_options=[]):
    timing_options = [
        "immediately",
        "at the next timepoint",
        #"at the last timepoint",
        "eventually",
        "always",
        "never",
    ]
    timing_options += additional_options
    for time_option in ["within","for","after"]:
        for i in range(5):
            timing_options.append(time_option + " " + str(i+1) + " ticks")
    for time_option in ["until","before"]:
        for stop_cond in stop_cond_list:
            timing_options.append(time_option + " " + stop_cond)
    return list(set(timing_options))

def get_fields_to_fretish(scope,condition,component,timing,response):
    res_str = scope + " " 
    res_str += condition + " " 
    res_str += component +" shall " + timing + " satisfy " + response
    return " ".join(res_str.split())

def get_fretish_to_ltl_dict(scope_options,condition_options,component_options,timing_options,response_options):
    fretish_to_ltl = {}
    for scope,condition,component,timing,response in itertools.product(scope_options,condition_options,component_options,timing_options,response_options):    
        cur_fretish = get_fields_to_fretish(scope,condition,component,timing,response)
        ltl_str,err_str = call_fret_formalize(cur_fretish)
        if err_str == "":
            fretish_to_ltl[cur_fretish] = ltl_str.replace("\n","")
        else:
            print(cur_fretish,err_str)
    return fretish_to_ltl
