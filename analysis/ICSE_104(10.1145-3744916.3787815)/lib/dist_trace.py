from collections.abc import Iterable
from nl2structnl import *
from batch_check import *
from automaton_utils import *
import spot_utils
import numpy as np
import time
import nusmv_utils
import os

DATA_HOME_DIR = os.getenv("DATA_HOME_DIR")

min_group_size = 10

def get_maxmin_elim_mask(total_var_dict,all_f_list,mc_mode="nusmv",bmc_k=None,aut_cache=None,constraint_f_list=None):
    global min_group_size
    print("getting trace",len(all_f_list))
    #mask,trace = get_maxmin_elim_mask_spot(all_f_list,bmc_k=bmc_k,aut_cache=aut_cache)
    if min_group_size is not None:
        cur_min_group_size = min_group_size
    else:
        cur_min_group_size = len(all_f_list)
    mask,trace = get_maxmin_elim_mask_po(all_f_list,aut_cache=aut_cache,bmc_k=bmc_k,mc_mode=mc_mode,constraint_f_list=constraint_f_list,min_group_size=cur_min_group_size)
    if trace is None:
        return mask, trace
    else:
        #if mc_mode == "timeout" and not isinstance(trace,tuple):
        #    assert trace.accepting_run() is not None
        #    cur_f = spot_utils.trace_to_formula(trace,debug=False)
        #    assert spot.translate(cur_f).accepting_run() is not None
        #    cur_var_dict = dict((var,"boolean") for var in spot_utils.get_variables_from_formula(cur_f))
        #    trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula(cur_f),bmc_k=bmc_k,use_trace=True)
        #    mask = get_mask_from_trace(all_f_list,trace,mc_mode="nusmv",bmc_k=bmc_k,aut_cache=aut_cache)
        #    assert trace is not None, cur_f        
        print("finish getting trace",min(sum([entry for entry in mask if entry is not None]),len(mask)-sum([entry for entry in mask if entry is not None]))/len(mask))
        print(mask)
        return mask, trace

def is_list_nested(lst):
    return bool(lst) and isinstance(lst[0], Iterable) and not isinstance(lst[0], (str, bytes))

def flatten_list(lst):
    if is_list_nested(lst):
        return list(itertools.chain.from_iterable(lst))
    else:
        return lst

class AutomatonCache:
    def __init__(self):
        self.cache = {}
        self.timeout_cache = {}
        self.scratch_pad = {}

    def hash(self,f_list):
        return frozenset(flatten_list(f_list))

    def get_aut(self,f_list,bmc_k=None):
        cur_hash = self.hash(f_list)
        if cur_hash not in self.cache and len(f_list) == 1:
            tmp = spot.translate(f_list[0])
            self.cache[cur_hash] = tmp.postprocess('det')
            if bmc_k is not None:
                self.cache[cur_hash] = get_aut_num_steps(self.cache[cur_hash],max_steps=bmc_k).postprocess('det')
        elif cur_hash not in self.cache and len(f_list) > 1:
            new_aut = self.get_aut([f_list[0]],bmc_k=bmc_k)
            for f in f_list[1:]:
                new_aut = spot.product(new_aut,self.get_aut([f],bmc_k=bmc_k)).postprocess('det')
            self.cache[cur_hash] = new_aut
            if bmc_k is not None:
                self.cache[cur_hash] = get_aut_num_steps(self.cache[cur_hash],max_steps=bmc_k).postprocess('det')
        return self.cache[cur_hash]

    def get_timeout_idx(self,ltl_list):
        recompute = False
        for i in range(len(ltl_list)):
            if ltl_list[i] not in self.timeout_cache:
                recompute = True
                break
        if recompute:
            timeout_idx = determine_timeout_idx(ltl_list)
            for i in range(len(ltl_list)):
                self.timeout_cache[ltl_list[i]] = i in timeout_idx
            return timeout_idx
        else:
            timeout_idx = set([i for i in range(len(ltl_list)) if self.timeout_cache[ltl_list[i]]])
            return timeout_idx
            
def get_aut_list_for_f(cur_f_list,bmc_k=None,aut_cache=None,is_verbose=False,check_timeout=False):
    if aut_cache is None:
        aut_cache = AutomatonCache()
    pos_aut_list = []
    neg_aut_list = []
    pos_f_list = []
    neg_f_list = []
    for i in range(len(cur_f_list)):
        pos_f_list.append(get_hold_formula(cur_f_list[i]))
        neg_f_list.append(get_nothold_formula(cur_f_list[i]))
    if check_timeout:
        timeout_idx = aut_cache.get_timeout_idx(pos_f_list)
        timeout_idx = timeout_idx.union(aut_cache.get_timeout_idx(neg_f_list))
    else:
        timeout_idx = set()
    for i in tqdm(range(len(cur_f_list)),disable=not is_verbose):
        if i not in timeout_idx:
            pos_aut_list.append(aut_cache.get_aut([get_hold_formula(cur_f_list[i])],bmc_k=bmc_k))
            neg_aut_list.append(aut_cache.get_aut([get_nothold_formula(cur_f_list[i])],bmc_k=bmc_k))
        else:
            pos_aut_list.append(None)
            neg_aut_list.append(None)
    return pos_f_list, neg_f_list, pos_aut_list, neg_aut_list, timeout_idx

def get_po_of_aut_list(ltl_list,aut_list=None,bmc_k=None,mc_mode="spot",timeout_idx=None,aut_cache=None,constraint_f_list=None):    
    po_hash = tuple((tuple(ltl_list),bmc_k))
    print(mc_mode,bmc_k)
    if po_hash in aut_cache.scratch_pad:
        print("found cached po!")
        return aut_cache.scratch_pad[po_hash]
    if mc_mode == "spot":
        assert aut_list is not None, "specifying aut_list is required when using mc_mode = spot or timeout"
        if constraint_f_list is not None and len(constraint_f_list) > 0:
            constraint_aut = get_aut_product(constraint_f_list,bmc_k=bmc_k)
            #aut_list = [spot.product(constraint_aut,entry).postprocess() if entry is not None else None for entry in aut_list]
            aut_list = [get_aut_num_steps(spot.product(constraint_aut,entry).postprocess(),bmc_k) if entry is not None else None for entry in aut_list]
            ltl_list = [f"({' & '.join(constraint_f_list)}) & ({entry})" for entry in ltl_list]
    elif mc_mode == "timeout":
        assert aut_list is not None, "specifying aut_list is required when using mc_mode = spot or timeout"
        if constraint_f_list is not None and len(constraint_f_list) > 0:
            #constraint_aut = get_aut_product(constraint_f_list,bmc_k=bmc_k)
            #aut_list = [get_aut_num_steps(spot.product(constraint_aut,entry).postprocess(),bmc_k) if entry is not None else None for entry in aut_list]
            ltl_list = [f"({' & '.join(constraint_f_list)}) & ({entry})" for entry in ltl_list]
    if timeout_idx is None:
        timeout_idx = set()
    key_subset_of_val = {}
    key_superset_of_val = {}
    key_mutex_of_val = {}
    for i in tqdm(range(len(ltl_list))):
        key_subset_of_val[i] = set()
        key_mutex_of_val[i] = set()
        if i not in key_superset_of_val:
            key_superset_of_val[i] = set()
        tmp_subset_check = {}
        tmp_mutex_check = {}
        if mc_mode == "spot":
            for j in range(len(ltl_list)):
                if i != j:
                    tmp_subset_check[j] = aut_list[j].contains(aut_list[i])
                    tmp_mutex_check[j] = spot.product(aut_list[j],aut_list[i]).accepting_run() is None
        elif mc_mode == "nusmv":
            cur_jobs = []
            for j in range(len(ltl_list)):
                if i != j:
                    cur_jobs.append(("subset",(ltl_list[i],ltl_list[j])))
                    cur_jobs.append(("overlap",(ltl_list[i],ltl_list[j])))
            #res = subprocess_batch_nusmv_MC(cur_jobs,bmc_k=bmc_k,timeout=None)
            res = dispatch_batch_MC(cur_jobs,
                                         spot_timeout=0,
                                         nusmv_timeout=None,
                                         nusmv_jobs_per_thread=1000,
                                         bmc_k=bmc_k)
            res_idx = 0
            for j in range(len(ltl_list)):
                if i != j:
                    tmp_subset_check[j] = res[res_idx]
                    res_idx += 1
                    tmp_mutex_check[j] = not res[res_idx]
                    res_idx += 1
        elif mc_mode == "timeout":
            """
            cur_jobs = []
            for j in range(len(ltl_list)):
                if i != j:
                    if i not in timeout_idx and j not in timeout_idx:
                        tmp_subset_check[j] = aut_list[j].contains(aut_list[i])
                        tmp_mutex_check[j] = spot.product(aut_list[j],aut_list[i]).accepting_run() is None
                    else:
                        cur_jobs.append(("subset",(ltl_list[i],ltl_list[j])))
                        cur_jobs.append(("overlap",(ltl_list[i],ltl_list[j])))
            res = dispatch_batch_MC(cur_jobs,
                                         spot_timeout=0,
                                         nusmv_timeout=None,
                                         nusmv_jobs_per_thread=1000,
                                         bmc_k=bmc_k)
            res_idx = 0
            for j in range(len(ltl_list)):
                if i != j:
                    if i not in timeout_idx and j not in timeout_idx:
                        assert j in tmp_subset_check
                        assert j in tmp_mutex_check
                    else:
                        tmp_subset_check[j] = res[res_idx]
                        res_idx += 1
                        tmp_mutex_check[j] = not res[res_idx]
                        res_idx += 1
            """
            cur_jobs = []
            for j in range(len(ltl_list)):
                if i != j:
                    cur_jobs.append(("subset",(ltl_list[i],ltl_list[j])))
                    cur_jobs.append(("overlap",(ltl_list[i],ltl_list[j])))
            #res = dispatch_batch_MC(cur_jobs,
            #                             spot_timeout=1,
            #                             nusmv_timeout=None,
            #                             nusmv_jobs_per_thread=1000,
            #                             bmc_k=bmc_k)
            res = parallel_dispatch_batch_MC(cur_jobs,
                                         jobs_per_thread=25,
                                         spot_timeout=0.5,
                                         nusmv_timeout=1,
                                         nusmv_jobs_per_thread=10,
                                         bmc_k=bmc_k)
            res_idx = 0
            for j in range(len(ltl_list)):
                if i != j:
                    tmp_subset_check[j] = res[res_idx]
                    res_idx += 1
                    tmp_mutex_check[j] = not res[res_idx]
                    res_idx += 1
        else:
            assert False
        for j in range(len(ltl_list)):
            if i != j and tmp_subset_check[j]: #aut_list[j].contains(aut_list[i]):
                key_subset_of_val[i].add(j)
                if j not in key_superset_of_val:
                    key_superset_of_val[j] = set()
                key_superset_of_val[j].add(i)
            if i != j and tmp_mutex_check[j]: #spot.product(aut_list[j],aut_list[i]).accepting_run() is None:
                key_mutex_of_val[i].add(j)
    aut_cache.scratch_pad[po_hash] = key_subset_of_val, key_superset_of_val, key_mutex_of_val
    return key_subset_of_val, key_superset_of_val, key_mutex_of_val


def get_po_for_aut(cur_aut,cur_f,all_ltl_list,all_aut_list,
                   key_subset_of_val,key_superset_of_val,key_mutex_of_val,decided_idx_set,cur_all_idx=None,
                   bmc_k=None,timeout_idx=None,cur_check_idx=None,mc_mode="spot"):
    global total_time
    if cur_all_idx is None:
        cur_all_idx = set([i for i in range(len(all_aut_list))])
    rem_idx_set = cur_all_idx - decided_idx_set
    new_pos = set()
    new_neg = set()
    #start_t = time.time()
    if mc_mode == "spot":
        """
        for i in rem_idx_set:
            if spot.product(all_aut_list[i],cur_aut).accepting_run() is None:
                new_neg.add(i)
            elif all_aut_list[i].contains(cur_aut):
                new_pos.add(i)
        """
        while rem_idx_set:
            i = rem_idx_set.pop()
            if spot.product(all_aut_list[i],cur_aut).accepting_run() is None:
                tmp_new_neg = set([i]).union(key_superset_of_val[i])
                rem_idx_set = rem_idx_set - tmp_new_neg
                new_neg.update(tmp_new_neg)
            elif all_aut_list[i].contains(cur_aut):
                tmp_new_pos = set([i]).union(key_subset_of_val[i])
                tmp_new_neg = key_mutex_of_val[i]
                rem_idx_set = rem_idx_set - tmp_new_pos
                rem_idx_set = rem_idx_set - tmp_new_neg
                new_pos.update(tmp_new_pos)
                new_neg.update(tmp_new_neg)
    elif mc_mode == "nusmv" or (mc_mode == "timeout" and cur_check_idx.intersection(timeout_idx)):
        cur_jobs = []
        for i in rem_idx_set:
            cur_jobs.append(("overlap",(" & ".join(cur_f),all_ltl_list[i])))
            cur_jobs.append(("subset",(" & ".join(cur_f),all_ltl_list[i])))
        res = dispatch_batch_MC(cur_jobs,
                                 spot_timeout=0,
                                 nusmv_timeout=None,
                                 nusmv_jobs_per_thread=100,
                                 bmc_k=bmc_k)
        res_idx = 0
        for i in rem_idx_set:
            if not res[res_idx]:
                new_neg.add(i)
            res_idx += 1
            if res[res_idx]:
                new_pos.add(i)
            res_idx += 1
    elif mc_mode == "timeout":
        cur_jobs = []
        for i in rem_idx_set:
            if i not in timeout_idx:
                if spot.product(all_aut_list[i],cur_aut).accepting_run() is None:
                    new_neg.add(i)
                elif all_aut_list[i].contains(cur_aut):
                    new_pos.add(i)
            else:
                cur_jobs.append(("overlap",(" & ".join(cur_f),all_ltl_list[i])))
                cur_jobs.append(("subset",(" & ".join(cur_f),all_ltl_list[i])))
        res = dispatch_batch_MC(cur_jobs,
                         spot_timeout=0,
                         nusmv_timeout=None,
                         nusmv_jobs_per_thread=100,
                         bmc_k=bmc_k)
        res_idx = 0
        for i in rem_idx_set:
            if i in timeout_idx:
                if not res[res_idx]:
                    new_neg.add(i)
                res_idx += 1
                if res[res_idx]:
                    new_pos.add(i)
                res_idx += 1
    else:
        assert False, f"mc_mode '{mc_mode}' not recognized"
    #total_time += time.time() - start_t
    return new_pos, new_neg

def get_covering_relation_tree(key_subset_of_val):
    new_key_subset_of_val = dict((k,v.copy()) for k,v in key_subset_of_val.items())
    for key in key_subset_of_val.keys():
        to_remove = set()
        for entry in key_subset_of_val[key]:
            for dup_key in key_subset_of_val[entry]:
                to_remove.add(dup_key)
        assert key not in to_remove
        new_key_subset_of_val[key] = key_subset_of_val[key] - to_remove
    return new_key_subset_of_val

def get_roots(key_subset_of_val):
    roots = set([entry for entry in key_subset_of_val])
    for key in key_subset_of_val.keys():
        roots = roots - key_subset_of_val[key]
    return roots

def get_longest_seq(key_subset_of_val):
    roots = get_roots(key_subset_of_val)
    workset = [[entry] for entry in roots]
    longest_seq = []
    while workset:
        node_seq = workset.pop()
        if len(node_seq) > len(longest_seq):
            longest_seq = node_seq            
        for next_node_id in key_subset_of_val[node_seq[-1]]:
            assert next_node_id not in node_seq
            workset.append(node_seq + [next_node_id])
    return longest_seq

def find_equiv_pair_in_po(key_subset_of_val):
    for key in key_subset_of_val.keys():
        for entry in key_subset_of_val[key]:
            if key in key_subset_of_val[entry]:    
                return (key,entry)
    return None
    
def remove_equivelent_from_po(key_subset_of_val):
    cur_key_subset_of_val = dict((k,v.copy()) for k,v in key_subset_of_val.items())
    pair = find_equiv_pair_in_po(cur_key_subset_of_val)
    while pair is not None:
        key1, key2 = pair
        for key in cur_key_subset_of_val:
            cur_key_subset_of_val[key].discard(key2)
        del cur_key_subset_of_val[key2]
        pair = find_equiv_pair_in_po(cur_key_subset_of_val)
    return cur_key_subset_of_val
                
def get_sliced_branches(key_subset_of_val):
    res_list = []
    #cur_key_subset_of_val = dict((k,v.copy()) for k,v in key_subset_of_val.items())
    cur_key_subset_of_val = remove_equivelent_from_po(key_subset_of_val)
    cur_key_subset_of_val = get_covering_relation_tree(cur_key_subset_of_val)
    while len(cur_key_subset_of_val) > 0:
        new_seq = get_longest_seq(cur_key_subset_of_val)
        assert len(new_seq) > 0
        res_list.append(new_seq)
        for entry in new_seq:
            for key in cur_key_subset_of_val:
                cur_key_subset_of_val[key].discard(entry)
            del cur_key_subset_of_val[entry]
    return res_list

def get_sat_aut_list(check_f_list,check_aut_list,init_aut,init_f,bmc_k,mc_mode):
    cur_f = init_f + check_f_list
    if mc_mode == "spot":
        found_unsat = False
        cur_aut = spot.product(spot.translate("1"),init_aut)
        for i in range(len(check_aut_list)):
            cur_aut = spot.product(cur_aut,check_aut_list[i])
            if bmc_k is not None:
                cur_aut = get_aut_num_steps(cur_aut,max_steps=bmc_k).postprocess('det')
            if cur_aut.accepting_run() is None:
                return cur_aut, cur_f
        return cur_aut, cur_f
    elif mc_mode == "nusmv":
        cur_var_dict = dict( (k,"boolean") for f in cur_f for k in spot_utils.get_variables_from_formula(f))
        trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula(" & ".join(cur_f)),bmc_k=bmc_k,use_trace=False)
        return trace, cur_f

def get_maxmin_elim_mask_po_helper(all_ltl_list,slice_idx_list,key_subset_of_val,key_superset_of_val,key_mutex_of_val,
                                   prev_pos=None,prev_neg=None,
                                   init_aut=None,init_f=None,aut_cache=None,
                                   bmc_k=None,goal=None,cur_all_idx=None,prev_check_idx=None,
                                   mc_mode="spot"):
    global total_count
    global total_time
    if init_aut is None:
        init_aut = spot.translate("1")
    if init_f is None:
        init_f = []
    if prev_pos is None:
        prev_pos = set()
    if prev_neg is None:
        prev_neg = set()
    if goal is None:
        goal = len(all_ltl_list) // 2
    if cur_all_idx is None:
        cur_all_idx = set([i for i in range(len(all_ltl_list))])
    if prev_check_idx is None:
        prev_check_idx = set()
    cur_group = slice_idx_list[0]
    rev_group = cur_group[::-1]
    #cur_f_list = [all_ltl_list[idx] for idx in cur_group]
    if mc_mode != "nusmv":
        all_pos_f_list, all_neg_f_list, all_pos_aut_list, all_neg_aut_list, timeout_idx = get_aut_list_for_f(all_ltl_list,bmc_k=bmc_k,aut_cache=aut_cache,
                                                                                                            check_timeout= mc_mode=="timeout")
        #pos_f_list, neg_f_list, pos_aut_list, neg_aut_list, timeout_idx = get_aut_list_for_f(cur_f_list,bmc_k=bmc_k,aut_cache=aut_cache)
        #for i in range(len(cur_f_list)-1):
        #    assert pos_aut_list[i+1].contains(pos_aut_list[i])
        #    assert neg_aut_list[i].contains(neg_aut_list[i+1])
    else:
        all_pos_f_list = [get_hold_formula(entry) for entry in all_ltl_list]
        all_neg_f_list = [get_nothold_formula(entry) for entry in all_ltl_list]
        all_pos_aut_list = [None for entry in all_ltl_list]
        all_neg_aut_list = [None for entry in all_ltl_list]
        timeout_idx = set()
    total_prev_pos_set = prev_pos.copy()

    #get min num pos
    min_num_pos = 0
    for i in range(len(cur_group)):
        if cur_group[i] in total_prev_pos_set:
            min_num_pos = len(cur_group) - i
            break

    total_prev_neg_set = prev_neg.copy()

    #get max num pos
    max_num_pos = len(cur_group)
    for i in range(len(cur_group)):
        if cur_group[i] in total_prev_neg_set:
            max_num_pos = (len(cur_group) - 1) - i
    
    for num_pos in range(min_num_pos,max_num_pos+1):
        cur_total_prev_neg_set = total_prev_neg_set.copy()
        cur_total_prev_pos_set = total_prev_pos_set.copy()
        
        #handle new positives
        for entry in rev_group[:num_pos]:
            cur_total_prev_pos_set.add(entry)
            cur_total_prev_pos_set.update(key_subset_of_val[entry].intersection(cur_all_idx))
            cur_total_prev_neg_set.update(key_mutex_of_val[entry].intersection(cur_all_idx))
        
        #handle new negatives
        for entry in rev_group[num_pos:]:
            cur_total_prev_neg_set.add(entry)
            cur_total_prev_neg_set.update(key_superset_of_val[entry].intersection(cur_all_idx))
        
        rem_count = len(cur_all_idx) - len(cur_total_prev_pos_set.union(cur_total_prev_neg_set))
        if (rem_count >= goal - len(cur_total_prev_pos_set) and goal - len(cur_total_prev_pos_set) >= 0) or \
            (rem_count >= goal - len(cur_total_prev_neg_set) and goal - len(cur_total_prev_neg_set) >= 0): 
            total_count += 1
            #mask = [False if i < len(cur_group) - num_pos else True for i in range(len(cur_group))]
            #check_aut_list = [pos_aut_list[i].postprocess('det') if mask[i] else neg_aut_list[i].postprocess('det') for i in range(len(cur_group))]

            if num_pos == 0:
                check_pos_list_idx = []
                #check_neg_list_idx = [len(cur_group)-1] #tmp change to below
                check_neg_list_idx = [cur_group[len(cur_group)-1]]
            elif num_pos == len(cur_group):
                #check_pos_list_idx = [0] #tmp change to below
                check_pos_list_idx = [cur_group[0]]
                check_neg_list_idx = []
            else:
                #check_pos_list_idx = [len(cur_group) - num_pos] #tmp change to below
                check_pos_list_idx = [cur_group[len(cur_group) - num_pos]]
                #check_neg_list_idx = [len(cur_group)- num_pos - 1] #tmp change to below
                check_neg_list_idx = [cur_group[len(cur_group)- num_pos - 1]]

            #only call model checker if cur_group is not already included
            cur_pos_set = set(rev_group[:num_pos])
            cur_neg_set = set(rev_group[num_pos:])
            if len(total_prev_pos_set.intersection(cur_pos_set)) == len(cur_pos_set) \
                and len(total_prev_neg_set.intersection(cur_neg_set)) == len(cur_neg_set):
                cur_check_idx = prev_check_idx.copy()
                cur_aut = init_aut
                cur_f = init_f
                found_unsat = False
            else:
                #check_aut_list = [neg_aut_list[i] for i in check_neg_list_idx] + [pos_aut_list[i] for i in check_pos_list_idx]  #tmp change to below
                check_f_list = [all_neg_f_list[i] for i in check_neg_list_idx] + [all_pos_f_list[i] for i in check_pos_list_idx]
                check_aut_list = [all_neg_aut_list[i] for i in check_neg_list_idx] + [all_pos_aut_list[i] for i in check_pos_list_idx]
                cur_check_idx = prev_check_idx.copy()
                cur_check_idx.update(check_pos_list_idx)
                cur_check_idx.update(check_neg_list_idx)
                if mc_mode == "timeout":
                    if timeout_idx.intersection(cur_check_idx) or isinstance(init_aut,tuple):
                        check_mc_mode = "nusmv"
                    else:
                        check_mc_mode = "spot"
                else:
                    check_mc_mode = mc_mode
                start_t = time.time()
                cur_aut,cur_f = get_sat_aut_list(check_f_list,check_aut_list=check_aut_list,init_aut=init_aut,init_f=init_f,bmc_k=bmc_k,mc_mode=check_mc_mode)
                total_time += time.time() - start_t
                if check_mc_mode == "spot":
                    found_unsat = cur_aut.accepting_run() is None
                else:
                    found_unsat = cur_aut is None
            
            
            if not found_unsat:
                if len(slice_idx_list) > 1:
                    #identify new implications of cur_aut
                    new_pos,new_neg = get_po_for_aut(cur_aut,cur_f,all_pos_f_list,all_pos_aut_list,
                                                     key_subset_of_val,key_superset_of_val,key_mutex_of_val,
                                                     cur_total_prev_pos_set.union(cur_total_prev_neg_set),
                                                     cur_all_idx=cur_all_idx,
                                                     bmc_k=bmc_k,
                                                     timeout_idx=timeout_idx,cur_check_idx=cur_check_idx,
                                                     mc_mode=mc_mode)
                    cur_total_prev_pos_set.update(new_pos.intersection(cur_all_idx))
                    cur_total_prev_neg_set.update(new_neg.intersection(cur_all_idx))
                    rem_count = len(cur_all_idx) - len(cur_total_prev_pos_set.union(cur_total_prev_neg_set))
                    if (rem_count >= goal - len(cur_total_prev_pos_set) and goal - len(cur_total_prev_pos_set) >= 0) or \
                        (rem_count >= goal - len(cur_total_prev_neg_set) and goal - len(cur_total_prev_neg_set) >= 0):
                        res_trace, res_f,  cur_total_prev_pos_set, cur_total_prev_neg_set = get_maxmin_elim_mask_po_helper(all_ltl_list,slice_idx_list[1:],
                                                      key_subset_of_val,key_superset_of_val,key_mutex_of_val,
                                                      prev_pos = cur_total_prev_pos_set,
                                                      prev_neg = cur_total_prev_neg_set,
                                                      init_aut=cur_aut,init_f=cur_f,
                                                      aut_cache=aut_cache,bmc_k=bmc_k,
                                                      goal=goal,cur_all_idx=cur_all_idx,
                                                      prev_check_idx=cur_check_idx,
                                                      mc_mode=mc_mode)
                        if res_trace is not None:
                            return res_trace, res_f,  cur_total_prev_pos_set, cur_total_prev_neg_set #TODO new
                else:
                    return cur_aut, cur_f,  cur_total_prev_pos_set, cur_total_prev_neg_set #TODO new
    return (None,None, None,None) #TODO new
    
def partition_slice_by_size(all_slice_list,min_group_size):
    assert min_group_size >= 2
    slice_part = []
    cur_slice_list = []
    cur_slice_size = 0
    for group in all_slice_list:
        if cur_slice_size < min_group_size:
            cur_slice_list.append(group)
            cur_slice_size += len(group)
        else:
            slice_part.append(cur_slice_list)
            cur_slice_list = [group]
            cur_slice_size = len(group)
    if len(cur_slice_list) > 0:
        slice_part.append(cur_slice_list)
    return slice_part

def get_maxmin_elim_mask_po(all_ltl_list,aut_cache=None,bmc_k=None,mc_mode="spot",constraint_f_list=None,min_group_size=10):
    global total_count
    global total_time
    total_count = 0
    total_time = 0
    if aut_cache is None:
        aut_cache = AutomatonCache()
    if mc_mode != "nusmv":
        pos_f_list, neg_f_list, pos_aut_list, neg_aut_list,timeout_idx = get_aut_list_for_f(all_ltl_list,bmc_k=bmc_k,aut_cache=aut_cache,
                                                                                            check_timeout= mc_mode=="timeout")
    else:
        pos_f_list = [get_hold_formula(f) for f in all_ltl_list]
        neg_f_list = [get_nothold_formula(f) for f in all_ltl_list]
        pos_aut_list = [None for f in all_ltl_list]
        neg_aut_list = [None for f in all_ltl_list]
        timeout_idx = set()
    print("getting po!")
    key_subset_of_val,key_superset_of_val,key_mutex_of_val = get_po_of_aut_list(pos_f_list,aut_list=pos_aut_list,
                                                                mc_mode=mc_mode,bmc_k=bmc_k,timeout_idx=timeout_idx,aut_cache=aut_cache,
                                                                #constraint_f_list=constraint_f_list[:1]
                                                                constraint_f_list=constraint_f_list
                                                                )
    print("finish getting po!")
    if True: #len(timeout_idx) > 0 or len(all_ltl_list) > 10:
        mc_mode = "nusmv"
    all_slice_list = get_sliced_branches(key_subset_of_val)
    slice_order = np.argsort([len(set(group).intersection(timeout_idx)) for group in all_slice_list])
    all_slice_list = [all_slice_list[idx] for idx in slice_order]
    slice_part = partition_slice_by_size(all_slice_list,min_group_size=min_group_size)
    #np.prod([len(entry) for entry in all_slice_list])/2**len(all_ltl_list)
    total_count = 0
    total_time = 0
    #trace = None
    #trace_f_list = None
    print("finish partition!")
    if constraint_f_list is not None and len(constraint_f_list) > 0:
        if mc_mode != "nusmv":
            trace = get_aut_product(constraint_f_list,bmc_k=bmc_k)
        else:
            trace = None
        trace_f_list = constraint_f_list.copy()
    else:
        trace = None
        trace_f_list = []
    total_prev_pos_set = set()
    total_prev_neg_set = set()
    for cur_slice_list in tqdm(slice_part):
        cur_trace = None
        #cur_goal = len(all_ltl_list)//2
        cur_all_idx = set([idx for group in cur_slice_list for idx in group])
        cur_goal = len(cur_all_idx)//2
        while cur_goal >= 0 and cur_trace is None:
            cur_trace,cur_trace_f_list,  cur_total_prev_pos_set, cur_total_prev_neg_set = get_maxmin_elim_mask_po_helper(all_ltl_list,cur_slice_list,
                                                   key_subset_of_val,key_superset_of_val,key_mutex_of_val,
                                                   aut_cache=aut_cache,bmc_k=bmc_k,
                                                   goal=cur_goal,
                                                   init_aut=trace,
                                                   init_f=trace_f_list,
                                                   cur_all_idx=cur_all_idx,
                                                   prev_pos=total_prev_pos_set.intersection(cur_all_idx), #TODO new
                                                   prev_neg=total_prev_neg_set.intersection(cur_all_idx), #TODO new
                                                   mc_mode=mc_mode)
            cur_goal -= 1
        if bmc_k is None:
            assert cur_trace is not None
        if cur_trace is not None:
            trace = cur_trace
            trace_f_list = cur_trace_f_list
            #handle new positives #TODO new
            for entry in cur_total_prev_pos_set:
                total_prev_pos_set.add(entry)
                total_prev_pos_set.update(key_subset_of_val[entry])
                total_prev_neg_set.update(key_mutex_of_val[entry])
            
            #handle new negatives #TODO new
            for entry in cur_total_prev_neg_set:
                total_prev_neg_set.add(entry)
                total_prev_neg_set.update(key_superset_of_val[entry])
        else:
            break
    print("finish iterating through slices!")
    if trace is not None:
        if isinstance(trace,tuple):
            cur_var_dict = dict((var,"boolean") for f in trace_f_list for var in spot_utils.get_variables_from_formula(f))
            trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula(" & ".join(trace_f_list)),bmc_k=bmc_k,use_trace=True)
            trace_formula = nusmv_utils.nusmv_trace_to_formula(trace)
        else:
            trace_formula = spot_utils.trace_to_formula(trace,debug=False)
        time.sleep(0.001)
        print("getting mask!")
        mask = get_mask_from_trace(all_ltl_list,trace_formula,mc_mode=mc_mode,bmc_k=bmc_k,aut_cache=aut_cache)
        print("got mask!")
        if mc_mode == "timeout" and not isinstance(trace,tuple):
            assert trace.accepting_run() is not None
            cur_f = spot_utils.trace_to_formula(trace,debug=False)
            cur_var_dict = dict((var,"boolean") for var in spot_utils.get_variables_from_formula(cur_f))
            trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula(cur_f),bmc_k=bmc_k,use_trace=True)
            assert trace is not None, cur_f   
        time.sleep(0.001)
        print("finish postprocessing trace!")
        return mask, trace
    else:
        print("could not find distinguishing trace!")
        #test_mask, test_trace = get_maxmin_elim_mask_spot(all_ltl_list,bmc_k=bmc_k,aut_cache=aut_cache)
        #assert test_trace is None
        return [None for entry in all_ltl_list], None

def get_hold_formula(proxy_list):
    return " ( "+" & ".join([f"({e})" for e in proxy_list]) + " ) "

def get_nothold_formula(proxy_list):
    return "( " + " & ".join([f"!({e})" for e in proxy_list]) + " ) "

def get_mask_from_trace(cur_f_list,trace_formula,mc_mode="nusmv",bmc_k=None,aut_cache=None):
    if aut_cache is None:
        aut_cache = AutomatonCache()
    if mc_mode != "nusmv":
        pos_f_list,neg_f_list,pos_aut_list,neg_aut_list,timeout_idx = get_aut_list_for_f(cur_f_list,aut_cache=aut_cache,check_timeout=mc_mode=="timeout")
    res = [None for entry in cur_f_list]
    if mc_mode == "spot" or mc_mode == "timeout":
        trace = spot.translate(trace_formula)
    for idx in tqdm(range(len(cur_f_list))):
        if mc_mode == "nusmv":
            cur_var_dict = dict((var,"boolean") for var in spot_utils.get_variables_from_formula(trace_formula)+spot_utils.get_variables_from_formula(get_hold_formula(cur_f_list[idx])))
            is_f_and_trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula("( "+trace_formula + ") & ("+ get_hold_formula(cur_f_list[idx]) +")"),bmc_k=bmc_k) is not None
            is_notf_and_trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula("( "+trace_formula + ") & ("+ get_nothold_formula(cur_f_list[idx]) +")"),bmc_k=bmc_k) is not None
            #is_f_and_trace = spot.product(trace,aut_cache.get_aut([get_hold_formula(cur_f_list[idx])])).accepting_run() is not None
            #is_notf_and_trace = spot.product(trace,aut_cache.get_aut([get_nothold_formula(cur_f_list[idx])])).accepting_run() is not None
        elif mc_mode == "spot":
            #is_f_and_trace = spot_utils.check_satisfiable("( "+trace_formula + ") & ("+ get_hold_formula(cur_f_list[idx]) +")") is not None
            #is_notf_and_trace = spot_utils.check_satisfiable("( "+trace_formula + ") & ("+ get_nothold_formula(cur_f_list[idx]) +")") is not None
            is_f_and_trace = spot.product(trace,aut_cache.get_aut([get_hold_formula(cur_f_list[idx])])).accepting_run() is not None
            is_notf_and_trace = spot.product(trace,aut_cache.get_aut([get_nothold_formula(cur_f_list[idx])])).accepting_run() is not None
        elif mc_mode == "timeout":
            if idx not in timeout_idx:
                is_f_and_trace = spot.product(trace,aut_cache.get_aut([get_hold_formula(cur_f_list[idx])])).accepting_run() is not None
                is_notf_and_trace = spot.product(trace,aut_cache.get_aut([get_nothold_formula(cur_f_list[idx])])).accepting_run() is not None
            else:
                cur_var_dict = dict((var,"boolean") for var in spot_utils.get_variables_from_formula(trace_formula)+spot_utils.get_variables_from_formula(get_hold_formula(cur_f_list[idx])))
                is_f_and_trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula("( "+trace_formula + ") & ("+ get_hold_formula(cur_f_list[idx]) +")"),bmc_k=bmc_k) is not None
                is_notf_and_trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula("( "+trace_formula + ") & ("+ get_nothold_formula(cur_f_list[idx]) +")"),bmc_k=bmc_k) is not None                
        if is_f_and_trace and not is_notf_and_trace:
            res[idx] = True
        elif not is_f_and_trace and is_notf_and_trace:
            res[idx] = False
        elif is_f_and_trace and is_notf_and_trace:
            res[idx] = None
        else:
            res[idx] = None
            #assert False, "f must allow or disallow the trace"
    return res

def get_myltltalk_elim_mask(total_var_dict,cur_f_list,mc_mode="nusmv",bmc_k=None,aut_cache=None,constraint_f_list=None):
    assert constraint_f_list is None, "adding constraint unimplemented for now"
    if aut_cache is None:
        aut_cache = AutomatonCache()
    if mc_mode != "nusmv":
        pos_f_list,neg_f_list,pos_aut_list,neg_aut_list,timeout_idx = get_aut_list_for_f(cur_f_list,aut_cache=aut_cache,check_timeout=mc_mode=="timeout",bmc_k=bmc_k)
    trace = None
    idx = 0
    #aut_dict = {}
    while trace is None and idx < len(cur_f_list):
        cur_f1 = get_hold_formula(cur_f_list[idx])
        if mc_mode == "spot":
            #cur_f1_aut = spot.translate(cur_f1)
            cur_f1_aut = aut_cache.get_aut([cur_f1])
        for i in range(len(cur_f_list)):
            if i != idx:
                cur_f2 = get_nothold_formula(cur_f_list[i])
                check_f = f"({cur_f1}) & ({cur_f2})"
                if mc_mode == "nusmv":
                    cur_var_dict = nusmv_utils.get_min_var_dict(total_var_dict,check_f)
                    trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula(check_f),bmc_k=bmc_k,use_trace=True)
                    if trace is not None:
                        break
                elif mc_mode == "spot":
                    cur_f2_aut = aut_cache.get_aut([cur_f2])
                    trace = spot.product(cur_f1_aut,cur_f2_aut)
                    if trace.accepting_run() is not None:
                        trace = trace.postprocess()
                        break
                    else:
                        trace = None
                elif mc_mode == "timeout":
                    """
                    if idx not in timeout_idx and i not in timeout_idx:
                        cur_f2_aut = aut_cache.get_aut([cur_f2])
                        trace = spot.product(cur_f1_aut,cur_f2_aut)
                        if trace.accepting_run() is not None:
                            trace = trace.postprocess()
                            trace_formula = spot.formula(spot_utils.trace_to_formula(trace,debug=False)).to_str(parenth=True)
                            trace = spot.translate(trace_formula)
                            break
                        else:
                            trace = None
                    else:
                        cur_var_dict = dict( (k,"boolean") for k in spot_utils.get_variables_from_formula(check_f) )
                        trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula(check_f),bmc_k=bmc_k,use_trace=True)
                        if trace is not None:
                            trace_formula = nusmv_utils.nusmv_trace_to_formula(trace)
                            trace = spot.translate(trace_formula)
                            break
                    """
                    cur_var_dict = dict( (k,"boolean") for k in spot_utils.get_variables_from_formula(check_f) )
                    check_f = spot_utils.filter_ltl_formula(check_f)
                    trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,check_f,bmc_k=bmc_k,use_trace=True)
                    if trace is not None:
                        trace_formula = nusmv_utils.nusmv_trace_to_formula(trace)
                        trace = spot.translate(trace_formula)
                        break
        idx += 1

    res = [None for entry in cur_f_list]
    if trace is not None:
        if mc_mode == "nusmv":
            trace_formula = nusmv_utils.nusmv_trace_to_formula(trace)
        elif mc_mode == "spot":
            trace_formula = spot.formula(spot_utils.trace_to_formula(trace,debug=False)).to_str(parenth=True)
            trace = spot.translate(trace_formula)
        for idx in tqdm(range(len(cur_f_list))):
            if mc_mode == "nusmv":
                is_f_and_trace = nusmv_utils.get_nusmv_ltl_satisfiable(total_var_dict,"( "+trace_formula + ") & ("+ get_hold_formula(cur_f_list[idx]) +")",bmc_k=bmc_k) is not None
                is_notf_and_trace = nusmv_utils.get_nusmv_ltl_satisfiable(total_var_dict,"( "+trace_formula + ") & ("+ get_nothold_formula(cur_f_list[idx]) +")",bmc_k=bmc_k) is not None
            elif mc_mode == "spot":
                #is_f_and_trace = spot_utils.check_satisfiable("( "+trace_formula + ") & ("+ get_hold_formula(cur_f_list[idx]) +")") is not None
                #is_notf_and_trace = spot_utils.check_satisfiable("( "+trace_formula + ") & ("+ get_nothold_formula(cur_f_list[idx]) +")") is not None
                is_f_and_trace = spot.product(trace,aut_cache.get_aut([get_hold_formula(cur_f_list[idx])])).accepting_run() is not None
                is_notf_and_trace = spot.product(trace,aut_cache.get_aut([get_nothold_formula(cur_f_list[idx])])).accepting_run() is not None
            elif mc_mode == "timeout":
                if idx not in timeout_idx:
                    is_f_and_trace = spot.product(trace,aut_cache.get_aut([get_hold_formula(cur_f_list[idx])])).accepting_run() is not None
                    is_notf_and_trace = spot.product(trace,aut_cache.get_aut([get_nothold_formula(cur_f_list[idx])])).accepting_run() is not None
                else:
                    is_f_and_trace = nusmv_utils.get_nusmv_ltl_satisfiable(total_var_dict,"( "+trace_formula + ") & ("+ get_hold_formula(cur_f_list[idx]) +")",bmc_k=bmc_k) is not None
                    is_notf_and_trace = nusmv_utils.get_nusmv_ltl_satisfiable(total_var_dict,"( "+trace_formula + ") & ("+ get_nothold_formula(cur_f_list[idx]) +")",bmc_k=bmc_k) is not None                    
            if is_f_and_trace and not is_notf_and_trace:
                res[idx] = True
            elif not is_f_and_trace and is_notf_and_trace:
                res[idx] = False
            elif is_f_and_trace and is_notf_and_trace:
                res[idx] = None
            else:
                res[idx] = None
                #assert False, "f must allow or disallow the trace"
        if mc_mode in ["nusmv","timeout"]:
            cur_var_dict = dict((var,"boolean") for var in spot_utils.get_variables_from_formula(trace_formula))
            trace = nusmv_utils.get_nusmv_ltl_satisfiable(cur_var_dict,spot_utils.filter_ltl_formula(trace_formula),bmc_k=bmc_k,use_trace=True)
            assert trace is not None, cur_f_list
        return res, trace
    else:
        return [None for entry in cur_f_list], None

def get_bottomup_distinguish(target_options,output_list,dcmp_list,total_var_dict,
                            get_mask_func=get_myltltalk_elim_mask,
                            mc_mode="nusmv",
                            bmc_k=7,
                            aut_cache=None,
                            constraint_f_list=None):
    total_log = []
    cur_outputs = output_list.copy()
    cur_dcmp_list = dcmp_list.copy()
    decided_decision_substrings = []
    while cur_dcmp_list:
        decision_substring = cur_dcmp_list.pop()
        selected_options_dict = group_output_options_by_decomposition_list(cur_outputs,dcmp_list)
        if len(cur_dcmp_list) > 0:
            cur_options = selected_options_dict[decision_substring]
            all_proxy_list = []
            target_f = None
            cur_var_set = set()
            for i in range(len(cur_options)):
                option_dict = cur_options[i]
                for prev_substring in decided_decision_substrings:
                    option_dict.update(selected_options_dict[prev_substring][i])
                cur_var_set.update(get_all_variables_from_option_dict(option_dict))
                cur_proxy = get_leaf_proxy_from_dcmp_group(option_dict,cur_outputs=cur_outputs)
                all_proxy_list.append(cur_proxy)
                if is_equal_intersection_option(option_dict,target_options):
                    target_f = cur_proxy
            print(option_dict)
            assert target_f is not None
            #remove syntatically equivalent proxies
            nondup_list = []
            for idx in range(len(all_proxy_list)):
                if all_proxy_list[idx] not in nondup_list:
                    nondup_list.append(all_proxy_list[idx])
            #remove semantically equivalent proxies
            #new_idx_list,equiv_dict = remove_equivalent_idx([get_hold_formula(lst) for lst in nondup_list],ret_equiv_dict=True,
            #                                                mc_mode=mc_mode,bmc_k=bmc_k,constraint_f_list=constraint_f_list)
            constraint_f = " & ".join([f"({f})" for f in constraint_f_list])
            new_idx_list,equiv_dict = remove_equivalent_idx_old([f"({get_hold_formula(lst)}) & ({constraint_f})" for lst in nondup_list],ret_equiv_dict=True,mc_mode=mc_mode,bmc_k=bmc_k)
            select_f_list = None
            for idx,idx_list in equiv_dict.items():
                equiv_proxies = [nondup_list[idx]] + [nondup_list[i] for i in idx_list]
                if target_f in equiv_proxies:
                    assert idx in new_idx_list
                    print("target_f equivalent to",len(equiv_proxies))
                    print([" & ".join(lst) for lst in nondup_list])
                    select_f_list = equiv_proxies
                    target_f = nondup_list[idx]
            nondup_list = [nondup_list[idx] for idx in new_idx_list]
            if select_f_list is None:
                assert target_f in nondup_list
                select_f_list = [target_f]
            print(len(nondup_list))
            log,res_f = get_query_log(target_f,total_var_dict,nondup_list,get_mask_func=get_mask_func,mc_mode=mc_mode,bmc_k=bmc_k,constraint_f_list=constraint_f_list)
            log = [list(e)+["proxy",cur_var_set.copy()] for e in log]
            found_correct = False
            new_outputs = []
            for i in range(len(cur_options)):
                #if all_proxy_list[i] in select_f_list:
                if all_proxy_list[i] in res_f or all_proxy_list[i] in select_f_list:
                    new_outputs.append(cur_outputs[i])
                if all_proxy_list[i] in res_f and all_proxy_list[i] in select_f_list:
                    found_correct = True
            assert found_correct
            total_log += log
            cur_outputs = new_outputs
        else:
            if len(cur_outputs) == 1:
                break
            print("final:",len(cur_outputs))
            for output in cur_outputs:
                print(output["decision2"],output["bool_exp3"])
            assert target_options in [get_output_options(e) for e in cur_outputs]    
            all_proxy_list = [[get_ltl_from_output(e)] for e in cur_outputs]
            target_f = [get_ltl_from_options(target_options)]
            assert target_f in all_proxy_list,print(target_f,all_proxy_list)
            log,res_f = get_query_log(target_f,total_var_dict,all_proxy_list,get_mask_func=get_mask_func,mc_mode=mc_mode,bmc_k=bmc_k,aut_cache=aut_cache)
            log = [list(e)+["full",set(total_var_dict.keys())] for e in log]
            total_log += log
            assert target_f == res_f[0]
            #print(len(log))
        decided_decision_substrings.append(decision_substring)
    return total_log

if os.getenv("STRUCTNL_MODE") == "fretish":
    decision_to_var_constraint_map = \
    {
        "_ABSTRACT_VAR1_":{},
        "while bool_exp1, _ABSTRACT_VAR1_":{"bool_exp1":"m1"}, 
        "after bool_exp1, _ABSTRACT_VAR1_":{"bool_exp1":"m3"},
        "before bool_exp1, _ABSTRACT_VAR1_":{"bool_exp1":"m4"},
        "only while bool_exp1, _ABSTRACT_VAR1_":{"bool_exp1":"m5"},
        "only after bool_exp1, _ABSTRACT_VAR1_":{"bool_exp1":"m6"},
        "only before bool_exp1, _ABSTRACT_VAR1_":{"bool_exp1":"m7"},
        "whenever bool_exp1, _ABSTRACT_VAR1_":{"bool_exp1":"c1"},
        "upon bool_exp1, _ABSTRACT_VAR1_":{"bool_exp1":"c2"},
        
        "_ABSTRACT_VAR2_":{},
        "whenever bool_exp2, _ABSTRACT_VAR2_":{"bool_exp2":"c1"},
        "upon bool_exp2, _ABSTRACT_VAR2_":{"bool_exp2":"c2"},
        
    }
    
    def get_leaf_proxy_template(decision2,decision3,cur_outputs=None):
        proxy_version = "2"
        if proxy_version == "1":
            return helper_get_leaf_proxy_template(decision2,decision3)
        elif proxy_version == "2":
            return helper_get_leaf_proxy_template_v2(decision2,decision3,cur_outputs=cur_outputs)
        else:
            assert False
    
    
    proxy_decision3_name_map = \
    {
        'immediately satisfy bool_exp3':'immediately',
        'within N_DURATION ticks satisfy bool_exp3':'within N_DURATION ticks',
        'after N_DURATION ticks satisfy bool_exp3':'after N_DURATION ticks',
        'until bool_exp4, satisfy bool_exp3':'until s',
        'always satisfy bool_exp3':'always',
        'never satisfy bool_exp3':'never',
        'at the next timepoint satisfy bool_exp3':'at the next timepoint',
        'eventually satisfy bool_exp3':'eventually',
        'for N_DURATION ticks satisfy bool_exp3':'for N_DURATION ticks',
        'before bool_exp4, satisfy bool_exp3':'before s',
    }
    
    proxy_decision2_name_map = \
    {
        "whenever bool_exp2, _ABSTRACT_VAR2_":"whenever c",
        "upon bool_exp2, _ABSTRACT_VAR2_":"upon c",
        "_ABSTRACT_VAR2_":"",
    }
    
    with open(DATA_HOME_DIR+"/fretish_condition-timing_proxy_start_step_dict.json", "r") as file:
        fretish_condtiming_proxy_start_step_dict = json.load(file)
    with open(DATA_HOME_DIR+"/fretish_condition-timing_proxy_dict.json", "r") as file:
        fretish_condtiming_proxy_dict = json.load(file)
    with open(DATA_HOME_DIR+"/fretish_timing_proxy_start_step_dict.json", "r") as file:
        fretish_timing_proxy_start_step_dict = json.load(file)
    with open(DATA_HOME_DIR+"/fretish_timing_proxy_dict.json", "r") as file:
        fretish_timing_proxy_dict = json.load(file)
    
    
    def helper_get_leaf_proxy_template_v2(decision2,decision3,cur_outputs=None):
        global proxy_decision3_name_map
        global proxy_decision3_name_map
        global fretish_timing_proxy_dict
        global fretish_condtiming_proxy_dict
        if decision2 is None:
            return fretish_timing_proxy_dict[proxy_decision3_name_map[decision3]].copy()
        else:
            template_key = (proxy_decision2_name_map[decision2],proxy_decision3_name_map[decision3])
            need_full_split = True
            if cur_outputs is not None:
                need_split_options = set([
                    "only while bool_exp1, _ABSTRACT_VAR1_",
                    "only before bool_exp1, _ABSTRACT_VAR1_",
                    "only after bool_exp1, _ABSTRACT_VAR1_",
                ])
                cur_decision1_options = set(output["decision1"] for output in cur_outputs)
                if len(cur_decision1_options.intersection(need_split_options)) == 0:
                    need_full_split = False
            if need_full_split:
                return fretish_condtiming_proxy_dict[str(template_key)].copy()
            else:
                return [fretish_condtiming_proxy_dict[str(template_key)][0]]
            
    def helper_get_leaf_proxy_template(decision2,decision3):
        #NOTE: proxt_nothold is NOT negated
        if decision2 is None:
            #timing proxy under any scope+condition
            if "until" not in decision3 and "before" not in decision3:
                decision3_ltl = get_structnl_to_ltl_template(decision1="_ABSTRACT_VAR1_",decision2="_ABSTRACT_VAR2_",decision3=decision3)
                proxy = [decision3_ltl]
            elif "until" in decision3:
                weak_until = "(bool_exp3 U bool_exp4)" #strong until
                strong_until = "(bool_exp4 V (bool_exp4 | bool_exp3))" #weak until
                proxy = [weak_until,strong_until]
            elif "before" in decision3:
                #strong_before = "((bool_exp3 V (!bool_exp4)) & F bool_exp4)" #strong before
                strong_before = "((bool_exp3 V (!bool_exp4)) & F bool_exp3)" #strong before
                weak_before = "(bool_exp3 V (! bool_exp4))" #weak before
                proxy = [strong_before,weak_before]
            else:
                assert False, decision3
        else:
            #condition+timing proxy under any scope
            decision3_proxy_list = get_leaf_proxy_template(decision2=None,decision3=decision3)
            if "whenever" in decision2:
                proxy = []
                for decision3_proxy in decision3_proxy_list:
                    proxy.append(f"!(G (bool_exp2 -> !({decision3_proxy})))")
                    proxy.append(f"(G (bool_exp2 -> ({decision3_proxy})))")                  
            elif "upon" in decision2:
                proxy = []
                for decision3_proxy in decision3_proxy_list:
                    proxy.append(f"!((G (((! bool_exp2) & (X bool_exp2)) -> (X !({decision3_proxy}))) & (bool_exp2 -> !({decision3_proxy}))))")
                    proxy.append(f"((G (((! bool_exp2) & (X bool_exp2)) -> (X ({decision3_proxy}))) & (bool_exp2 -> ({decision3_proxy}))))")
            elif decision2 == "_ABSTRACT_VAR2_":
                proxy = decision3_proxy_list
            else:
                assert False, decision2
        return proxy
    
    def helper_fill_templates(templates,option_dict):
        for items in option_dict.values():
            if items["option"] not in ["_ABSTRACT_VAR2_","_ABSTRACT_VAR1_"]:
                for k,v in items.items():
                    if k == "N_DURATION" and v is not None and v != "":
                        for i in range(len(templates)):
                            templates[i] = templates[i].replace("N_DURATION+1",str(v+1))
                            templates[i] = templates[i].replace("N_DURATION-1",str(v-1))
                            templates[i] = templates[i].replace("N_DURATION",str(v))
                    elif k != "option" and v is not None and v != "":
                        for i in range(len(templates)):
                            cur_exp = spot.formula(v).to_str(parenth=True)
                            if cur_exp == "1":
                                cur_exp = "TRUE"
                            elif cur_exp == "0":
                                cur_exp = "FALSE"
                            templates[i] = templates[i].replace(k,f"({cur_exp})")
                            #templates[i] = templates[i].replace(k,str(v))
        return templates
    
    def get_leaf_proxy_from_dcmp_group(option_dict,cur_outputs=None):
        global proxy_start_step
        if all(entry in option_dict for entry in decision_order):
            return [f"{'X ' * proxy_start_step}  ({get_ltl_from_options(option_dict)})"]
        if "decision2" in option_dict:
            decision2 = option_dict["decision2"]["option"]
        else:
            decision2 = None
        decision3 = option_dict["decision3"]["option"]
        proxy = get_leaf_proxy_template(decision2,decision3,cur_outputs=cur_outputs)
        proxy = helper_fill_templates(proxy,option_dict)
        return proxy
    
    def get_abstract_proxy_from_dcmp_group(option_dict,cur_outputs=None):
        #assert False, "deprecated for now"
        proxy_option_dict = option_dict.copy()
        if "decision3" not in option_dict:
            proxy_option_dict["decision3"] = {"option":"immediately satisfy bool_exp3"}
        if "decision2" not in option_dict:
            assert "decision3" not in option_dict or "decision1" not in option_dict
            proxy_option_dict["decision2"] = {"option":"_ABSTRACT_VAR2_"}
        proxy = get_leaf_proxy_from_dcmp_group(proxy_option_dict,cur_outputs=cur_outputs)
        return proxy
        """
        if "decision2" in option_dict:
            decision2 = option_dict["decision2"]["option"]
        else:
            decision2 = "_ABSTRACT_VAR2_"
        if "decision1" in option_dict:
            decision1 = option_dict["decision1"]["option"]
            templates = [get_structnl_to_ltl_template(decision1=decision1,decision2=decision2,decision3='immediately satisfy bool_exp3')]
            proxy = helper_fill_templates(templates,option_dict)
        elif "decision3" in option_dict:
            proxy = get_leaf_proxy_from_dcmp_group(option_dict)
        else:
            assert "decision2" in option_dict
            templates = [get_structnl_to_ltl_template(decision1="_ABSTRACT_VAR1_",decision2=decision2,decision3='immediately satisfy bool_exp3')]
            proxy = helper_fill_templates(templates,option_dict)
        return proxy
        """
    def get_fretish_witness_trace():
        #transitions
        b0_1 = "(!c1 & !c2 & m3 & !m4 & m5 & m6 & !m7)"
        b0_2 = "(!c1 & !c2 & m3 & !m4 & m5 & !m6 & !m7)"
        b1 = "(c1 & c2 & m1 & !m2 & !m3 & !m4 & !m5 & m6 & m7)"
        b2_4 = "(c1 & c2 & m1 & !m2 & !m3 & !m4 & !m5 & m6 & m7)"
        b2_5 = "(c1 & c2 & m1 & !m2 & !m3 & !m4 & !m5 & !m6 & m7)"
        a3 = "(!c1 & !c2 & m1 & !m2 & !m4 & !m5 & m6)"
        a4 = "(!c1 & c2 & m1 & !m2 & !m4 & !m5 & m6)"
        b4 = "(!c1 & !c2 & m1 & !m2 & !m4 & !m5 & m6)"
        a5 = "(!c1 & c2 & m1 & !m2 & !m4 & !m5 & !m6)"
        b5_4 = "(!c1 & c2 & m1 & !m2 & !m4 & !m5 & m6)"
        b5_3 = "(!c1 & !c2 & m1 & !m2 & !m4 & !m5 & m6)"
        b5_6 = "(!c1 & !c2 & m1 & !m2 & !m4 & !m5 & !m6)"
        a6 = "(!c1 & !c2 & m1 & !m2 & !m4 & !m5 & !m6)"
        b6 = "(!c1 & !c2 & m1 & !m2 & !m4 & !m5 & m6)"
        
        ## functions
        f_3 = f"G ({a3})"
        f_4 = f"{a4} W ({b4} & X({f_3}))"
        f_6 = f"{a6} W ({b6} & X({f_3}))"
        f_5 = f"{a5} W ( ({b5_4} & X({f_4})) | ({b5_3} & X ({f_3})) | ({b5_6} & X ({f_6})) )"
        f_2 = f"({b2_4} & X ({f_4})) | ({b2_5} & X({f_5}))"
        f_1 = f"{b1} & X({f_4})"
        f_0 = f"({b0_1} & X({f_1})) | ({b0_2} & X({f_2}))"
        return spot_utils.filter_ltl_formula(f_0)
elif os.getenv("STRUCTNL_MODE") == "SPS":
    with open(DATA_HOME_DIR+"/sps_proxy_start_step_dict.json", "r") as file:
        sps_proxy_start_step_dict = json.load(file)
    with open(DATA_HOME_DIR+"/sps_proxy_dict.json", "r") as file:
        sps_proxy_dict = json.load(file)
    for template_key,proxy_list in sps_proxy_dict.items():
        filter_list = []
        for proxy in proxy_list:
            filter_list.append(spot_utils.filter_ltl_formula(proxy))
        sps_proxy_dict[template_key] = filter_list
    proxy_start_step = 0

    decision_to_var_constraint_map = {
        "Globally, _ABSTRACT_VAR1_":{},
        "Before bool_exp2, _ABSTRACT_VAR1_":{"bool_exp2":"r1"},
        "After bool_exp1, _ABSTRACT_VAR1_":{"bool_exp1":"q1"},
        "Between bool_exp1 and bool_exp2, _ABSTRACT_VAR1_":{"bool_exp1":"q2","bool_exp2":"r2"},
        "After bool_exp1 until bool_exp2, _ABSTRACT_VAR1_":{"bool_exp1":"q3","bool_exp2":"r3"},
    }
    
    def get_leaf_proxy_template(decision2):
        return helper_get_leaf_proxy_template(decision2)
    
    def helper_get_leaf_proxy_template(decision2):
        global sps_proxy_dict
        return sps_proxy_dict[decision2].copy()

    def helper_fill_templates(templates,option_dict):
        for items in option_dict.values():
            if items["option"] not in ["_ABSTRACT_VAR1_"]:
                for k,v in items.items():
                    if k != "option" and v is not None and v != "":
                        for i in range(len(templates)):
                            cur_exp = spot.formula(v).to_str(parenth=True)
                            if cur_exp == "1":
                                cur_exp = "TRUE"
                            elif cur_exp == "0":
                                cur_exp = "FALSE"
                            templates[i] = templates[i].replace(k,f"({cur_exp})")
                            #templates[i] = templates[i].replace(k,str(v))
                            #templates[i] = spot_utils.filter_ltl_formula(templates[i])
        return templates
    
    def get_leaf_proxy_from_dcmp_group(option_dict,cur_outputs=None):
        global proxy_start_step
        if all(entry in option_dict for entry in decision_order):
            return [f"{'X ' * proxy_start_step}  ({get_ltl_from_options(option_dict)})"]
        decision2 = option_dict["decision2"]["option"]
        proxy = get_leaf_proxy_template(decision2)
        proxy = helper_fill_templates(proxy,option_dict)
        return proxy

    """
    def get_abstract_proxy_from_dcmp_group(option_dict,cur_outputs=None):
        #assert False, "deprecated for now"
        proxy_option_dict = option_dict.copy()
        if "decision3" not in option_dict:
            proxy_option_dict["decision3"] = {"option":"immediately satisfy bool_exp3"}
        if "decision2" not in option_dict:
            assert "decision3" not in option_dict or "decision1" not in option_dict
            proxy_option_dict["decision2"] = {"option":"_ABSTRACT_VAR2_"}
        proxy = get_leaf_proxy_from_dcmp_group(proxy_option_dict,cur_outputs=cur_outputs)
        return proxy
    """
elif os.getenv("STRUCTNL_MODE") == "PSP":
    proxy_start_step = 0
    decision_to_var_constraint_map = {
        "Globally, _ABSTRACT_VAR1_":{},
        "Before bool_exp2, _ABSTRACT_VAR1_":{"bool_exp2":"r1"},
        "After bool_exp1, _ABSTRACT_VAR1_":{"bool_exp1":"q1"},
        "Between bool_exp1 and bool_exp2, _ABSTRACT_VAR1_":{"bool_exp1":"q2","bool_exp2":"r2"},
        "After bool_exp1 until bool_exp2, _ABSTRACT_VAR1_":{"bool_exp1":"q3","bool_exp2":"r3"},
    }
    
    def get_leaf_proxy_from_dcmp_group(option_dict,cur_outputs=None):
        if all(entry in option_dict for entry in decision_order):
            return [f"({get_ltl_from_options(option_dict)})"]

        proxy_output = {"decision1":"Globally, _ABSTRACT_VAR1_", "decision2":option_dict["decision2"]["option"]}
        for item in decision_to_item_list["decision2"]:
            if item in option_dict["decision2"]:
                proxy_output[item] = option_dict["decision2"][item]
        proxy = [f"({get_ltl_from_output(proxy_output)})"]
        found_before_or_between = False
        for output in cur_outputs:
            if output["decision1"] in ["Before bool_exp2, _ABSTRACT_VAR1_","Between bool_exp1 and bool_exp2, _ABSTRACT_VAR1_"]:
                found_before_or_between = True
                break
        if found_before_or_between:
            proxy_output["decision1"] = "Before bool_exp2, _ABSTRACT_VAR1_"
            proxy_output["bool_exp2"] = "r1"
            proxy.append(f"({get_ltl_from_output(proxy_output)})")
        return proxy
        
    def get_PSP_witness_trace(t_length=20):
        t6_6 = "(!r2 & !r3)"
        t5_6 = "q2 & !r2 & !r3"
        t5_5 = "((r2 & !r3) | (!q2 & !r3))"
        t4_5 = "r1 & r2 & !r3"
        t4_4 = "!r1 & !r2 & !r3"
        t0_1 = "q1 & q2 & q3 & !r1 & !r2 & !r3"
        
        s6 = f"G ({t6_6})"
        s5 = f"(({t5_5}) W ({t5_6} & X({s6})))"
        s4 = f"(({t4_4}) U (({t4_5}) & X({s5})))"
        s1 = f"(G[0,{t_length-1}] ({t4_4}) & F[{t_length},{t_length}] ({s4}))"
        s0 = f"{t0_1} & X({s1})"
        return spot_utils.filter_ltl_formula(s0)
else:
    assert False

def format_bool_exp(in_exp):
    cur_exp = spot.formula(in_exp).to_str(parenth=True)
    if cur_exp == "1":
        cur_exp = "TRUE"
    elif cur_exp == "0":
        cur_exp = "FALSE"
    return cur_exp
    
def get_abstract_constraints(all_options,cur_options,cur_proxy_list,prev_proxy_list):
    #WARNING need to ensure cur_options[i] corresponds to cur_proxy_list[i]
    global proxy_start_step
    global decision_to_var_constraint_map
    print("len abs constraint:",len(prev_proxy_list))
    new_constraint_f_list = []
    for prev_proxy in prev_proxy_list:
        new_constraint_f_list.append(f"( G ( {'X '*proxy_start_step} (bool_exp3) -> ({get_hold_formula(prev_proxy)}) ))")
        new_constraint_f_list.append(f"( G ( {'X '*proxy_start_step} !(bool_exp3) -> ({get_nothold_formula(prev_proxy)}) ))")
    
    for i in range(len(cur_options)):
        for decision_type in cur_options[i]:
            decision = cur_options[i][decision_type]["option"]
            if decision in decision_to_var_constraint_map:
                var_constraint_map = decision_to_var_constraint_map[decision]
                for template_var, var in var_constraint_map.items():
                    new_constraint_f_list.append(f"(({get_hold_formula(cur_proxy_list[i])}) -> G (({format_bool_exp(cur_options[i][decision_type][template_var])}) <-> ({var})))")
    return new_constraint_f_list

def get_all_variables_from_option_dict(option_dict):
    var_set = set()
    for decision in option_dict:
        for item in decision_to_item_list[decision]:
            if "N_DURATION" not in item and option_dict[decision][item] is not None and option_dict[decision][item] != "" and option_dict[decision]['option'] not in ["_ABSTRACT_VAR2_","_ABSTRACT_VAR1_"] and item in option_dict[decision]['option']:
                try:
                    var_set.update(spot_utils.get_variables_from_formula(option_dict[decision][item]))
                except Exception as e:
                    print(e)
                    print(option_dict[decision])
                    print(item)
                    raise e
    return var_set

def remove_duplicate_proxies(nondup_list,target_f,total_constraint_f_list,mc_mode,bmc_k):
    #new_idx_list,equiv_dict = remove_equivalent_idx([get_hold_formula(lst) for lst in nondup_list],ret_equiv_dict=True,mc_mode=mc_mode,bmc_k=bmc_k,constraint_f_list=total_constraint_f_list)
    constraint_f = " & ".join([f"({f})" for f in total_constraint_f_list])
    new_idx_list,equiv_dict = remove_equivalent_idx_old([f"({get_hold_formula(lst)}) & ({constraint_f})" for lst in nondup_list],ret_equiv_dict=True,mc_mode=mc_mode,bmc_k=bmc_k)
    select_f_list = None
    for idx,idx_list in equiv_dict.items():
        equiv_proxies = [nondup_list[idx]] + [nondup_list[i] for i in idx_list]
        if target_f in equiv_proxies:
            assert idx in new_idx_list
            select_f_list = equiv_proxies
            target_f = nondup_list[idx]
    nondup_list = [nondup_list[idx] for idx in new_idx_list]
    #nondup_options_list = [nondup_options_list[idx] for idx in new_idx_list]
    if select_f_list is None:
        assert target_f in nondup_list
        select_f_list = [target_f]
    return nondup_list, select_f_list, target_f

def get_var_dict_for_formula(f):
    return dict((k,"boolean") for k in spot_utils.get_variables_from_formula(f))

def get_abstract_distinguish(target_options,output_list,dcmp_list,total_var_dict,
                            get_mask_func=get_myltltalk_elim_mask,
                            mc_mode="nusmv",
                            bmc_k=7,
                            aut_cache=None,
                            constraint_f_list=None):
    total_log = []
    cur_outputs = output_list.copy()
    cur_dcmp_list = dcmp_list.copy()
    decided_decision_substrings = []
    res_f = [] #proxies selected in previous step
    while cur_dcmp_list:
        selected_options_dict = group_output_options_by_decomposition_list(cur_outputs,dcmp_list)
        #for decision_substring in cur_dcmp_list[::-1]:
        decision_substring = cur_dcmp_list.pop()
        print(decision_substring)
        cur_options = selected_options_dict[decision_substring]
        total_cur_var_set = set()
        cur_var_set = set()
        all_proxy_list = []
        all_options_list = []
        target_f = None
        for i in range(len(cur_options)):
            option_dict = cur_options[i]
            cur_var_set.update(get_all_variables_from_option_dict(option_dict))
            #cur_proxy = get_abstract_proxy_from_dcmp_group(option_dict,cur_outputs=cur_outputs)
            proxy_option_dict = option_dict.copy()
            for prev_substring in decided_decision_substrings:
                proxy_option_dict.update(selected_options_dict[prev_substring][i])
            total_cur_var_set.update(get_all_variables_from_option_dict(proxy_option_dict))
            cur_proxy = get_leaf_proxy_from_dcmp_group(proxy_option_dict,cur_outputs=cur_outputs)
            all_options_list.append(proxy_option_dict)
            all_proxy_list.append(cur_proxy)
            if is_equal_intersection_option(proxy_option_dict,target_options):
                target_f = cur_proxy
        assert target_f is not None
        if len(decided_decision_substrings) > 0:
            cur_var_set.add("bool_exp3")
        print(len(cur_outputs),cur_var_set,total_cur_var_set)
        #remove syntatically equivalent proxies
        nondup_list = []
        nondup_options_list = []
        nondup_all_options_list = []
        for idx in range(len(all_proxy_list)):
            if all_proxy_list[idx] not in nondup_list:
                nondup_list.append(all_proxy_list[idx])
                nondup_options_list.append(cur_options[idx])
                nondup_all_options_list.append(all_options_list[idx])
        #remove semantically equivalent proxies
        print("options:",nondup_options_list[0])
        abs_constraint_f_list = get_abstract_constraints(all_options=nondup_all_options_list,cur_options=nondup_options_list,cur_proxy_list=nondup_list,prev_proxy_list=res_f)
        total_constraint_f_list = constraint_f_list + abs_constraint_f_list
        #if get_aut_product(total_constraint_f_list,bmc_k=bmc_k).accepting_run() is None:
        constraint_f = " & ".join([f"({f})" for f in total_constraint_f_list])
        sat_f = get_hold_formula(nondup_list[0])
        #sat_f = " | ".join([f"({get_hold_formula(lst)})" for lst in nondup_list])
        check_f = f"({constraint_f}) & ({sat_f})"
        if nusmv_utils.get_nusmv_ltl_satisfiable(get_var_dict_for_formula(check_f),spot_utils.filter_ltl_formula(check_f),bmc_k=bmc_k) is not None:
            print("abstract run!")
            nondup_list, select_f_list, target_f = remove_duplicate_proxies(nondup_list,target_f,total_constraint_f_list,mc_mode,bmc_k)
            print("cur num f:",len(nondup_list))
            log,res_f = get_query_log(target_f,total_var_dict,nondup_list,get_mask_func=get_mask_func,mc_mode=mc_mode,bmc_k=bmc_k,aut_cache=aut_cache,constraint_f_list=total_constraint_f_list)
            log = [list(e)+["proxy",cur_var_set.copy()] for e in log]
            total_log += log
            found_correct = False
            next_has_correct = False
            new_outputs = []
            nondup_list = []
            for i in range(len(cur_options)):
                #if all_proxy_list[i] in select_f_list:
                if all_proxy_list[i] in res_f or all_proxy_list[i] in select_f_list:    
                    new_outputs.append(cur_outputs[i])
                    nondup_list.append(all_proxy_list[i])
                    if is_equal_intersection_option(all_options_list[i],target_options):
                        target_f = all_proxy_list[i]
                        next_has_correct = True
                if all_proxy_list[i] in res_f and all_proxy_list[i] in select_f_list:
                    found_correct = True
            print("finishing abstract",len(nondup_list))
            assert found_correct
            assert next_has_correct

        print("standard run!")
        nondup_list, select_f_list, target_f = remove_duplicate_proxies(nondup_list,target_f,constraint_f_list,mc_mode,bmc_k)
        found = False
        for i in range(len(cur_options)):
            for entry in select_f_list:
                if entry == all_proxy_list[i] and is_equal_intersection_option(all_options_list[i],target_options):
                    found = True
        assert found
                
        log,res_f = get_query_log(target_f,total_var_dict,nondup_list,get_mask_func=get_mask_func,mc_mode=mc_mode,bmc_k=bmc_k,aut_cache=aut_cache,constraint_f_list=constraint_f_list)
        print(len(log),cur_var_set.copy())
        log = [list(e)+["proxy",total_cur_var_set.copy()] for e in log]
        total_log += log
        found_correct = False
        next_has_correct = False
        new_outputs = []
        for i in range(len(cur_options)):
            #if all_proxy_list[i] in select_f_list:
            if all_proxy_list[i] in res_f or all_proxy_list[i] in select_f_list:    
                new_outputs.append(cur_outputs[i])
                if is_equal_intersection_option(all_options_list[i],target_options):
                    next_has_correct = True
            if all_proxy_list[i] in res_f and all_proxy_list[i] in select_f_list:
                found_correct = True
        assert found_correct
        assert next_has_correct
        cur_outputs = new_outputs
        #print(len(log))
        decided_decision_substrings.append(decision_substring)
    if len(cur_outputs) > 1:
        assert target_options in [get_output_options(e) for e in cur_outputs]    
        all_proxy_list = [[get_ltl_from_output(e)] for e in cur_outputs]
        target_f = [get_ltl_from_options(target_options)]
        assert target_f in all_proxy_list,print(target_f,all_proxy_list)
        log,res_f = get_query_log(target_f,total_var_dict,all_proxy_list,get_mask_func=get_mask_func,mc_mode=mc_mode,bmc_k=bmc_k,aut_cache=aut_cache)
        log = [list(e)+["full",set(total_var_dict.keys())] for e in log]
        total_log += log
        assert target_f == res_f[0]
    else:
        assert target_options == get_output_options(cur_outputs[0])
    return total_log

def get_query_log(target_f,total_var_dict,cur_f_list,get_mask_func,mc_mode="nusmv",bmc_k=None,aut_cache=None,debug=True,constraint_f_list=None):
    assert len(cur_f_list) > 0
    if len(cur_f_list) == 1:
        return [], [cur_f_list[0]]
    start_trace_gen_t = time.time()
    cur_mask,trace = get_mask_func(total_var_dict,cur_f_list,mc_mode=mc_mode,bmc_k=bmc_k,aut_cache=aut_cache,constraint_f_list=constraint_f_list)
    end_trace_gen_t = time.time()
    if trace is None or sum([entry for entry in cur_mask if entry is not None]) == 0 or sum([entry for entry in cur_mask if entry is not None]) == len(cur_f_list)\
        or sum([1 for entry in cur_mask if entry is True]) == 0 or sum([1 for entry in cur_mask if entry is False]) == 0:
        return [], cur_f_list
    assert trace is not None
    
    accept_f_list = [cur_f_list[i] for i in range(len(cur_f_list)) if cur_mask[i] is True]
    reject_f_list = [cur_f_list[i] for i in range(len(cur_f_list)) if cur_mask[i] is False]
    dontcare_f_list = [cur_f_list[i] for i in range(len(cur_f_list)) if cur_mask[i] is None]
    #if target_f contains trace:
    if mc_mode == "nusmv" or mc_mode == "timeout":
        #is_target_f_contains_trace = nusmv_utils.get_nusmv_ltl_true(total_var_dict,"( "+nusmv_utils.nusmv_trace_to_formula(trace)+" ) -> ( "+get_hold_formula(target_f)+" )") is None
        is_target_f_contains_trace = nusmv_utils.get_nusmv_ltl_satisfiable(total_var_dict,"( "+nusmv_utils.nusmv_trace_to_formula(trace)+" ) & ( "+get_hold_formula(target_f)+" )",bmc_k=bmc_k) is not None
        #is_target_f_contains_trace = nusmv_utils.get_nusmv_ltl_satisfiable(total_var_dict,"( "+nusmv_utils.nusmv_trace_to_formula(trace)+" ) & ( "+get_hold_formula(target_f)+" )",bmc_k=None) is not None
        #is_target_f_contains_trace = spot_utils.check_satisfiable("( "+nusmv_utils.nusmv_trace_to_formula(trace)+" ) & ( "+get_hold_formula(target_f)+" )") is not None
    elif mc_mode == "spot":
        #is_target_f_contains_trace = spot.formula(get_hold_formula(target_f)).contains(trace)
        is_target_f_contains_trace = spot_utils.check_satisfiable("( "+spot_utils.trace_to_formula(trace,debug=False)+" ) & ( "+get_hold_formula(target_f)+" )") is not None
        #is_target_f_contains_trace = spot_utils.check_satisfiable("( "+nusmv_utils.nusmv_trace_to_formula(trace)+" ) & ( "+get_hold_formula(target_f)+" )") is not None
    else:
        assert False

    if target_f in accept_f_list:
        assert not debug or is_target_f_contains_trace
    elif target_f in reject_f_list:
        assert not debug or not is_target_f_contains_trace, target_f in dontcare_f_list
    
    if is_target_f_contains_trace:
        assert not debug or target_f in accept_f_list+dontcare_f_list
        accept_log, res_f = get_query_log(target_f,total_var_dict,accept_f_list+dontcare_f_list,get_mask_func=get_mask_func,mc_mode=mc_mode,bmc_k=bmc_k,aut_cache=aut_cache,debug=debug,constraint_f_list=constraint_f_list)
        assert not debug or target_f in res_f
        return [(trace,True,len(reject_f_list),len(cur_f_list),end_trace_gen_t-start_trace_gen_t)] + accept_log, res_f
    else:
        assert not debug or target_f in reject_f_list+dontcare_f_list
        reject_log, res_f = get_query_log(target_f,total_var_dict,reject_f_list+dontcare_f_list,get_mask_func=get_mask_func,mc_mode=mc_mode,bmc_k=bmc_k,aut_cache=aut_cache,debug=debug,constraint_f_list=constraint_f_list)
        assert not debug or target_f in res_f, len(reject_f_list+dontcare_f_list)
        return [(trace,False,len(accept_f_list),len(cur_f_list),end_trace_gen_t-start_trace_gen_t)] + reject_log, res_f

def get_num_vars_in_trace(trace,exclude_vars=None,include_vars=None):
    if exclude_vars is None:
        exclude_vars = set()
    prefix_list, cycle_list = trace
    if len(prefix_list) > 0:
        all_var_set = set(prefix_list[0].keys())
    elif len(cycle_list) > 0:
        all_var_set = set(cycle_list[0].keys())
    else:
        return 0
    if include_vars is None:
        return len(all_var_set-exclude_vars)
    else:
        return len(all_var_set.intersection(include_vars)-exclude_vars)
    

def get_results_from_trace_log(log,mc_mode,exclude_vars=None,proxy_start_step=0,bmc_k=20):
    num_traces = len(log)
    var_count = []
    tracesize = []
    balanced = []
    trace_gen_time = []
    for o_query in log:
        trace,is_accept,num_elim,num_total_f,gen_time,trace_type,var_set = o_query
        if mc_mode == "spot":
            trace_formula = spot_utils.trace_to_formula(trace,debug=False)
            trace = nusmv_utils.get_nusmv_ltl_satisfiable(dict((k,"boolean") for k in spot_utils.get_variables_from_formula(trace_formula)),trace_formula,bmc_k=bmc_k)
        prefix,cycle = trace
        if trace_type == "full":
            tracesize.append(len(prefix)+len(cycle))
        elif trace_type == "proxy":
            tracesize.append(max([len(prefix)-proxy_start_step,0])+len(cycle))
        else:
            assert False, "trace type not recognized!"
        var_count.append(get_num_vars_in_trace(trace,exclude_vars=exclude_vars,include_vars=var_set))
        balanced.append((num_elim , num_total_f))
        trace_gen_time.append(gen_time)
    return num_traces, var_count, tracesize, balanced, trace_gen_time

def trace_to_str(trace):
    prefix,cycle = trace
    prefix_res = []
    for entry in prefix:
        cur_assignment = []
        for var in entry:
            if entry[var] == 'TRUE':
                cur_assignment.append(var)
            else:
                cur_assignment.append(f"!{var}")
        prefix_res.append(" & ".join(cur_assignment))
    cycle_res = []
    for entry in cycle:
        cur_assignment = []
        for var in entry:
            if entry[var] == 'TRUE':
                cur_assignment.append(var)
            else:
                cur_assignment.append(f"!{var}")
        cycle_res.append(" & ".join(cur_assignment))
    return " ; ".join(prefix_res) + f" ; ({' ; '.join(cycle_res)})^w"
