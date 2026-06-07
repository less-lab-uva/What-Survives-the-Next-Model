import json
import llm_prompt
import spot
import pandas as pd
from spot_utils import *
from tqdm import tqdm
import itertools
import os

#_MODE_ = "fretish"
#_MODE_ = "SPS"

if os.getenv("STRUCTNL_MODE") == "fretish":
    from nl2structnl_fretish import *
elif os.getenv("STRUCTNL_MODE") == "SPS":
    from nl2structnl_sps import *
elif os.getenv("STRUCTNL_MODE") == "PSP":
    from nl2structnl_PSP import *
else:
    assert False

def get_output_options(output):
    out_dict = {}
    for decision in decision_to_item_list:
        out_dict[decision] = dict((k,output[k]) for k in decision_to_item_list[decision])
        out_dict[decision]["option"] = output[decision]
    return out_dict

def group_output_options_by_decomposition_list(output_list,dcmp_list):
    selected_options_dict = dict((k,[]) for k in dcmp_list)
    for output in output_list:
        for k in dcmp_list:
            selected_options_dict[k].append({})
        for decision in decision_to_item_list:
            cur_substring = output[decision+"_substring"]
            selected_options_dict[cur_substring][-1][decision] = dict((k,output[k]) for k in decision_to_item_list[decision])
            selected_options_dict[cur_substring][-1][decision]["option"] = output[decision]
    return selected_options_dict

def is_equal_intersection_option(option_dict1,option_dict2):
    all_decisions = set(list(option_dict1.keys())).intersection(list(option_dict2.keys()))
    for decision in all_decisions:
        if option_dict1[decision]["option"] != option_dict2[decision]["option"]:
            return False
        for k in decision_to_item_list[decision]:
            if option_dict1[decision][k] != option_dict2[decision][k]:
                return False
    return True

def get_dcmp_list_from_dcmp_structure(dcmp_structure):
    dcmp_list = []
    for decision in [entry+"_substring" for entry in decision_order]:
        for cur_substring in dcmp_structure[decision]:
            if cur_substring != "" and cur_substring not in dcmp_list:
                dcmp_list.append(cur_substring)
    return dcmp_list

def get_extrapolate_outputs(prev_outputs,MAX_DURATION=5,filter_mode="any contain",
                            get_ltl_from_output_func=get_ltl_from_output,
                            get_all_possible_options_func=get_all_possible_decision_options_for_ex,
                            mc_mode="spot"):
    assert filter_mode in ["any contain","any overlap",None]
    all_outputs = prev_outputs.copy()
    for entry in prev_outputs:
        all_outputs += get_all_possible_options_func(entry,MAX_DURATION=MAX_DURATION)
    print(len(all_outputs))
    all_ltl = []
    for entry in all_outputs:
        all_ltl.append(get_ltl_from_output_func(entry))
    #all_ltl = list(set(all_ltl))
    base_f_list = [get_ltl_from_output_func(entry) for entry in prev_outputs]
    if mc_mode == "spot" and filter_mode is not None:
        base_aut_list = [spot.translate(f) for f in base_f_list]
    overlap_idx_list = []
    unique_f = set()
    for i in tqdm(range(len(all_ltl))):
        f = all_ltl[i]
        if f not in unique_f and check_ltl_formula(f):
            unique_f.add(f)
            is_using_vars = any(set(get_variables_from_formula(f)) == (set(get_variables_from_formula(base_f))) for base_f in base_f_list)
            #is_using_vars = any(set(get_variables_from_formula(f)).issubset(set(get_variables_from_formula(base_f))) for base_f in base_f_list)
            if is_using_vars:
                if filter_mode is None:
                    is_pass = True
                else:
                    if mc_mode == "spot":
                        cur_aut = spot.translate(f)
                        if filter_mode == "any contain":
                            is_pass = any(spot.contains(base_aut,cur_aut) for base_aut in base_aut_list) or any(spot.contains(cur_aut,base_aut) for base_aut in base_aut_list)
                        elif filter_mode == "any overlap":
                            is_pass = any(spot.product(cur_aut,base_aut).accepting_run() is not None for base_aut in base_aut_list)
                        else:
                            assert False
                    elif mc_mode == "nusmv":
                        cur_var_dict = dict( (k,"boolean") for k in get_variables_from_formula(f))
                        is_pass = False
                        try:
                            if filter_mode == "any contain":
                                is_pass = any(nusmv_utils.get_nusmv_ltl_satisfiable({**cur_var_dict, **dict((k, "boolean") for k in get_variables_from_formula(base_f))},f"!({base_f}) & ({f})",bmc_k=None,timeout=1) is None \
                                              or nusmv_utils.get_nusmv_ltl_satisfiable({**cur_var_dict, **dict((k, "boolean") for k in get_variables_from_formula(base_f))},f"({base_f}) & !({f})",bmc_k=None,timeout=1) is None \
                                              for base_f in base_f_list)
                            elif filter_mode == "any overlap":
                                is_pass = any(nusmv_utils.get_nusmv_ltl_satisfiable({**cur_var_dict, **dict((k, "boolean") for k in get_variables_from_formula(base_f))},f"({base_f}) & ({f})",bmc_k=None,timeout=1) is not None for base_f in base_f_list)
                            else:
                                assert False
                        except TimeoutError as e:
                            print("caught timeout!")
                            pass
                    else:
                        assert False
                if is_pass:
                    overlap_idx_list.append(i)
    new_output_list = [all_outputs[idx] for idx in overlap_idx_list]
    #new_output_list = [new_output_list[idx] for idx in remove_equivalent_idx([get_ltl_from_output_func(entry) for entry in new_output_list],mc_mode=mc_mode)]
    return new_output_list