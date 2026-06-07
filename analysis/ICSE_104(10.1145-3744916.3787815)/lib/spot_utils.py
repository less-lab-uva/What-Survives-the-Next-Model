import spot

def construct_str(prop_list):
    if len(prop_list) == 0:
        return "1"
    res_str = ""
    if len(prop_list) > 0:
        res_str += "(" + prop_list[0] + ") "
    for i in range(1,len(prop_list)):
        res_str +=  "& " + i*"X" +"(" + prop_list[i] + ") "    
    return "("+res_str+")"

def get_trace_prefix_list(automaton,acc_run):
    prefix_list = []
    for i in range(len(acc_run.prefix)):
        #prefix_list.append(spot.bdd_format_formula(automaton.get_dict(), acc_run.prefix[i].label))
        prefix_list.append(spot.bdd_format_formula(automaton.get_dict(), acc_run.prefix[i]))
    return prefix_list

def get_trace_cycle_list(automaton,acc_run):
    cycle_list = []
    for i in range(len(acc_run.cycle)):
        #cycle_list.append(spot.bdd_format_formula(automaton.get_dict(), acc_run.cycle[i].label))
        cycle_list.append(spot.bdd_format_formula(automaton.get_dict(), acc_run.cycle[i]))
    return cycle_list

def get_stepwise_formula_lists(trace):
    automaton = trace.as_automaton()
    #acc_run = automaton.accepting_run()
    acc_run = automaton.accepting_word()
    
    prefix_list = get_trace_prefix_list(automaton,acc_run)
    cycle_list = get_trace_cycle_list(automaton,acc_run)
    return prefix_list, cycle_list

def trace_to_formula(trace,debug=True):
    #acc_run = trace.accepting_run()
    acc_run = trace.accepting_word()
    #WARNING?: if there's no prefix, then the produced formula does not contain the trace, but the trace contains the formula
    
    prefix_list = get_trace_prefix_list(trace,acc_run)

    cycle_list = get_trace_cycle_list(trace,acc_run)
    
    prefix_str = construct_str(prefix_list)
    
    cycle_str = construct_str(cycle_list)
    cycle_condition_str = "G" + "(" + cycle_str + " <-> "+ len(cycle_list)*"X" + cycle_str + ")"
    full_form = prefix_str + " & " + len(prefix_list)*"X" + cycle_str + " & " + len(prefix_list)*"X" + cycle_condition_str
    full_form = spot.formula(full_form).to_str(parenth=True)
    if debug:
        assert spot.are_equivalent(spot.formula(full_form),trace)
    return full_form

def filter_ltl_formula(f_str):
    spot_f = spot.formula(f_str)
    spot_f = spot.unabbreviate(spot_f, "RW")
    new_f_str = spot_f.to_str(parenth=True)
    if new_f_str == "1":
        return "TRUE"
    elif new_f_str == "0":
        return "FALSE"
    else:
        return new_f_str.replace("(0)","(FALSE)").replace("(1)","(TRUE)").replace("(1 ","(TRUE ")

def check_ltl_formula(f_str,ret_err_msg=False):
    try:
        filter_ltl_formula(f_str)
        spot_f = spot.formula(f_str)
        is_ltl = spot_f.is_ltl_formula()   
    except Exception as e:
        if ret_err_msg:
            return str(e)
        else:
            return False
    if ret_err_msg:
        if is_ltl:
            return ""
        else:
            return "the formula is not LTL"
    else:
        return is_ltl 

def check_boolean_formula(f_str,ret_err_msg=False):
    try:
        spot_f = spot.formula(f_str)
        is_bool = spot_f.is_boolean()
    except Exception as e:
        if ret_err_msg:
            return str(e)
        else:
            return False
    if ret_err_msg:
        if is_bool:
            return ""
        else:
            return "the formula is not boolean"
    else:
        return is_bool

def check_nontrivial_boolean_formula(f_str):
    #assumes f_str is valid boolean formula
    return not spot.are_equivalent(f_str,"1") and not spot.are_equivalent(f_str,"0")

def get_variables_from_formula(formula_str):
    spot_formula = spot.formula(formula_str)
    ap = spot.atomic_prop_collect(spot_formula)
    return [str(entry) for entry in ap]

def check_valid_nonnegative_integer(f_str):
    try:
        val = int(f_str)
        return val > 0
    except:
        return False

def check_satisfiable(formula_str):
    #returns None if not satisfiable, otherwise, returns a spot word (trace)
    spot_formula = spot.formula(formula_str)
    automaton = spot_formula.translate()
    automaton.merge_edges()
    #trace = automaton.accepting_word()
    trace_word = automaton.accepting_word()
    if trace_word is not None:
        return trace_word.as_automaton()
    else:
        return None