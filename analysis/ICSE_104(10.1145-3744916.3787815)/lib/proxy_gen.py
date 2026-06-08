import spot
import spot_utils
import nusmv_utils
import itertools
from tqdm import tqdm
import buddy
import time
import numpy as np
import collections

def my_copy_aut(in_aut):
    #assert in_aut.num_sets() == 1
    assert in_aut.prop_state_acc()
    
    # The bdd_dict is used to maintain the correspondence between the
    # atomic propositions and the BDD variables that label the edges of
    # the automaton.
    bdict = in_aut.get_dict()
    # This creates an empty automaton that we have yet to fill.
    aut = spot.make_twa_graph(bdict)
    aut.copy_ap_of(in_aut)
    #aut.set_buchi()
    aut.set_acceptance(in_aut.num_sets(),in_aut.get_acceptance())
    aut.prop_state_acc(True)
    aut.new_states(in_aut.num_states())
    aut.set_univ_init_state(get_dest_list(in_aut,in_aut.get_init_state_number()))

    for s in range(0, in_aut.num_states()):
        for e in in_aut.out(s):
            aut.new_univ_edge(e.src, get_dest_list(in_aut,e.dst), e.cond, e.acc)
    
    assert aut.get_acceptance() == in_aut.get_acceptance()
    assert aut.num_sets() == in_aut.num_sets()
    assert aut.num_states() == in_aut.num_states()
    assert get_dest_list(aut,aut.get_init_state_number()) == get_dest_list(in_aut,in_aut.get_init_state_number())
    #assert aut.get_init_state_number() == in_aut.get_init_state_number()
    return aut

def get_aut_shannon_expansion(in_aut,universal_var_names):
    filtered_universal_var_names = set([var for var in universal_var_names if var in in_aut.ap()])
    if len(filtered_universal_var_names) == 0:
        return spot.translate("1","coBuchi","deterministic","sbacc")
    univ_var_list = [buddy.bdd_ithvar(in_aut.register_ap(var_name)) for var_name in filtered_universal_var_names]
    univ_labels = []
    for mask in itertools.product([True,False],repeat=len(univ_var_list)):
        if mask[0]:
            cur_label = univ_var_list[0]
        else:
            cur_label = -univ_var_list[0]
        for i in range(1,len(univ_var_list)):
            if mask[i]:
                cur_label = cur_label & univ_var_list[i]
            else:
                cur_label = cur_label & -univ_var_list[i]
        univ_labels.append(cur_label)
    
    bdict = in_aut.get_dict()
    aut = spot.make_twa_graph(bdict)
    aut.copy_ap_of(in_aut)
    aut.set_acceptance(in_aut.num_sets(),in_aut.get_acceptance())
    aut.prop_state_acc(in_aut.prop_state_acc())
    aut.new_states(in_aut.num_states())
    aut.set_univ_init_state(get_dest_list(in_aut,in_aut.get_init_state_number()))
    
    for s in range(0, in_aut.num_states()):
        for e in in_aut.out(s):
            for label in univ_labels:
                if spot.bdd_format_formula(bdict, e.cond & label) != "0":
                    aut.new_univ_edge(e.src, get_dest_list(in_aut,e.dst), label, e.acc)
    
    assert aut.get_acceptance() == in_aut.get_acceptance()
    assert aut.num_sets() == in_aut.num_sets()
    assert aut.num_states() == in_aut.num_states()
    assert get_dest_list(aut,aut.get_init_state_number()) == get_dest_list(in_aut,in_aut.get_init_state_number())
    #assert aut.get_init_state_number() == in_aut.get_init_state_number()
    aut.merge_edges()
    return aut

def remove_states_on_condition(in_aut,cond_f,**cond_f_args):
    #assert in_aut.num_sets() == 1
    assert in_aut.prop_state_acc()
    
    bdict = in_aut.get_dict()
    aut = spot.make_twa_graph(bdict)
    aut.copy_ap_of(in_aut)
    #aut.set_buchi()
    aut.set_acceptance(in_aut.num_sets(),in_aut.get_acceptance())
    aut.prop_state_acc(True)
    aut.new_states(in_aut.num_states())
    aut.set_init_state(in_aut.get_init_state_number())
    valid_states = set()
    for s in range(0, in_aut.num_states()):
        is_valid_state = cond_f(all_state_edges=in_aut.out(s),aut_bdict=bdict,**cond_f_args)
        if is_valid_state:
            valid_states.add(s)

    for s in valid_states:
        for e in in_aut.out(s):
            if e.dst in valid_states:
                aut.new_univ_edge(e.src, [e.dst], e.cond, e.acc)
                #aut.new_edge(e.src, e.dst, e.cond, e.acc)
    
    return aut

def is_state_contains_all_labels(all_state_edges,aut_bdict,labels,**kwargs):
    all_transition_cond = []
    for e in all_state_edges:
        all_transition_cond.append(f"({spot.bdd_format_formula(aut_bdict, e.cond)})")
    transition_f = " | ".join(all_transition_cond)
    has_all_labels = all([spot_utils.check_satisfiable(f"({transition_f}) & ({f})") for f in labels])
    return has_all_labels

def is_state_contains_any_label(all_state_edges,aut_bdict,labels,**kwargs):
    all_transition_cond = []
    for e in all_state_edges:
        all_transition_cond.append(f"({spot.bdd_format_formula(aut_bdict, e.cond)})")
    transition_f = " | ".join(all_transition_cond)
    has_any_label = any(spot.contains(transition_f,f) for f in labels)
    return has_any_label

def reduce_labels_no_existential(in_aut,universal_var_names):
    #assert in_aut.num_sets() == 1
    assert in_aut.prop_state_acc()

    universal_var_names = [var for var in universal_var_names if var in in_aut.ap()]
    univ_var_list = [buddy.bdd_ithvar(in_aut.register_ap(var_name)) for var_name in universal_var_names]
    univ_labels = []
    for mask in itertools.product([True,False],repeat=len(univ_var_list)):
        if mask[0]:
            cur_label = univ_var_list[0]
        else:
            cur_label = -univ_var_list[0]
        for i in range(1,len(univ_var_list)):
            if mask[i]:
                cur_label = cur_label & univ_var_list[i]
            else:
                cur_label = cur_label & -univ_var_list[i]
        univ_labels.append(cur_label)
    #var_m = buddy.bdd_ithvar(in_aut.register_ap("m"))
    #univ_labels = [var_m, -var_m]
    #labels = [var_r_c & var_m, var_r_c & -var_m, -var_r_c & var_m, -var_r_c & -var_m]
    
    bdict = in_aut.get_dict()
    aut = spot.make_twa_graph(bdict)
    aut.copy_ap_of(in_aut)
    #aut.set_buchi()
    aut.set_acceptance(in_aut.num_sets(),in_aut.get_acceptance())
    aut.prop_state_acc(True)
    aut.new_states(in_aut.num_states())
    aut.set_init_state(in_aut.get_init_state_number())
    for s in range(0, in_aut.num_states()):
        all_transition_f = " | ".join([f"({spot.bdd_format_formula(bdict, e.cond)})" for e in in_aut.out(s)])
        for label_idx in range(len(univ_labels)):
            cond_f = spot.bdd_format_formula(bdict, univ_labels[label_idx])
            if spot.contains(all_transition_f,cond_f):
                nondet_edges = []
                for e in in_aut.out(s):
                    cur_transition_f = spot.bdd_format_formula(bdict, e.cond)
                    is_sat = spot_utils.check_satisfiable(f"({cur_transition_f}) & ({cond_f})") is not None
                    if is_sat:
                        nondet_edges.append(e)
                if len(nondet_edges) > 0:
                    aut.new_univ_edge(s,[e.dst for e in nondet_edges],univ_labels[label_idx],nondet_edges[0].acc)           
    return aut

def get_possible_subsets(cur_idx_list,all_transition_f_list,cond_f):
    if len(cur_idx_list) <= 1:
        return [cur_idx_list]

    res = []
    for i in range(len(cur_idx_list)):
        new_idx_list = cur_idx_list[:i] + cur_idx_list[i+1:]
        cur_all_transition_f = " | ".join([all_transition_f_list[idx] for idx in new_idx_list])
        if spot.contains(cur_all_transition_f,cond_f):
            res += get_possible_subsets(new_idx_list,all_transition_f_list,cond_f)
    if len(res) > 0:
        return res
    else:
        return [cur_idx_list]

def get_all_nondet_sets(edge_list,all_transition_f_list,cond_f):
    assert len(edge_list) == len(all_transition_f_list)
    all_edge_idx_lists = get_possible_subsets([i for i in range(len(edge_list))],all_transition_f_list,cond_f)
    all_edge_idx_lists = list(set([frozenset(idx_list) for idx_list in all_edge_idx_lists]))
    return [[edge_list[idx] for idx in idx_list] for idx_list in all_edge_idx_lists]

def get_shannon_expansion(bool_f,var_list):
    sorted_var_list = sorted(var_list, key=len, reverse=True)
    f_list = []
    for var_assign in itertools.product(["( TRUE )","( FALSE )"],repeat=len(var_list)):
        cur_f = bool_f
        for i in range(len(sorted_var_list)):
            cur_f = cur_f.replace(sorted_var_list[i],var_assign[i])
        f_list.append(f"({cur_f})")
    return " | ".join(f_list)

def reduce_labels(in_aut,universal_var_names,existential_var_names=[],include_existential_var_labels=True):
    #assert in_aut.num_sets() == 1
    assert in_aut.prop_state_acc()
    valid_label_time = 0
    transition_check_time = 0
    total_start_t = time.time()

    filtered_universal_var_names = set([var for var in universal_var_names if var in in_aut.ap()])
    if len(filtered_universal_var_names) == 0:
        #print(universal_var_names)
        #print(in_aut.ap())
        if spot.are_equivalent(in_aut,"1"):
            return spot.translate("1","coBuchi","deterministic","sbacc")
        else:
            return spot.translate("0","coBuchi","deterministic","sbacc")
    univ_var_list = [buddy.bdd_ithvar(in_aut.register_ap(var_name)) for var_name in filtered_universal_var_names]
    univ_labels = []
    for mask in itertools.product([True,False],repeat=len(univ_var_list)):
        if mask[0]:
            cur_label = univ_var_list[0]
        else:
            cur_label = -univ_var_list[0]
        for i in range(1,len(univ_var_list)):
            if mask[i]:
                cur_label = cur_label & univ_var_list[i]
            else:
                cur_label = cur_label & -univ_var_list[i]
        univ_labels.append(cur_label)
    ignore_vars = existential_var_names
    
    bdict = in_aut.get_dict()
    aut = spot.make_twa_graph(bdict)
    aut.copy_ap_of(in_aut)
    #aut.set_buchi()
    aut.set_acceptance(in_aut.num_sets(),in_aut.get_acceptance())
    aut.prop_state_acc(True)
    aut.new_states(in_aut.num_states())
    aut.set_init_state(in_aut.get_init_state_number())
    for s in range(0, in_aut.num_states()):
        edge_list = [e for e in in_aut.out(s)]
        all_transition_f_list = []
        for e in edge_list:
            cur_transition_f = get_shannon_expansion(spot.bdd_format_formula(bdict, e.cond),ignore_vars)
            all_transition_f_list.append(cur_transition_f)
        all_transition_f = "("+" | ".join(all_transition_f_list)+")"
        for label_idx in range(len(univ_labels)):
            cond_f = spot.bdd_format_formula(bdict, univ_labels[label_idx])
            start_t = time.time()
            is_valid_label = spot.contains(all_transition_f,cond_f)
            valid_label_time += time.time() - start_t
            if is_valid_label:
                #first get all edges that work with external_label[label_idx] (pos_edges)
                pos_edges = []
                pos_edges_transition_f_list = []
                for e_idx in range(len(edge_list)):
                    cur_transition_f = all_transition_f_list[e_idx]
                    start_t = time.time()
                    is_sat = spot_utils.check_satisfiable(f"({cur_transition_f}) & ({cond_f})") is not None
                    transition_check_time += time.time() - start_t
                    if is_sat:
                        pos_edges.append(edge_list[e_idx])
                        pos_edges_transition_f_list.append(cur_transition_f)
                if len(existential_var_names) > 0:
                    #nondet_sets = get_all_nondet_sets(edge_list,all_transition_f_list,cond_f)
                    nondet_sets = get_all_nondet_sets(pos_edges,pos_edges_transition_f_list,cond_f)
                else:
                    nondet_sets = [pos_edges]
                for nondet_edges in nondet_sets:
                    if len(existential_var_names) > 0 and include_existential_var_labels:
                        new_edge_label = nondet_edges[0].cond
                        for i in range(1,len(nondet_edges)):
                            new_edge_label = new_edge_label | nondet_edges[i].cond
                        new_edge_label = new_edge_label & univ_labels[label_idx]
                    else:
                        new_edge_label = univ_labels[label_idx]
                    aut.new_univ_edge(s,[e.dst for e in nondet_edges],new_edge_label,nondet_edges[0].acc)           
    
    #print("valid label check:",valid_label_time)
    #print("transitioncheck:",transition_check_time)
    #print("total time:",time.time()-total_start_t)
    return aut

def get_proxy_constraint_list_inorder(all_f_list,all_shift_step_list,all_sign_list):
    cur_f_list = []
    for i in range(len(all_f_list)-1):
        for j in range(len(all_f_list[i])):
            cur_f1 = f"({' X '*(all_shift_step_list[i][j])} ({all_f_list[i][j]}))"
            cur_f1_sign = all_sign_list[i][j]

            cur_f2 = f"({' X '*(all_shift_step_list[i+1][j])} ({all_f_list[i+1][j]}))"
            cur_f2_sign = all_sign_list[i+1][j]
            
            if cur_f1_sign == cur_f2_sign:
                cur_f_list.append(f"( ({cur_f1}) <-> ({cur_f2}) )")
            else:
                cur_f_list.append(f"( ({cur_f1}) <-> !({cur_f2}) )")
    return cur_f_list

def get_proxy_constraint_list_minvar(all_f_list,all_shift_step_list,all_sign_list):
    cur_f_list = []
    for j in range(len(all_f_list[0])):
        best_idx = np.argmin([ len(spot_utils.get_variables_from_formula(all_f_list[i][j])) for i in range(len(all_f_list))])
        cur_f1 = f"({' X '*(all_shift_step_list[best_idx][j])} ({all_f_list[best_idx][j]}))"
        cur_f1_sign = all_sign_list[best_idx][j]
        for i in range(len(all_f_list)):
            if i != best_idx:
                cur_f2 = f"({' X '*(all_shift_step_list[i][j])} ({all_f_list[i][j]}))"
                cur_f2_sign = all_sign_list[i][j]
                if cur_f1_sign == cur_f2_sign:
                    cur_f_list.append(f"( ({cur_f1}) <-> ({cur_f2}) )")
                else:
                    cur_f_list.append(f"( ({cur_f1}) <-> !({cur_f2}) )")
    return cur_f_list

def get_proxy_constraint_list(all_f_list,all_shift_step_list,all_sign_list):
    #return get_proxy_constraint_list_inorder(all_f_list,all_shift_step_list,all_sign_list)
    return get_proxy_constraint_list_minvar(all_f_list,all_shift_step_list,all_sign_list)

def get_nontrivial_constraint_per_template(all_f_list,all_shift_step_list,all_sign_list,universal_var_names):
    cur_f_list = []
    for j in range(len(all_f_list[0])):
        best_idx = np.argmin([ len(spot_utils.get_variables_from_formula(all_f_list[i][j])) for i in range(len(all_f_list))])
        cur_f = f"({' X '*(all_shift_step_list[best_idx][j])} ({all_f_list[best_idx][j]}))"
        cur_f_sign = all_sign_list[best_idx][j]
        if cur_f_sign:
            cur_f = f"!({cur_f})"
        cur_f_list.append(cur_f)
    return cur_f_list


def my_simplify_aut(aut):
    res =  spot.remove_alternation(aut).postprocess("deterministic","coBuchi","sbacc")
    assert res is not None
    return res

def get_reduce_and_simplify_all(cur_f_list,universal_var_names,init_aut,cache={}):
    res_list = []
    for f in cur_f_list:
        if f in cache:
            cur_aut = cache[f]
            res_list.append(cur_aut)
        else:
            cur_aut = reduce_wrapper(f,universal_var_names).postprocess()
            cache[f] = cur_aut
            res_list.append(cur_aut)
    return res_list

def apply_all_my_product_automata(aut_list):
    cur_aut = aut_list[0]
    assert cur_aut is not None
    for i in range(1,len(aut_list)):
        assert cur_aut is not None
        assert aut_list[i] is not None
        cur_aut = spot.product(cur_aut,aut_list[i]).postprocess()
        #cur_aut = my_simplify_aut(my_product_automata(cur_aut,aut_list[i]))
    return cur_aut

def extract_proxy(all_f_list,all_shift_step_list,all_sign_list,template_groups,all_constraint_aut):
    #for each group of templates, extract proxy, then conjunct the proxies and the constraints.
    #extract proxy of a group by taking any template and any column in the group
    proxy_list = [[] for j in range(len(all_f_list[0]))]
    proxy_sign_list = [[] for j in range(len(all_f_list[0]))]
    proxy_start_step_list = [[] for j in range(len(all_f_list[0]))]
    for group in template_groups:
        for j in range(len(all_f_list[0])):
            select_template_idx = group[0] #proxy is arbtriarily chosen as first template in the group
            proxy_sign = all_sign_list[select_template_idx][j]
            proxy = all_f_list[select_template_idx][j]
            proxy_start_step = np.max(all_shift_step_list) - all_shift_step_list[select_template_idx][j]
            proxy_list[j].append(f"({proxy})")
            proxy_sign_list[j].append(proxy_sign)
            proxy_start_step_list[j].append(proxy_start_step)
    
    #normalize each proxy so that don't need to save every sign and start step
    norm_proxy_list = [[] for j in range(len(all_f_list[0]))]
    norm_proxy_start_step_list = []
    for j in range(len(proxy_list)):
        #cur_start_step = np.max(proxy_start_step_list[j])
        cur_start_step = np.max(all_shift_step_list)
        for k in range(len(proxy_list[j])):
            norm_proxy = f"({' X '*(cur_start_step - proxy_start_step_list[j][k])} ({proxy_list[j][k]}))"
            if not proxy_sign_list[j][k]:
                norm_proxy = f"!({norm_proxy})"
            norm_proxy_list[j].append(norm_proxy)
        norm_proxy_start_step_list.append(cur_start_step)
    return norm_proxy_list, norm_proxy_start_step_list

def get_init_aut(all_f_list,all_shift_step_list,all_sign_list,universal_var_names):
    nontrivial_f_list = get_nontrivial_constraint_per_template(all_f_list,all_shift_step_list,all_sign_list,universal_var_names)
    cur_aut_list = []
    for f in nontrivial_f_list:
        cur_aut = spot.translate(f,"sbacc","deterministic")
        assert spot.are_equivalent(cur_aut,f)
        cur_aut = get_aut_shannon_expansion(cur_aut,universal_var_names)
        cur_aut_list.append(cur_aut)
    init_aut = apply_all_my_product_automata(cur_aut_list)
    return init_aut

def inner_search(all_f_list,all_shift_step_list,all_sign_list,universal_var_names,aut_cache):
    covered_set = set()
    template_groups = []
    aut_per_group = []
    #while haven't found valid proxy for all templates
    #keep conjuncting proxies on conflicting templates
    while len(covered_set) < len(all_f_list): 
        #first prioritize finding proxies for templates have not found proxy for
        possible_idx = [idx for idx in range(len(all_f_list)) if idx not in covered_set]
        for idx in range(len(all_f_list)):
            if idx not in possible_idx:
                possible_idx.append(idx)
        #find proxy that covers maximal amount of templates
        cur_template_idx = [possible_idx[0]]
        cur_all_f_list = [all_f_list[idx] for idx in cur_template_idx]
        cur_all_shift_step_list = [all_shift_step_list[idx] for idx in cur_template_idx]
        cur_all_sign_list = [all_sign_list[idx] for idx in cur_template_idx]
        init_aut = get_init_aut(cur_all_f_list,cur_all_shift_step_list,cur_all_sign_list,universal_var_names)
        #init_aut = spot.translate("F r1")
        final_comb_aut = None
        #final_comb_aut = init_aut
        for idx in possible_idx[1:]:
            cur_template_idx.append(idx)
            cur_all_f_list = [all_f_list[idx] for idx in cur_template_idx]
            cur_all_shift_step_list = [all_shift_step_list[idx] for idx in cur_template_idx]
            cur_all_sign_list = [all_sign_list[idx] for idx in cur_template_idx]
     
            constraint_f_list = get_proxy_constraint_list(cur_all_f_list,cur_all_shift_step_list,cur_all_sign_list)
            
            cur_aut_list = get_reduce_and_simplify_all(constraint_f_list,universal_var_names,init_aut,cache=aut_cache)
            cur_aut_list.append(init_aut)
            cur_aut_list += aut_per_group
            comb_aut = apply_all_my_product_automata(cur_aut_list)
            if comb_aut.accepting_run() is None:
                cur_template_idx.pop()
            else:
                final_comb_aut = comb_aut

        assert final_comb_aut is None or final_comb_aut.accepting_run() is not None
        if final_comb_aut is None:
            return None, None, None, None
        for idx in cur_template_idx:
            covered_set.add(idx)
        template_groups.append(cur_template_idx)
        aut_per_group.append(final_comb_aut)
    print("success groups:",template_groups,len(all_f_list[0]))
    all_constraint_aut = apply_all_my_product_automata(aut_per_group)
    #extract proxies and combine constraints
    norm_proxy_list, norm_proxy_start_step_list = extract_proxy(all_f_list,all_shift_step_list,all_sign_list,template_groups,all_constraint_aut)
    for j in range(len(norm_proxy_list)):
        pos_proxy = " & ".join(norm_proxy_list[j])
        pos_aut = spot.translate(pos_proxy,'deterministic','sbacc')
        assert spot.are_equivalent(pos_aut,pos_proxy)
        pos_aut = get_aut_shannon_expansion(pos_aut,universal_var_names)
        all_constraint_aut = spot.product(all_constraint_aut,pos_aut).postprocess('deterministic','sbacc')
        neg_proxy = " & ".join([f"!({entry})" for entry in norm_proxy_list[j]])
        neg_aut = spot.translate(neg_proxy,'deterministic','sbacc')
        assert spot.are_equivalent(neg_aut,neg_proxy)
        neg_aut = get_aut_shannon_expansion(neg_aut,universal_var_names)
        all_constraint_aut = spot.product(all_constraint_aut,neg_aut).postprocess('deterministic','sbacc')
    #verify_proxies(all_f_list,all_shift_step_list,all_sign_list,norm_proxy_list, norm_proxy_start_step_list, all_constraint_aut)
    return norm_proxy_list, norm_proxy_start_step_list, template_groups, all_constraint_aut

def verify_proxies(all_f_list,all_shift_step_list,all_sign_list,norm_proxy_list, norm_proxy_start_step_list, all_constraint_aut,return_j_idx=False):
    bmc_k=None
    
    if norm_proxy_list is None:
        return False if not return_j_idx else -1
        
    if all_constraint_aut.accepting_run() is None:
        return False if not return_j_idx else -1

    all_var_dict = {}
    for i in range(len(all_f_list)):
        for j in range(len(all_f_list[i])):
            all_var_dict.update(dict((k,"boolean") for k in spot_utils.get_variables_from_formula(all_f_list[i][j])))
            
    trace_f = spot_utils.trace_to_formula(spot.split_edges(all_constraint_aut),debug=False)
    #trace_f = spot_utils.trace_to_formula(spot.split_edges(tmp_aut),debug=False)
    for j in tqdm(range(len(norm_proxy_list))):
        for i in range(len(all_f_list)):
            pos_proxy = " & ".join(norm_proxy_list[j])
            pos_polarity = "" if all_sign_list[i][j] else "!"
            cur_check_f = f"({pos_proxy}) & ({trace_f})"
            #cur_var_dict = dict((k,"boolean") for k in spot_utils.get_variables_from_formula(cur_check_f))
            #if spot_utils.check_satisfiable(cur_check_f) is None:
            if nusmv_utils.get_nusmv_ltl_satisfiable(all_var_dict,cur_check_f,bmc_k=bmc_k) is None:
                return False if not return_j_idx else j
            cur_check_f = f"({trace_f}) -> (({pos_proxy}) -> {pos_polarity} {' X '*(all_shift_step_list[i][j])} ({all_f_list[i][j]}))"
            #if not spot.are_equivalent(cur_check_f,"1"):
            if not nusmv_utils.get_nusmv_ltl_equivalent(all_var_dict,cur_check_f,all_var_dict,"TRUE",bmc_k=bmc_k):
                return False if not return_j_idx else j

            neg_proxy = " & ".join([f"!({entry})" for entry in norm_proxy_list[j]])
            neg_polarity = "!" if all_sign_list[i][j] else ""
            cur_check_f = f"({neg_proxy}) & ({trace_f})"
            #cur_var_dict = dict((k,"boolean") for k in spot_utils.get_variables_from_formula(cur_check_f))
            #if spot_utils.check_satisfiable(cur_check_f) is None:
            if nusmv_utils.get_nusmv_ltl_satisfiable(all_var_dict,cur_check_f,bmc_k=bmc_k) is None:
                return False if not return_j_idx else j
            cur_check_f = f"({trace_f}) -> (({neg_proxy}) -> {neg_polarity} {' X '*(all_shift_step_list[i][j])} ({all_f_list[i][j]}))"
            #if not spot.are_equivalent(cur_check_f,"1"):
            if not nusmv_utils.get_nusmv_ltl_equivalent(all_var_dict,cur_check_f,all_var_dict,"TRUE",bmc_k=bmc_k):
                return False if not return_j_idx else j
    """
    for j in range(len(norm_proxy_list)):
        for i in range(len(all_f_list)):
            pos_proxy = " & ".join(norm_proxy_list[j])
            pos_polarity = "" if all_sign_list[i][j] else "!"
            if spot.product(all_constraint_aut,spot.translate(pos_proxy)).accepting_run() is None:
                return False if not return_j_idx else j
            if not spot.translate(f"(({pos_proxy}) -> {pos_polarity} {' X '*(all_shift_step_list[i][j])} ({all_f_list[i][j]}))").contains(all_constraint_aut):
                return False if not return_j_idx else j

            neg_proxy = " & ".join([f"!({entry})" for entry in norm_proxy_list[j]])
            neg_polarity = "!" if all_sign_list[i][j] else ""
            if spot.product(all_constraint_aut,spot.translate(neg_proxy)).accepting_run() is None:
                return False if not return_j_idx else j
            if not spot.translate(f"(({neg_proxy}) -> {neg_polarity} {' X '*(all_shift_step_list[i][j])} ({all_f_list[i][j]}))").contains(all_constraint_aut):
                return False if not return_j_idx else j
    """
    return True if not return_j_idx else None

def simplify_proxies(proxy_list, proxy_start_step_list, all_constraint_aut):
    new_proxy_list = []
    for j in range(len(proxy_list)):
        new_proxy_list.append([])
        for k in range(len(proxy_list[j])):
            found_equivalent = False
            for proxy in new_proxy_list[-1]:
                if spot.contains(f"({proxy_list[j][k]}) <-> ({proxy})",all_constraint_aut):
                    found_equivalent = True
                    break
            if not found_equivalent:
                new_proxy_list[-1].append(proxy_list[j][k])
    return new_proxy_list

def check_template_param(all_f_list,template_shift_step_list,template_sign_list,universal_var_names,aut_cache,only_check_last=False):        
    cur_all_shift_step_list = [[template_shift_step_list[i] for j in range(len(all_f_list[i]))] for i in range(len(all_f_list))]
    cur_all_sign_list = [[template_sign_list[i] for j in range(len(all_f_list[i]))] for i in range(len(all_f_list))]
    proxy_list, proxy_start_step_list, template_groups, all_constraint_aut = inner_search(
                all_f_list,cur_all_shift_step_list,cur_all_sign_list,universal_var_names,aut_cache
    )
    if verify_proxies(all_f_list,cur_all_shift_step_list,cur_all_sign_list, proxy_list, proxy_start_step_list, all_constraint_aut):
        print("proxy pass!",template_groups)
        return proxy_list, proxy_start_step_list, template_groups, all_constraint_aut
    else:
        return None

def reduce_labels_by_shannon(cur_f,universal_var_names):
    if spot.are_equivalent(cur_f,"1"):
        cur_aut = spot.translate("1",'deterministic','sbacc')
    else:
        cur_aut = spot.translate(f"!({cur_f})",'deterministic','sbacc')
        cur_aut = spot.complement(get_aut_shannon_expansion(cur_aut,universal_var_names))
    return cur_aut

def reduce_wrapper(cur_f,universal_var_names):
    """
    cur_aut = spot.translate(cur_f,'coBuchi','deterministic','sbacc')
    try:
        assert spot.are_equivalent(cur_f,cur_aut)
        cur_aut = spot.remove_alternation(reduce_labels(cur_aut,universal_var_names))
    except:
        cur_aut = reduce_labels_by_shannon(cur_f,universal_var_names)
    test_aut = reduce_labels_by_shannon(cur_f,universal_var_names).postprocess()
    assert spot.are_equivalent(cur_aut,test_aut)
    return cur_aut
    """
    return reduce_labels_by_shannon(cur_f,universal_var_names)

def outer_param_search(all_f_list,universal_var_names,max_shift=0,aut_cache={},prev_param_solutions=None):
    if prev_param_solutions is None or len(prev_param_solutions) == 0:
        template_sign_list = [True] + [None for entry in range(len(all_f_list)-1)]
        template_shift_step_list = [0] + [None for entry in range(len(all_f_list)-1)]
        work_set = [(template_sign_list.copy(),template_shift_step_list.copy())]
    else:
        work_set = prev_param_solutions
    param_solutions = []
    proxy_solutions = []
    while len(work_set) > 0:
        template_sign_list,template_shift_step_list = work_set.pop()
        cur_possible_idx = [i for i in range(len(all_f_list)) if template_sign_list[i] is None]
        if len(cur_possible_idx) == 0:
            proxy_proof = check_template_param(all_f_list,template_shift_step_list,template_sign_list,universal_var_names,aut_cache,only_check_last=True)
            param_solutions.append((template_sign_list,template_shift_step_list))
            proxy_solutions.append(proxy_proof)
        for idx in cur_possible_idx:
            cur_idx_list = [i for i in range(len(template_sign_list)) if template_sign_list[i] is not None]
            cur_all_f_list = [all_f_list[i] for i in cur_idx_list] + [ all_f_list[idx] ]
            found_solution = False
            for new_sign,new_shift_step in itertools.product([False,True],[shift for shift in range(max_shift+1)]):
                cur_template_sign_list = [template_sign_list[i] for i in cur_idx_list] + [new_sign]
                cur_template_shift_step_list = [template_shift_step_list[i] for i in cur_idx_list] + [new_shift_step]
                proxy_proof = check_template_param(cur_all_f_list,cur_template_shift_step_list,cur_template_sign_list,universal_var_names,aut_cache,only_check_last=True)
                if proxy_proof is not None:    
                    template_sign_list[idx] = new_sign
                    template_shift_step_list[idx] = new_shift_step
                    work_set.append((template_sign_list.copy(),template_shift_step_list.copy()))
                    found_solution = True
                    break #TODO remove?
            if found_solution:
                #TODO remove?
                break
            for new_sign,new_shift_step in itertools.product([False,True],[shift for shift in range(1,max_shift+1-max([template_shift_step_list[i] for i in cur_idx_list]))]):
                cur_template_sign_list = [template_sign_list[i] for i in cur_idx_list] + [new_sign]
                cur_template_shift_step_list = [template_shift_step_list[i]+new_shift_step for i in cur_idx_list] + [0]
                proxy_proof = check_template_param(cur_all_f_list,cur_template_shift_step_list,cur_template_sign_list,universal_var_names,aut_cache,only_check_last=True)              
                if proxy_proof is not None:    
                    template_sign_list[idx] = new_sign
                    new_template_shift_step_list = [template_shift_step_list[i]+new_shift_step if i in cur_idx_list else None for i in range(len(all_f_list))]
                    new_template_shift_step_list[idx] = 0
                    work_set.append((template_sign_list.copy(),new_template_shift_step_list.copy()))
                    found_solution = True
                    break #TODO remove?
            if found_solution:
                break
        if len(cur_possible_idx) > 1 and not found_solution:
            idx = template_sign_list.index(None)
            for new_sign,new_shift_step in itertools.product([False,True],[shift for shift in range(max_shift+1)]):
                template_sign_list[idx] = new_sign
                template_shift_step_list[idx] = new_shift_step
                work_set.append((template_sign_list.copy(),template_shift_step_list.copy()))
    return param_solutions, proxy_solutions

def top_proxy_search(all_f_list,universal_var_names):
    aut_cache = {}
    max_shift = 1
    param_solution_list, proxy_solution_list = [], []
    j_idx_order = np.argsort([max([len(spot_utils.get_variables_from_formula(all_f_list[i][j])) for i in range(len(all_f_list))]) for j in range(len(all_f_list[0]))])
    next_j_idx = j_idx_order[0]
    cur_j_idx = []
    for num_j in tqdm(range(1,len(all_f_list[0])+1)):
        if next_j_idx != -1 and next_j_idx not in cur_j_idx:
            cur_j_idx.append(next_j_idx)
        else:
            for j in range(len(all_f_list[0])):
                if j not in cur_j_idx:
                    cur_j_idx.append(j)
                    break

        cur_all_f_list = [[all_f_list[i][j] for j in cur_j_idx] for i in range(len(all_f_list))]
        param_solution_list, proxy_solution_list = outer_param_search(cur_all_f_list,universal_var_names,max_shift=max_shift,aut_cache=aut_cache,prev_param_solutions=param_solution_list)
        for sol_idx in range(len(proxy_solution_list)):
            cur_param_solution, cur_proxy_solution = param_solution_list[sol_idx], proxy_solution_list[sol_idx]
            if cur_proxy_solution is None:
                print("no solution!",cur_j_idx)
                continue
            proxy_list, proxy_start_step_list, template_groups, all_constraint_aut = cur_proxy_solution
            template_sign_list,template_shift_step_list = cur_param_solution
            all_shift_step_list = [[template_shift_step_list[i] for j in range(len(all_f_list[i]))] for i in range(len(all_f_list))]
            all_sign_list = [[template_sign_list[i] for j in range(len(all_f_list[i]))] for i in range(len(all_f_list))]            
            proxy_list, proxy_start_step_list = extract_proxy(all_f_list,all_shift_step_list,all_sign_list,template_groups,all_constraint_aut)
            print("start verify proxy!")
            next_j_idx = verify_proxies(all_f_list,all_shift_step_list,all_sign_list, proxy_list, proxy_start_step_list, all_constraint_aut,return_j_idx=True)
            print("finish verify proxy!")
            if next_j_idx is None:
                print("verified!",cur_j_idx)
                #new_proxy_list = simplify_proxies(proxy_list, proxy_start_step_list, all_constraint_aut)
                new_proxy_list = proxy_list
                return all_f_list, all_shift_step_list, all_sign_list, new_proxy_list, proxy_start_step_list, all_constraint_aut

    return None

def get_dest_list(aut,dst):
    if not aut.is_univ_dest(dst):
        return [dst]
    
    else:
        return [i for i in aut.univ_dests(dst)]

def my_product_automata(aut1,aut2):
    assert aut1.get_acceptance() == "Fin(0)"
    assert aut2.get_acceptance() == "Fin(0)"
    assert aut1.prop_state_acc()
    assert aut2.prop_state_acc()
    
    o_aut = my_copy_aut(aut1)
    
    o_aut.copy_ap_of(aut2)

    o_aut.new_states(aut2.num_states())
    o_aut.set_univ_init_state(get_dest_list(aut1,aut1.get_init_state_number())+[aut1.num_states()+dst for dst in get_dest_list(aut2,aut2.get_init_state_number())])
    for s_aut2 in range(aut2.num_states()):
        for e in aut2.out(s_aut2):
            o_aut.new_univ_edge(aut1.num_states()+e.src, [aut1.num_states()+dst for dst in get_dest_list(aut2,e.dst)], e.cond, e.acc)
    return o_aut


