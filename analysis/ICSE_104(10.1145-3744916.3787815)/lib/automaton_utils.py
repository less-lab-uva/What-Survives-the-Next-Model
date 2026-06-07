import spot

def get_dest_list(aut,dst):
    if not aut.is_univ_dest(dst):
        return [dst]
    
    else:
        return [i for i in aut.univ_dests(dst)]

def get_aut_num_steps(in_aut,max_steps):
    if max_steps is None:
        return in_aut
    in_aut = in_aut.postprocess('det')
    bdict = in_aut.get_dict()
    aut = spot.make_twa_graph(bdict)
    aut.copy_ap_of(in_aut)
    aut.set_acceptance(in_aut.num_sets(),in_aut.get_acceptance())
    aut.prop_state_acc(in_aut.prop_state_acc())

    save_set = set()
    work_list = [ (entry,0) for entry in get_dest_list(in_aut,in_aut.get_init_state_number())]
    while len(work_list) > 0:
        cur_node,cur_depth = work_list.pop()
        save_set.add(cur_node)
        if cur_depth < max_steps:
            for e in in_aut.out(cur_node):
                for dst in get_dest_list(in_aut,e.dst):
                    if dst not in save_set:
                        work_list.append((dst,cur_depth+1))
    
    out_to_in_state = list(save_set)
    in_to_out_state = dict((out_to_in_state[i],i) for i in range(len(out_to_in_state)))
    
    aut.new_states(len(in_to_out_state))
    aut.set_univ_init_state([in_to_out_state[idx] for idx in get_dest_list(in_aut,in_aut.get_init_state_number())])
    for in_idx in in_to_out_state.keys():
        for e in in_aut.out(in_idx):
            new_dst_list = [in_to_out_state[idx] for idx in get_dest_list(in_aut,e.dst) if idx in in_to_out_state]
            if len(new_dst_list) > 0:
                aut.new_univ_edge(in_to_out_state[e.src], new_dst_list, e.cond, e.acc)
    return aut
