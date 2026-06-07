import subprocess
import re

def call_nusmv(smv_file,bmc_k=None,timeout=None):
    #cur_tool = "NuSMV"
    cur_tool = "nuXmv"
    try:
        if bmc_k is not None:
            result = subprocess.run([cur_tool, "-bmc","-bmc_length", str(bmc_k), "-ctt", smv_file], 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
            return result.stdout, result.stderr
        else:
            result = subprocess.run([cur_tool, smv_file], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
            return result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        raise TimeoutError(f"nusmv exceeded timeout of {timeout} seconds") from e
    except Exception as e:
        return str(e), None

def detect_counterexample(output):
    if re.search(r'-- specification.*is false', output):
        return True
    elif re.search(r'-- specification.*is true', output):
        return False
    elif re.search(r'-- no counterexample found with bound',output):
        return False
    else:
        print(output)
        assert False, "could not tell if nusmv returns a trace or not"

def parse_nusmv_trace(output):
    assignment_pattern = re.compile(r'\s*([\w.]+)\s*=\s*(\w+)')
    lines = output.splitlines()
    trace_list = []
    is_found_loop = False
    loop_idx = 0
    for i, line in enumerate(lines):
        if re.search(r'-- specification.*is false', line):
            pass
        elif re.search(r'-> State: *', line):
            if len(trace_list) > 1:
                for var in trace_list[-2]:
                    if var not in trace_list[-1]:
                        trace_list[-1][var] = trace_list[-2][var]
            trace_list.append({})
            if not is_found_loop:
                loop_idx += 1
        elif re.search(r'\s*([\w.]+)\s*=\s*(\w+)', line):
            match = assignment_pattern.match(line)
            var_name = match.group(1)
            var_value = match.group(2)
            trace_list[-1][var_name] = var_value
        elif re.search(r'-- Loop starts here', line):
            is_found_loop = True
    if len(trace_list) > 1:
        for var in trace_list[-2]:
            if var not in trace_list[-1]:
                trace_list[-1][var] = trace_list[-2][var]
    #if loop_idx >= len(trace_list):
    #    print(trace_list[loop_idx:])
    #    print(output)
    prefix_list,cycle_list = trace_list[:loop_idx], trace_list[loop_idx:][:-1]
    return [e for e in prefix_list if len(e) > 0],[e for e in cycle_list if len(e) > 0]

def nusmv_construct_str(prop_list):
    if len(prop_list) == 0:
        return "TRUE"
    res_str = ""
    if len(prop_list) > 0:
        #var_assignment = [var_name+"="+val for var_name,val in prop_list[0].items()]
        var_assignment = [f"({var_name})" if val == "TRUE" else f"!({var_name})" for var_name, val in prop_list[0].items()]
        res_str += "(" + " & ".join(var_assignment) + ")"
    for i in range(1,len(prop_list)):
        #var_assignment = [var_name+"="+val for var_name,val in prop_list[i].items()]
        var_assignment = [f"({var_name})" if val == "TRUE" else f"!({var_name})" for var_name, val in prop_list[i].items()]
        res_str +=  " & (" + i*" X " +"(" + " & ".join(var_assignment) + ") ) "    
    return "("+res_str+")"

def nusmv_trace_to_formula(trace):
    prefix_list, cycle_list = trace
    
    prefix_str = nusmv_construct_str(prefix_list)
    if len(cycle_list) > 0:
        cycle_str = nusmv_construct_str(cycle_list)
        cycle_condition_str = " G " + "(" + cycle_str + " <-> ("+ len(cycle_list)*" X " + cycle_str + " ) )"
        full_form = prefix_str + " & " + len(prefix_list)*" X " + cycle_str + " & " + len(prefix_list)*" X " + cycle_condition_str
        return full_form
    else:
        return prefix_str

def nusmv_formula_to_file(smv_fname,var_dict,formula_str):
    total_str = "MODULE main\n"
    total_str += "VAR\n"
    #for entry in var_list:
    #    total_str += entry["name"] + " : " + entry["type"] + ";\n"
    for var_name, var_type in var_dict.items():
        total_str += var_name + " : " + var_type + ";\n"
    total_str += "JUSTICE TRUE;\n"
    total_str += "LTLSPEC\n"
    total_str += formula_str
    f = open(smv_fname,"w")
    f.write(total_str)
    f.close()

def check_valid_nusmv_formula(var_dict,formula_str,ret_string=False,smv_fname="tmp1.smv"):
    valid_formula_str = "( " + formula_str + ") & !(" + formula_str + " )"
    nusmv_formula_to_file(smv_fname,var_dict,valid_formula_str)
    raw_out,raw_err = call_nusmv(smv_fname)
    if not ret_string:
        return raw_err == ""
    else:
        return raw_err


def fix_nusmv_trace(trace,f_str,var_dict,bmc_k):
    bad_prefix,bad_cycle = trace
    for i in range(len(bad_cycle)):
        #new_trace = (bad_prefix+bad_cycle[:-i],bad_cycle[-i:])
        new_trace = (bad_prefix+bad_cycle[:i],bad_cycle[i:])
        mod_trace_formula = nusmv_trace_to_formula(new_trace)
        if get_nusmv_ltl_satisfiable(var_dict,f"({f_str}) & ({mod_trace_formula})",bmc_k=bmc_k) is not None:
            #assert get_nusmv_ltl_true(var_dict,f"({mod_trace_formula}) -> ({f_str})",bmc_k=bmc_k) is None
            return new_trace
    return None

def get_nusmv_ltl_satisfiable(var_dict,formula_str,bmc_k=None,use_trace=False,timeout=None,smv_fname="tmp1.smv"):
    tmp_formula_str = "!(" + formula_str + ")"
    nusmv_formula_to_file(smv_fname,var_dict,tmp_formula_str)
    raw_out,raw_err = call_nusmv(smv_fname,bmc_k=bmc_k,timeout=timeout)
    if raw_err == "":
        if detect_counterexample(raw_out):
            trace = parse_nusmv_trace(raw_out)
            if use_trace:
                return fix_nusmv_trace(trace,formula_str,var_dict,bmc_k=bmc_k)
            else:
                return trace
        else:
            return None
    elif "The initial states set of the finite state machine is empty." in raw_err:
        return None
    else:
        assert False, raw_err

def get_nusmv_ltl_true(var_dict,formula_str,bmc_k=None,timeout=None,smv_fname="tmp1.smv"):
    #return None if true
    nusmv_formula_to_file(smv_fname,var_dict,formula_str)
    raw_out,raw_err = call_nusmv(smv_fname,bmc_k=bmc_k,timeout=timeout)
    if raw_err == "":
        if detect_counterexample(raw_out):
            return parse_nusmv_trace(raw_out)
        else:
            return None
    elif "The initial states set of the finite state machine is empty." in raw_err:
        return None
    else:
        assert False, raw_err   

def get_nusmv_ltl_equivalent(var_dict_a,formula_str_a,var_dict_b,formula_str_b,bmc_k=None,timeout=None,smv_fname="tmp1.smv"):
    total_var_dict = var_dict_a.copy()
    for var_name,var_type in var_dict_b.items():
        total_var_dict[var_name] = var_type
    total_formula = "( ( "+formula_str_a + " ) & !( " + formula_str_b + " ) ) | ( !( " + formula_str_a + " ) & ( " + formula_str_b + " ) )"
    trace = get_nusmv_ltl_satisfiable(var_dict=total_var_dict,formula_str=total_formula,bmc_k=bmc_k,timeout=timeout,smv_fname=smv_fname)
    return trace == None

def get_min_var_dict(in_var_dict,ltl_str):
    out_var_dict = in_var_dict.copy()
    for k,v in in_var_dict.items():
        del out_var_dict[k]
        if not check_valid_nusmv_formula(out_var_dict,ltl_str):
            out_var_dict[k] = v
    return out_var_dict

def get_num_vars_in_trace(trace):
    prefix_list, cycle_list = trace
    if len(prefix_list) > 0:
        return len(prefix_list[0])
    elif len(cycle_list) > 0:
        return len(cycle_list[0])
    else:
        return 0