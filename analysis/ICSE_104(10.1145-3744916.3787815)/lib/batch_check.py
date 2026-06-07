from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import re
import json
from tqdm import tqdm
import spot
import itertools
import spot_utils
from automaton_utils import *
import nusmv_utils
import os

DATA_HOME_DIR = os.getenv("DATA_HOME_DIR")
SMV_FILE_DIR = os.getenv("SMV_FILE_DIR")

def run_in_parallel_preserve_order(jobs, max_workers=4):
    results = [None] * len(jobs)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(func, *args): i
            for i, (func, args) in enumerate(jobs)
        }

        for future in as_completed(future_to_index):
            i = future_to_index[future]
            try:
                results[i] = future.result()
            except TimeoutError as e:
                results[i] = "Timeout exceeded"

    return results

def parse_nusmv_batch_results(raw_out,check_f_list,bmc_k):
    #print(raw_out)
    false_pattern = re.compile(r"^-- specification\s+(.*?)\s+is false", re.MULTILINE)
    false_formulas = false_pattern.findall(raw_out)
    false_formulas = [spot_utils.filter_ltl_formula(entry) for entry in false_formulas]
    true_pattern = re.compile(r"^-- specification\s+(.*?)\s+is true", re.MULTILINE)
    true_formulas = true_pattern.findall(raw_out)
    true_formulas = [spot_utils.filter_ltl_formula(entry) for entry in true_formulas]
    """
    assert len(check_f_list) == 1 #reverting to 1 formula per nusmv query since nusmv changes the formula syntax and cannot be consistently parsed
    if len(true_formulas) == 0 and len(false_formulas) == 0:
        #nusmv returned partial output but did not finish
        return [None]
    assert (len(true_formulas) == 1 and len(false_formulas) == 0) or (len(true_formulas) == 0 and len(false_formulas) == 1),f"{str(check_f_list)}\n{raw_out}"
    return [len(true_formulas) > 0]
    """
    res = []
    for i in range(len(check_f_list)):
        formula = check_f_list[i]
        #cur_f = spot.formula(formula).to_str(parenth=True)
        cur_f = spot_utils.filter_ltl_formula(formula)
        if bmc_k is None and cur_f not in true_formulas and cur_f not in false_formulas:
            assert len(check_f_list) > len(true_formulas) + len(false_formulas)
            res.append(None)
        else:
            res.append(cur_f not in false_formulas)
        #assert cur_f in true_formulas or cur_f in false_formulas, f"{i}: {cur_f}\n{raw_out}"
    return res

def nusmv_batch_job(total_var_dict,check_f_list,smv_fname,timeout=None,bmc_k=None):
    total_str = "MODULE main\n"
    total_str += "VAR\n"
    for var_name, var_type in total_var_dict.items():
        total_str += var_name + " : " + var_type + ";\n"
    total_str += "JUSTICE TRUE;\n"
    for formula in check_f_list:
        total_str += "LTLSPEC\n"
        total_str += f"{formula}\n\n"
    f = open(smv_fname,"w")
    f.write(total_str)
    f.close()
    raw_out,raw_err = nusmv_utils.call_nusmv(smv_fname,bmc_k=bmc_k,timeout=timeout)
    res = parse_nusmv_batch_results(raw_out,check_f_list,bmc_k=bmc_k)
    if timeout is None:
        assert not any(entry is None for entry in res),print(raw_out,"\n",raw_err)
    return res

def subprocess_batch_nusmv_MC(all_jobs,smv_fname,bmc_k=None,timeout=None):
    total_var_dict, check_f_list = to_smv_batch_job_list(all_jobs)
    results = nusmv_batch_job(total_var_dict,check_f_list,smv_fname=smv_fname,timeout=timeout,bmc_k=bmc_k)
    for i in range(len(all_jobs)):
        if all_jobs[i][0] == "overlap" and results[i] is not None:
            results[i] = not results[i]
    return results

def dispatch_batch_MC(all_jobs,spot_timeout=0.2,nusmv_timeout=None,nusmv_jobs_per_thread=1,bmc_k=None,thread_id=0):
    if spot_timeout > 0:    
        success = True
        try:
            results = subprocess_batch_spot_MC(all_jobs,job_fname=SMV_FILE_DIR+f"/tmp{thread_id}.smv",timeout=spot_timeout)
        except subprocess.TimeoutExpired as e:
            success = False
        except Exception as e:
            print(e)
            success = False
        if success:
            return results
    results = []
    for i in range(len(all_jobs)//nusmv_jobs_per_thread + len(all_jobs)%nusmv_jobs_per_thread):
        #total_var_dict, check_f_list = to_smv_batch_job_list(all_jobs[i*nusmv_jobs_per_thread:i*nusmv_jobs_per_thread+nusmv_jobs_per_thread])
        try:
            cur_results = subprocess_batch_nusmv_MC(all_jobs[i*nusmv_jobs_per_thread:i*nusmv_jobs_per_thread+nusmv_jobs_per_thread],
                                                    smv_fname=SMV_FILE_DIR+f"/tmp{thread_id}.smv",
                                                    timeout=nusmv_timeout,
                                                    bmc_k=bmc_k,
                                                   )
            #cur_results = nusmv_batch_job(total_var_dict,check_f_list,smv_fname=SMV_FILE_DIR+f"/tmp{thread_id}.smv",timeout=nusmv_timeout)
            results += cur_results
        except TimeoutError as e:
            results += [None for entry in all_jobs[i*nusmv_jobs_per_thread:i*nusmv_jobs_per_thread+nusmv_jobs_per_thread]]
    return results

def parallel_dispatch_batch_MC(all_jobs,jobs_per_thread=None,spot_timeout=0.2,nusmv_timeout=None,nusmv_jobs_per_thread=1,bmc_k=None):
    if jobs_per_thread is None:
        jobs_per_thread = nusmv_jobs_per_thread
    job_allocation = []
    for i in range(len(all_jobs)//jobs_per_thread + len(all_jobs)%jobs_per_thread):
        cur_jobs = all_jobs[i*jobs_per_thread:i*jobs_per_thread+jobs_per_thread]
        job_allocation.append((dispatch_batch_MC,(cur_jobs,spot_timeout,nusmv_timeout,nusmv_jobs_per_thread,bmc_k,i)))
    results_per_job = run_in_parallel_preserve_order(job_allocation, max_workers=10)
    results = []
    for i in range(len(results_per_job)):
        results = []
        for i in range(len(results_per_job)):
            assert results_per_job[i] != "Timeout exceeded"
            results += results_per_job[i]
    return results

def subprocess_batch_spot_MC(job_list,job_fname="tmp_spot.json",timeout=None):
    with open(job_fname, "w") as f:
        json.dump(job_list, f)
    result = subprocess.run(["python", DATA_HOME_DIR+"/spot_model_checker.py", job_fname], capture_output=True, text=True,timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"spot_model_checker exited with {result.returncode}:\n{result.stderr}"
        )
    
    res_str = result.stdout.strip()
    return json.loads(res_str)

def to_smv_batch_job_list(job_list):
    total_var_dict = {}
    res_list = []
    for check_type, formulas in job_list:
        if len(formulas) == 2:
            f1, f2 = formulas
            total_var_dict.update(dict( (k,"boolean") for k in spot_utils.get_variables_from_formula(f1)))
            total_var_dict.update(dict( (k,"boolean") for k in spot_utils.get_variables_from_formula(f2)))
        elif len(formulas) == 1:
            f = formulas[0]
            total_var_dict.update(dict( (k,"boolean") for k in spot_utils.get_variables_from_formula(f)))
        else:
            assert False
        if check_type == "equivalence":
            res_list.append(f"({f1}) <-> ({f2})")
        elif check_type == "subset":
            res_list.append(f"!(({f1}) & !({f2}))")
        elif check_type == "superset":
            res_list.append(f"!(!({f1}) & ({f2}))")
        elif check_type == "overlap":
            res_list.append(f"!(({f1}) & ({f2}))")
        elif check_type == "satisfiable":
            assert False, "unimplemented"
            res_list.append(f"!({f})")
        else:
            assert False, "check type not found!"
    for i in range(len(res_list)):
        res_list[i] = spot_utils.filter_ltl_formula(res_list[i])
    return total_var_dict,res_list

def get_most_constrained_idx(ltl_list):
    aut_list = [spot.translate(ltl_list[i]) for i in range(len(ltl_list))]
    res_set = set([i for i in range(len(ltl_list))])
    for i in range(len(ltl_list)):
        for j in range(len(ltl_list)):
            if i != j and spot.contains(aut_list[i],aut_list[j]):
                res_set.remove(i)
                break

    #remove equivalent
    equiv_dict = {}
    for i,j in list(itertools.combinations(res_set,2)):
        if spot.are_equivalent(aut_list[i],aut_list[j]):
            if i not in equiv_dict:
                equiv_dict[i] = []
            equiv_dict[i].append(j)
            if j not in equiv_dict:
                equiv_dict[j] = []
            equiv_dict[j].append(i)
    items_to_delete = set()
    while len(equiv_dict) > 0:
        for key,val in equiv_dict.items():
            for e in val:
                items_to_delete.add(e)
                del equiv_dict[e]
            del equiv_dict[key]
            break
    return [idx for idx in res_set if idx not in items_to_delete]

def get_least_constrained_idx(ltl_list):
    aut_list = [spot.translate(ltl_list[i]) for i in range(len(ltl_list))]
    res_set = set([i for i in range(len(ltl_list))])
    for i in range(len(ltl_list)):
        for j in range(len(ltl_list)):
            if i != j and spot.contains(aut_list[j],aut_list[i]):
                res_set.remove(i)
                break

    #remove equivalent
    equiv_dict = {}
    for i,j in list(itertools.combinations(res_set,2)):
        if spot.are_equivalent(aut_list[i],aut_list[j]):
            if i not in equiv_dict:
                equiv_dict[i] = []
            equiv_dict[i].append(j)
            if j not in equiv_dict:
                equiv_dict[j] = []
            equiv_dict[j].append(i)
    items_to_delete = set()
    while len(equiv_dict) > 0:
        for key,val in equiv_dict.items():
            for e in val:
                items_to_delete.add(e)
                del equiv_dict[e]
            del equiv_dict[key]
            break
    return [idx for idx in res_set if idx not in items_to_delete]

def remove_equivalent_idx_old(ltl_list,timeout=None,mc_mode="spot",bmc_k=None,ret_equiv_dict=False):
    if mc_mode == "spot":
        aut_list = [spot.translate(ltl_list[i]) for i in range(len(ltl_list))]
    res_set = [i for i in range(len(ltl_list))]
    equiv_dict = {}
    visited = set()
    for i in tqdm(range(len(res_set))):
        if i not in visited:
            if mc_mode == "timeout":
                cur_jobs = []
                for j in range(i+1,len(res_set)):
                    cur_jobs.append(("equivalence",(ltl_list[i],ltl_list[j])))
                equiv_results = parallel_dispatch_batch_MC(cur_jobs,
                                         jobs_per_thread=25,
                                         spot_timeout=0.5,
                                         nusmv_timeout=timeout,
                                         nusmv_jobs_per_thread=10,
                                         bmc_k=bmc_k)
            elif mc_mode == "spot":
                equiv_results = []
                for j in range(i+1,len(res_set)):
                    equiv_results.append(spot.are_equivalent(aut_list[i],aut_list[j]))
            elif mc_mode == "nusmv":
                equiv_results = []
                for j in range(i+1,len(res_set)):
                    cur_var_dict = dict((var,"boolean") for var in spot_utils.get_variables_from_formula(ltl_list[i]))
                    cur_var_dict.update(dict((var,"boolean") for var in spot_utils.get_variables_from_formula(ltl_list[j])))
                    equiv_results.append(nusmv_utils.get_nusmv_ltl_equivalent(cur_var_dict,ltl_list[i],cur_var_dict,ltl_list[j],bmc_k=bmc_k))
            else:
                assert False
            for j in range(i+1,len(res_set)):
                if equiv_results[j-(i+1)]:
                    if i not in equiv_dict:
                        equiv_dict[i] = []
                    equiv_dict[i].append(j)
                    visited.add(j)
    ret_dict = dict((k,v.copy()) for k,v in equiv_dict.items())
    items_to_delete = set()
    while len(equiv_dict) > 0:
        for key,val in equiv_dict.items():
            for e in val:
                items_to_delete.add(e)
            del equiv_dict[key]
            break
    if not ret_equiv_dict:
        return [idx for idx in res_set if idx not in items_to_delete]
    else:
        return [idx for idx in res_set if idx not in items_to_delete],ret_dict

def determine_timeout_idx(ltl_list):
    timeout_idx = set()
    jobs_per_thread = 10
    for i in range(len(ltl_list)//jobs_per_thread + len(ltl_list)%jobs_per_thread):
        cur_jobs = [("translate",[entry]) for entry in ltl_list[i*jobs_per_thread:(i+1)*jobs_per_thread] ]
        try:
            subprocess_batch_spot_MC(cur_jobs,job_fname=SMV_FILE_DIR+f"/tmp{i}.smv",timeout=0.5)
        except subprocess.TimeoutExpired as e:
            timeout_idx.update(set([idx for idx in range(i*jobs_per_thread,min((i+1)*jobs_per_thread,len(ltl_list)),1)]))
    to_remove = set()
    for i in timeout_idx:
        cur_jobs = [("translate",[ltl_list[i]])]
        try:
            subprocess_batch_spot_MC(cur_jobs,job_fname=SMV_FILE_DIR+f"/tmp.smv",timeout=0.5)
            to_remove.add(i)
        except subprocess.TimeoutExpired as e:
            pass
    timeout_idx = timeout_idx - to_remove
    print("num timeout:",len(timeout_idx),flush=True)
    return timeout_idx
    
def get_aut_product(f_list,bmc_k=None):
    cur_aut = spot.translate(f_list[0])
    for f in f_list[1:]:
        cur_aut = spot.product(cur_aut,spot.translate(f)).postprocess()
        if bmc_k is not None:
            cur_aut = get_aut_num_steps(cur_aut,bmc_k)
    if bmc_k is None:
        return cur_aut
    else:
        return get_aut_num_steps(cur_aut,bmc_k)

import random
def remove_equivalent_idx(ltl_list,aut_list=None,mc_mode="spot",ret_equiv_dict=False,bmc_k=None,
                         nusmv_jobs_per_thread=100,constraint_f_list=None):
    if mc_mode == "spot":
        timeout_idx = set()
        if aut_list is None:
            aut_list = [spot.translate(ltl_list[i]) for i in range(len(ltl_list))]
        if constraint_f_list is None:
            constraint_aut = spot.translate("1")
        else:
            constraint_aut = get_aut_product(constraint_f_list,bmc_k=bmc_k)
        obj_list = aut_list
        #tmp_check_equiv_func = lambda i,j,obj_list : spot.are_equivalent(obj_list[i],obj_list[j])
        def tmp_check_equiv_func(i,j,obj_list):
            return spot.product(constraint_aut,spot.product(aut_list[i],spot.complement(aut_list[j]))).accepting_run() is None \
                and spot.product(constraint_aut,spot.product(spot.complement(aut_list[i]),aut_list[j])).accepting_run() is None
        tmp_get_trace = lambda i,obj_list : str(obj_list[i].accepting_word())
    elif mc_mode == "nusmv":
        timeout_idx = set()
        #obj_list = ltl_list
        if constraint_f_list is not None and len(constraint_f_list) > 0:
            obj_list = [f"({' & '.join(constraint_f_list)}) & ({entry})" for entry in ltl_list]
        else:
            obj_list = ltl_list
        def tmp_check_equiv_func(i,j,obj_list):
            cur_var_dict = dict((var,"boolean") for var in spot_utils.get_variables_from_formula(obj_list[i]))
            cur_var_dict.update(dict((var,"boolean") for var in spot_utils.get_variables_from_formula(obj_list[j])))
            return nusmv_utils.get_nusmv_ltl_equivalent(cur_var_dict,obj_list[i],cur_var_dict,obj_list[j],bmc_k=bmc_k)
        def tmp_get_trace(i,obj_list):
            cur_var_dict = dict((var,"boolean") for var in spot_utils.get_variables_from_formula(obj_list[i]))
            return str(nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,obj_list[i],bmc_k=10))
    elif mc_mode == "timeout":
        #obj_list = ltl_list
        if constraint_f_list is not None and len(constraint_f_list) > 0:
            obj_list = [f"({' & '.join(constraint_f_list)}) & ({entry})" for entry in ltl_list]
        else:
            obj_list = ltl_list
        print("in remove equivelent calling determine timeout!")
        timeout_idx = determine_timeout_idx(ltl_list)
        if len(timeout_idx) > 0:
            raise
        aut_list = [spot.translate(ltl_list[i]) if i not in timeout_idx else None for i in range(len(ltl_list))]
        if constraint_f_list is None:
            constraint_aut = spot.translate("1")
        else:
            constraint_aut = get_aut_product(constraint_f_list,bmc_k=bmc_k)
        assert len(aut_list) == len(ltl_list)
        def tmp_check_equiv_func(i,j,obj_list):
            if i in timeout_idx or j in timeout_idx:
                cur_var_dict = dict((var,"boolean") for var in spot_utils.get_variables_from_formula(obj_list[i]))
                cur_var_dict.update(dict((var,"boolean") for var in spot_utils.get_variables_from_formula(obj_list[j])))
                return nusmv_utils.get_nusmv_ltl_equivalent(cur_var_dict,obj_list[i],cur_var_dict,obj_list[j],bmc_k=bmc_k)
            else:
                #return spot.are_equivalent(aut_list[i],aut_list[j])
                #print(spot.product(aut_list[i],spot.complement(aut_list[j])).num_states())
                #return aut_list[i].contains(aut_list[j]) and aut_list[j].contains(aut_list[i])
                return spot.product(constraint_aut,spot.product(aut_list[i],spot.complement(aut_list[j]))).accepting_run() is None \
                    and spot.product(constraint_aut,spot.product(spot.complement(aut_list[i]),aut_list[j])).accepting_run() is None
        def tmp_get_trace(i,obj_list):
            if i in timeout_idx:
                cur_var_dict = dict((var,"boolean") for var in spot_utils.get_variables_from_formula(obj_list[i]))
                return str(nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,obj_list[i],bmc_k=10))
            else:
                return str(aut_list[i].accepting_word())
    else:
        assert False
        
    word_dict = {}
    for i in tqdm(range(len(ltl_list))):
        cur_hash = tmp_get_trace(i,obj_list)
        if cur_hash not in word_dict:
            word_dict[cur_hash] = []
        word_dict[cur_hash].append(i)
    
    equiv_dict = {}
    visited = set()
    for idx_list in tqdm(word_dict.values()):
        for cur_index in range(len(idx_list)):
            i = idx_list[cur_index]
            if i not in visited and i not in timeout_idx:
                for j in idx_list[cur_index+1:]:
                    if j not in timeout_idx and tmp_check_equiv_func(i,j,obj_list):
                        if i not in equiv_dict:
                            equiv_dict[i] = []
                        if j in equiv_dict:
                            equiv_dict[i] += equiv_dict[j]
                            del equiv_dict[j]
                        equiv_dict[i].append(j)
                        visited.add(j)
            elif i not in visited and i in timeout_idx:
                cur_jobs = []
                for j in idx_list:
                    cur_jobs.append(("equivalence",(ltl_list[i],ltl_list[j])))
                #equiv_results = subprocess_batch_spot_MC(cur_jobs)
                #equiv_results = dispatch_batch_MC(cur_jobs,spot_timeout=0,nusmv_jobs_per_thread=nusmv_jobs_per_thread,bmc_k=bmc_k)
                equiv_results = parallel_dispatch_batch_MC(cur_jobs,jobs_per_thread=nusmv_jobs_per_thread,spot_timeout=0.5,nusmv_jobs_per_thread=nusmv_jobs_per_thread,bmc_k=bmc_k)
                for res_idx in range(len(equiv_results)):
                    j = idx_list[res_idx]
                    if i < j and equiv_results[res_idx]:
                        if i not in equiv_dict:
                            equiv_dict[i] = []
                        if j in equiv_dict:
                            equiv_dict[i] += equiv_dict[j]
                            del equiv_dict[j]
                        equiv_dict[i].append(j)
                        visited.add(j)
                    elif i > j and equiv_results[res_idx]:
                        if j not in equiv_dict:
                            equiv_dict[j] = []
                        if i in equiv_dict:
                            equiv_dict[j] += equiv_dict[i]
                            del equiv_dict[i]
                        equiv_dict[j].append(i)
                        visited.add(i)
                        
    items_to_delete = set()
    for key,val in equiv_dict.items():
        for e in val:
            items_to_delete.add(e)
    for key in equiv_dict:
        for val in equiv_dict.values():
            assert key not in val
    checked_set = set([e for idx_list in word_dict.values() for e in itertools.product(idx_list,idx_list)])
    new_idx_list = [idx for idx in range(len(ltl_list)) if idx not in items_to_delete]
    
    for cur_index in tqdm(range(len(new_idx_list))):
        i = new_idx_list[cur_index]
        if i not in visited and i not in timeout_idx:
            cur_idx_list = [entry for entry in new_idx_list[cur_index+1:] if (i,entry) not in checked_set]
            #for j in new_idx_list[cur_index+1:]:
            for j in cur_idx_list:
                if j not in timeout_idx and tmp_check_equiv_func(i,j,obj_list):
                    if i not in equiv_dict:
                        equiv_dict[i] = []
                    if j in equiv_dict:
                        equiv_dict[i] += equiv_dict[j]
                        del equiv_dict[j]
                    equiv_dict[i].append(j)
                    visited.add(j)
        elif i not in visited and i in timeout_idx:
            cur_idx_list = [entry for entry in new_idx_list if (i,entry) not in checked_set]
            cur_jobs = []
            #for j in new_idx_list:
            for j in cur_idx_list:
                cur_jobs.append(("equivalence",(ltl_list[i],ltl_list[j])))
            #equiv_results = subprocess_batch_spot_MC(cur_jobs)
            #equiv_results = dispatch_batch_MC(cur_jobs,spot_timeout=0,nusmv_jobs_per_thread=nusmv_jobs_per_thread,bmc_k=bmc_k)
            equiv_results = parallel_dispatch_batch_MC(cur_jobs,jobs_per_thread=nusmv_jobs_per_thread,spot_timeout=0.5,nusmv_jobs_per_thread=nusmv_jobs_per_thread,bmc_k=bmc_k)
            for res_idx in range(len(equiv_results)):
                #j = new_idx_list[res_idx]
                j = cur_idx_list[res_idx]
                if i < j and equiv_results[res_idx] and i not in visited:
                    if i not in equiv_dict:
                        equiv_dict[i] = []
                    if j in equiv_dict:
                        equiv_dict[i] += equiv_dict[j]
                        del equiv_dict[j]
                    equiv_dict[i].append(j)
                    visited.add(j)
                elif i > j and equiv_results[res_idx] and j not in visited:
                    if j not in equiv_dict:
                        equiv_dict[j] = []
                    if i in equiv_dict:
                        equiv_dict[j] += equiv_dict[i]
                        del equiv_dict[i]
                    equiv_dict[j].append(i)
                    visited.add(i)
                    
    for key,val in equiv_dict.items():
        for e in val:
            items_to_delete.add(e)
    for key in equiv_dict:
        for val in equiv_dict.values():
            assert key not in val

    new_idx_list = [idx for idx in range(len(ltl_list)) if idx not in items_to_delete]
    if not ret_equiv_dict:
        return new_idx_list
    else:
        return new_idx_list,equiv_dict
