import pandas as pd
from nl2structnl import *
import nl2structnl_fretish
import nl2structnl_PSP
import nl2ltl
import itertools
import spot_utils

print(df_option_names)

def extract_options_for_group(options_per_group,group_idx):
    res = []
    all_cur_options = []
    cur_decision_ids = []
    for decision_id in options_per_group[group_idx]:
        all_cur_options.append(options_per_group[group_idx][decision_id])
        cur_decision_ids.append(decision_id)
    for entry in itertools.product(*all_cur_options):
        res.append(dict( (cur_decision_ids[i],entry[i]) for i in range(len(entry))))
    return res
    
def get_all_option_data(df_row,option_names):
    res = []
    for option_name in option_names:
        try:
            data = json.loads(df_row[option_name])
        except Exception as e:
            print(df_row)
            print(option_name)
            print(df_row[option_name])
            raise e
        res.append(data)
    return res

def postprocess_fretish_outputs_N_DURATION(output_list,max_N_DURATION):
    res = []
    for output in output_list:
        if "N_DURATION" in nl2structnl_fretish.extract_structnl_from_output(output) and output["N_DURATION"] is None:
            for N_DURATION in range(1,max_N_DURATION+1):
                new_output = output.copy()
                new_output["N_DURATION"] = N_DURATION
                res.append(new_output)
        else:
            res.append(output)
    return res

def get_all_outputs_from_options_per_group(all_options_per_group):
    #all_options_per_group = option type X group X decisions
    res = []
    num_groups = len(all_options_per_group[0])
    for group_idx in range(num_groups):
        cur_group_options = []
        for options_per_group in all_options_per_group:
            cur_group_options.append(extract_options_for_group(options_per_group,group_idx))
        cur_group_outputs = []
        for entry in itertools.product(*cur_group_options):
            output_dict = {}
            for part_dict in entry:
                output_dict.update(part_dict)
            cur_group_outputs.append(output_dict)
        res += cur_group_outputs
    return res

def get_all_outputs_for_df_row(df_row,max_N_DURATION=5,group_by_template=False,structnl="fretish"):
    if structnl == "fretish":
        decision_to_item_list = nl2structnl_fretish.decision_to_item_list
        df_option_names = nl2structnl_fretish.df_option_names
    elif structnl == "PSP":
        decision_to_item_list = nl2structnl_PSP.decision_to_item_list
        df_option_names = nl2structnl_PSP.df_option_names
    else:
        assert False
    #global decision_to_item_list
    #global df_option_names

    all_options_per_group = get_all_option_data(df_row,df_option_names)
    #all_options_per_group = option type X group X decisions
    
    output_list = get_all_outputs_from_options_per_group(all_options_per_group)
    if structnl == "fretish" and max_N_DURATION is not None:
        if not group_by_template:
            res = postprocess_fretish_outputs_N_DURATION(output_list,max_N_DURATION=max_N_DURATION)
        else:
            res = []
            for output in output_list:
                res.append(postprocess_fretish_outputs_N_DURATION([output],max_N_DURATION=max_N_DURATION))
    else:
        res = output_list
    
    for output in res:
        for decision,item_list in decision_to_item_list.items():
            for item in item_list:
                if item not in output:
                    output[item] = None
    return res

def get_ap_dict(var_df):
    ap_dict = {}
    var_names = var_df["variable name"]
    var_descriptions = var_df["description"]
    for i in range(len(var_df)):
        ap_dict[var_names[i]] = var_descriptions[i]
    return ap_dict

def load_outputs(result_dir,cur_dataset_name,row_idx,model,num_trial,cur_method,cur_mode,max_N_DURATION=None,structnl="fretish"):
    cur_exp_name = f"{result_dir}/{cur_dataset_name}-{row_idx}_model-{model}_trials-{num_trial}"
    
    with open(cur_exp_name + "_" + cur_method +".json", "r") as json_file:
        cur_outputs = json.load(json_file)

    if structnl == "fretish":
        get_ltl_from_output = nl2structnl_fretish.get_ltl_from_output
        get_all_possible_decision_options_for_ex = nl2structnl_fretish.get_all_possible_decision_options_for_ex
    elif structnl == "PSP":
        get_ltl_from_output = nl2structnl_PSP.get_ltl_from_output
        get_all_possible_decision_options_for_ex = nl2structnl_PSP.get_all_possible_decision_options_for_ex
    else:
        assert False
    
    if cur_method in ["nl2ltltemplate","nl2ltl","nl2spec","NL2TL","deepstl","synthtl","NL2TL-FT"]:
        get_ltl_from_output_func = lambda x : x["output_LTL"]
        get_all_possible_options_func = nl2ltl.get_all_possible_ltltemplates_for_ex
    elif cur_method in ["nl2structnl-reflect","nl2structnl","nl2structnl_dcmp"]:
        get_ltl_from_output_func = get_ltl_from_output
        get_all_possible_options_func = get_all_possible_decision_options_for_ex
    else:
        assert False
    cur_outputs= [output for output in cur_outputs if spot_utils.check_ltl_formula(get_ltl_from_output_func(output))]
    
    if cur_mode == "extra":
        cur_outputs = get_extrapolate_outputs(cur_outputs,
                                                             MAX_DURATION=max_N_DURATION,
                                                             #filter_mode="any contain",
                                                             filter_mode=None,
                                                             get_ltl_from_output_func=get_ltl_from_output_func,
                                                             get_all_possible_options_func=get_all_possible_options_func,
                                                             #mc_mode="nusmv"
                                                            )
    if cur_method in ["nl2structnl-reflect","nl2structnl","nl2structnl_dcmp"]:
        output_ltl_list = [get_ltl_from_output(entry) for entry in cur_outputs]
    elif cur_method in ["nl2ltltemplate","nl2ltl","nl2spec","NL2TL","deepstl","synthtl","NL2TL-FT"]:
        output_ltl_list = [spot_utils.filter_ltl_formula(entry["output_LTL"]) for entry in cur_outputs]
    else:
        assert False
    return cur_outputs, output_ltl_list

def load_labels(data_home_dir,cur_dataset_name,row_idx,max_N_DURATION=None,cur_df_file=None,structnl="fretish"):
    if cur_df_file is None:
        cur_df_file = data_home_dir + cur_dataset_name + "/PlausibleSpecs.xlsx"
    df = pd.read_excel(cur_df_file, engine='openpyxl')
    label_output_list = get_all_outputs_for_df_row(df.iloc[row_idx],max_N_DURATION=max_N_DURATION,structnl=structnl)
    if structnl == "fretish":
        label_ltl_list = [nl2structnl_fretish.get_ltl_from_output(output) for output in label_output_list]
    elif structnl == "PSP":
        label_ltl_list = [nl2structnl_PSP.get_ltl_from_output(output) for output in label_output_list]
    else:
        assert False
    return label_output_list, label_ltl_list

def load_vars(data_home_dir,cur_dataset_name,row_idx=None):
    cur_var_file = data_home_dir + cur_dataset_name + "/Variables.xlsx"
    if os.path.exists(cur_var_file):
        var_df = pd.read_excel(cur_var_file, engine='openpyxl')
        ap_dict = get_ap_dict(var_df)
        return ap_dict
    cur_var_file = data_home_dir + cur_dataset_name + "/PlausibleSpecs.xlsx"
    if os.path.exists(cur_var_file):
        df = pd.read_excel(cur_var_file, engine='openpyxl')
        ap_dict = json.loads(df.iloc[row_idx]["ap_dict"])
        return ap_dict
    assert False, "cannot load ap_dict!"