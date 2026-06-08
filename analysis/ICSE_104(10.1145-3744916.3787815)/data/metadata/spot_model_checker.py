import spot
import json
import sys

aut_dict = {}
def get_aut(f):
    global aut_dict
    if f not in aut_dict:
        aut_dict[f] = spot.translate(f)
    return aut_dict[f]

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

def trace_to_formula(trace):
    #acc_run = trace.accepting_run()
    acc_run = trace.accepting_word()
    #WARNING?: if there's no prefix, then the produced formula does not contain the trace, but the trace contains the formula
    if acc_run is None:
        return None
        
    prefix_list = get_trace_prefix_list(trace,acc_run)

    cycle_list = get_trace_cycle_list(trace,acc_run)
    
    prefix_str = construct_str(prefix_list)
    
    cycle_str = construct_str(cycle_list)
    cycle_condition_str = "G" + "(" + cycle_str + " <-> "+ len(cycle_list)*"X" + cycle_str + ")"
    full_form = prefix_str + " & " + len(prefix_list)*"X" + cycle_str + " & " + len(prefix_list)*"X" + cycle_condition_str
    full_form = spot.formula(full_form).to_str(parenth=True)
    return full_form

with open(sys.argv[1], "r") as f:
    input_list = json.load(f)


res = []
for check_type,formulas in input_list:
	if check_type == 'equivalence':
		f1,f2 = formulas
		res.append(spot.are_equivalent(get_aut(f1),get_aut(f2)))
	elif check_type == 'subset':
		f1,f2 = formulas
		res.append(spot.contains(get_aut(f2),get_aut(f1)))
	elif check_type == 'superset':
		f1,f2 = formulas
		res.append(spot.contains(get_aut(f1),get_aut(f2)))
	elif check_type == 'overlap':
		f1,f2 = formulas
		res.append(spot.product(get_aut(f1),get_aut(f2)).accepting_run() is not None)
	elif check_type == 'satisfiable':
		found_unsat = False
		cur_aut = spot.translate('1')
		for f in formulas:
			cur_aut = spot.product(cur_aut,get_aut(f)).postprocess()
			if cur_aut.accepting_run() is None:
				found_unsat = True
				break
		res.append(not found_unsat)
	elif check_type == 'trace':
		found_unsat = False
		cur_aut = spot.translate('1')
		for f in formulas:
			cur_aut = spot.product(cur_aut,get_aut(f)).postprocess()
			if cur_aut.accepting_run() is None:
				found_unsat = True
				break
		if not found_unsat:
			res.append(trace_to_formula(cur_aut))
		else:
			res.append(None)
	elif check_type == 'translate':
		for f in formulas:
			tmp = spot.translate(f).postprocess('det')
print(json.dumps(res))