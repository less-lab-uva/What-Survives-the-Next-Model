import spot
from batch_check import *

def get_all_metrics(ltl_list,label_ltl_list,equal_only=False,timeout=None,is_parallel=False,nusmv_jobs_per_thread=1,bmc_k=None):
    #timeout_ltl_idx = set(random.sample(range(len(ltl_list)), 1))
    #timeout_label_idx = set(random.sample(range(len(label_ltl_list)), 50))
    timeout_ltl_idx = determine_timeout_idx(ltl_list)
    timeout_label_idx = determine_timeout_idx(label_ltl_list)
    ltl_aut_list = [spot.translate(ltl_list[i]) if i not in timeout_ltl_idx else None for i in range(len(ltl_list))]
    label_aut_list = [spot.translate(label_ltl_list[i]) if i not in timeout_label_idx else None for i in range(len(label_ltl_list))]
    spot_results = []
    nusmv_jobs = []
    for i in tqdm(range(len(ltl_list))):
        for j in range(len(label_ltl_list)):
            if i not in timeout_ltl_idx and j not in timeout_label_idx:
                spot_results.append(spot.contains(label_aut_list[j],ltl_aut_list[i]) and spot.contains(ltl_aut_list[i],label_aut_list[j]))
                if not equal_only:
                    spot_results.append(spot.contains(label_aut_list[j],ltl_aut_list[i]))
                    spot_results.append(spot.contains(ltl_aut_list[i],label_aut_list[j]))
                    spot_results.append(spot.product(ltl_aut_list[i],label_aut_list[j]).accepting_run() is not None)
            else:
                nusmv_jobs.append(("equivalence",(ltl_list[i],label_ltl_list[j])))
                if not equal_only:
                    nusmv_jobs.append(("subset",(ltl_list[i],label_ltl_list[j])))
                    nusmv_jobs.append(("superset",(ltl_list[i],label_ltl_list[j])))
                    nusmv_jobs.append(("overlap",(ltl_list[i],label_ltl_list[j])))

    print(len(nusmv_jobs))
    if not is_parallel:
        nusmv_results = dispatch_batch_MC(nusmv_jobs,spot_timeout=0,nusmv_timeout=timeout,nusmv_jobs_per_thread=nusmv_jobs_per_thread,bmc_k=bmc_k)
    else:
        nusmv_results = parallel_dispatch_batch_MC(nusmv_jobs,
                                             jobs_per_thread=len(nusmv_jobs)//10,
                                             spot_timeout=0,
                                             nusmv_timeout=timeout,
                                             nusmv_jobs_per_thread=nusmv_jobs_per_thread,
                                             bmc_k=bmc_k)
    assert len(nusmv_results) == len(nusmv_jobs)   
    res_list = []
    nusmv_res_idx = 0
    spot_res_idx = 0
    for i in range(len(ltl_list)):
        cur_equiv_results = []
        cur_subset_results = []
        cur_superset_results = []
        cur_overlap_results = []
        for j in range(len(label_ltl_list)):
            if i not in timeout_ltl_idx and j not in timeout_label_idx:
                cur_equiv_results.append(spot_results[spot_res_idx])
                spot_res_idx += 1
                if not equal_only:
                    cur_subset_results.append(spot_results[spot_res_idx])
                    spot_res_idx += 1
                    cur_superset_results.append(spot_results[spot_res_idx])
                    spot_res_idx += 1
                    cur_overlap_results.append(spot_results[spot_res_idx])
                    spot_res_idx += 1
            else:
                cur_equiv_results.append(nusmv_results[nusmv_res_idx])
                nusmv_res_idx += 1
                if not equal_only:
                    cur_subset_results.append(nusmv_results[nusmv_res_idx])
                    nusmv_res_idx += 1
                    cur_superset_results.append(nusmv_results[nusmv_res_idx])
                    nusmv_res_idx += 1
                    cur_overlap_results.append(nusmv_results[nusmv_res_idx])
                    nusmv_res_idx += 1
        is_equal = any(cur_equiv_results)
        if not equal_only:
            is_subset = any(cur_subset_results)
            is_superset = any(cur_superset_results)
            is_overlap = any(cur_overlap_results)
            res_list.append([is_equal,is_subset,is_superset,is_subset and is_superset,is_overlap])
        else:
            res_list.append([is_equal])
    assert nusmv_res_idx == len(nusmv_jobs)
    if equal_only:
        assert spot_res_idx == len(ltl_list)*len(label_ltl_list) - len(nusmv_jobs)
    else:
        assert spot_res_idx == 4*len(ltl_list)*len(label_ltl_list) - len(nusmv_jobs)
    return res_list

def get_all_metrics_old(ltl_list,label_ltl_list,equal_only=False,timeout=None,bmc_k=None):
    all_jobs = []
    for i in tqdm(range(len(ltl_list))):
        for f in label_ltl_list:
            all_jobs.append(("equivalence",(ltl_list[i],f)))
        if not equal_only:
            for f in label_ltl_list:
                all_jobs.append(("subset",(ltl_list[i],f)))
            for f in label_ltl_list:
                all_jobs.append(("superset",(ltl_list[i],f)))
            for f in label_ltl_list:
                all_jobs.append(("overlap",(ltl_list[i],f)))
                                    
    #results = dispatch_batch_MC(all_jobs,spot_timeout=0,nusmv_timeout=1,nusmv_jobs_per_thread=len(label_ltl_list))
    results = parallel_dispatch_batch_MC(all_jobs,
                                         jobs_per_thread=25,
                                         spot_timeout=0.5,
                                         nusmv_timeout=timeout,
                                         nusmv_jobs_per_thread=1,
                                         bmc_k=bmc_k)

    res_idx = 0
    res_list = []
    for i in range(len(ltl_list)):
        is_equal = any(results[res_idx:res_idx+len(label_ltl_list)])
        res_idx += len(label_ltl_list)
        if not equal_only:
            is_subset = any(results[res_idx:res_idx+len(label_ltl_list)])
            res_idx += len(label_ltl_list)
            is_superset = any(results[res_idx:res_idx+len(label_ltl_list)])
            res_idx += len(label_ltl_list)
            is_overlap = any(results[res_idx:res_idx+len(label_ltl_list)])
            res_idx += len(label_ltl_list)
            res_list.append([is_equal,is_subset,is_superset,is_subset and is_superset,is_overlap])
        else:
            res_list.append([is_equal])
    return res_list

def get_coverage_metric(ltl_list,group_label_ltl_list):
    res_list = []
    aut_list = [spot.translate(entry) for entry in ltl_list]
    label_aut_list = [[spot.translate(entry) for entry in lst] for lst in group_label_ltl_list]
    for i in range(len(group_label_ltl_list)):
        is_equal = any(spot.are_equivalent(aut,label_aut) for aut,label_aut in itertools.product(aut_list,label_aut_list[i]))
        res_list.append([is_equal])
    return res_list