# -*- coding: utf-8 -*-
"""
Common clustering functions and utilities.

Created on Fri Dec 16 14:14:30 2016

@author: mkonrad
"""

import itertools

import numpy as np

from pdftabextract.common import (fill_array_a_with_values_from_b, sorted_by_attr, flatten_list,
                                  DIRECTION_HORIZONTAL, DIRECTION_VERTICAL)


#%% Clustering

def find_clusters_1d_break_dist(vals, dist_thresh):
    """
    Very simple clusting in 1D: Sort <vals> and calculate distance between values. Form clusters when <dist_thresh> is
    exceeded.
    
    Returns a list if clusters, where each element in the list is a np.array with indices of <vals>.
    """
    if type(vals) is not np.ndarray:
        raise ValueError("vals must be a NumPy array")
    
    clusters = []
    
    if len(vals) > 0:
        pos_indices_sorted = np.argsort(vals)      # indices of sorted values
        gaps = np.diff(vals[pos_indices_sorted])   # calculate distance between sorted values
        
        cur_clust = [pos_indices_sorted[0]]  # initialize with first index
        
        if len(vals) > 1:
            for idx, gap in zip(pos_indices_sorted[1:], gaps):
                if gap >= dist_thresh:           # create new cluster
                    clusters.append(np.array(cur_clust))
                    cur_clust = []
                cur_clust.append(idx)
            
        clusters.append(np.array(cur_clust))
    
    assert len(vals) == sum(map(len, clusters))
    
    return clusters


#%% Cluster adjustment

def get_adjusted_cluster_centers(clusters, n_required_clusters, max_range_deviation,
                                 find_center_clusters_method, **kwargs):
    """
    From a dict containing clusters per page, find the cluster centers and apply some adjustments to them
    (filter bad values, interpolate missing values).
    
    Return the adjusted cluster centers in a dict with page number -> cluster center mapping.
    
    If parameter <return_center_clusters_diffsums> is True, additionally return a dict with summed differences between
    found centers and "model" centers as quality measure.
    <n_required_clusters> is the number of cluster centers (i.e. number of columns or lines) to be found.
    <max_range_deviation> is the maximum deviation of the centers range of a page from the median range.
    <find_center_clusters_method> is the clustering method to cluster aligned ("normalized") centers (<kwargs> will
    be passed to this function).
    <image_scaling> is an optional parameter: dict with page number -> <scaling> mapping with which the
    final centers for each page are calculated by <center> / <scaling>.
    """
    return_center_clusters_diffsums = kwargs.pop('return_center_clusters_diffsums', False)
    image_scaling = kwargs.pop('image_scaling', None)
    
    # 1. Filter for pages with clusters whose min/max range is acceptable
    # (i.e. the deviation from the median is below a certain threshold)
    all_clusters_centers_range = {}
    all_clusters_centers = {}
    for p_num, clusters_w_vals in clusters.items():
        all_clusters_centers_range[p_num], all_clusters_centers[p_num] = calc_cluster_centers_range(clusters_w_vals,
                                                                                                    return_centers=True)
    median_range = np.median(list(all_clusters_centers_range.values()))
    
    good_page_nums = [p_num for p_num, centers_range in all_clusters_centers_range.items()
                      if abs(centers_range - median_range) <= max_range_deviation]
    
    good_cluster_centers = {p_num: all_clusters_centers[p_num] for p_num in good_page_nums}
    
    # 2. Align the cluster centers so that they all start with 0 and create a flat list that contains all centers
    centers_norm = []
    for p_num, centers in good_cluster_centers.items():
        centers = np.array(centers)
        centers_norm.extend(centers - centers[0])
    
    centers_norm = np.array(centers_norm)

    # 3. Clustering second pass: Cluster aligned ("normalized") centers and filter them
    centers_norm_clusters_ind = find_center_clusters_method(centers_norm, **kwargs)
    centers_norm_clusters = zip_clusters_and_values(centers_norm_clusters_ind, centers_norm)
    
    center_norm_medians = []
    
    # Filter clusters: take only clusters with at least <min_n_values> inside. Decrease this value on each iteration.
    for min_n_values in range(len(good_page_nums), 0, -1):
        for _, vals in centers_norm_clusters:
            if len(vals) >= min_n_values:
                center_norm_medians.append(np.median(vals))
        
            if len(center_norm_medians) == n_required_clusters:
                break
        else:
            continue
        break
    
    assert len(center_norm_medians) == n_required_clusters
    
    center_norm_medians = np.array(sorted(center_norm_medians))

    # 4. Adjust the cluster centers by finding the best matching array to <center_norm_medians> if sizes differ
    adjusted_centers = {}
    diffsums = {} if return_center_clusters_diffsums else None
    for p_num, centers in all_clusters_centers.items():
        corrected_centers, diffsum = find_best_matching_array(np.array(centers), center_norm_medians)
        
        if image_scaling is not None:
            scaling_for_page = image_scaling[p_num]
            corrected_centers /= scaling_for_page
        
        adjusted_centers[p_num] = corrected_centers
        if return_center_clusters_diffsums:
            diffsums[p_num] = diffsum
    
    if return_center_clusters_diffsums:
        return adjusted_centers, diffsums
    else:
        return adjusted_centers
        
        
def merge_overlapping_sections(texts_in_secs, direction, overlap_thresh):
    """
    Merge overlapping sections of texts in <direction> whose consecutive
    "distance" or overlap (when the distance is negative) is less than <overlap_thresh>.
    """
    if direction not in (DIRECTION_HORIZONTAL, DIRECTION_VERTICAL):
        raise ValueError("direction must be  DIRECTION_HORIZONTAL or DIRECTION_VERTICAL (see pdftabextract.common)")
    
    if direction == DIRECTION_HORIZONTAL:
        pos_attr = 'left'
        other_pos_attr = 'right'
    else:
        pos_attr = 'top'
        other_pos_attr = 'bottom'    
    
    # sorted section positions for left side or top side
    sec_positions1 = [sorted_by_attr(sec, pos_attr, reverse=True)[0][pos_attr] for sec in texts_in_secs]
    # sorted section positions for right side or bottom side
    sec_positions2 = [sorted_by_attr(sec, other_pos_attr, reverse=True)[0][other_pos_attr] for sec in texts_in_secs]
    
    # calculate distance/overlap between sections
    sec_positions = list(zip(sec_positions1, sec_positions2))
    sec_dists = [pos[0] - sec_positions[i-1][1] if i > 0 else 0 for i, pos in enumerate(sec_positions)]
    #print(sum([d <= 0 for d in sec_dists]))
    
    # merge sections that overlap (whose distance is less than <overlap_thresh>)
    merged_secs = []
    prev_sec = []
    for i, dist in enumerate(sec_dists):
        cur_sec = texts_in_secs[i]
        if dist < overlap_thresh:
            sec = cur_sec + prev_sec
            if len(merged_secs) > 0:
                merged_secs.pop()
        else:
            sec = cur_sec
        
        merged_secs.append(sec)
        prev_sec = sec
    
    assert len(flatten_list(texts_in_secs)) == len(flatten_list(merged_secs))
    
    return merged_secs


def merge_small_sections(texts_in_secs, min_num_texts):
    """
    Merge sections that are too small, i.e. have too few "content" which means that their number
    of texts is lower than or equal <min_num_texts>.
    """
    merged_secs = []
    prev_sec = None
    for cur_sec in texts_in_secs:
        if prev_sec:
            if len(cur_sec) <= min_num_texts:  # number of texts is too low
                sec = cur_sec + prev_sec       # merge this section with the previous section
                if len(merged_secs) > 0:       # remove the prev. section from the final list
                    merged_secs.pop()          # in order to add the merged section later
            else:
                sec = cur_sec
        else:
            sec = cur_sec
        
        merged_secs.append(sec)   # add the (possibly merged) section
        prev_sec = sec

    assert len(flatten_list(texts_in_secs)) == len(flatten_list(merged_secs))

    return merged_secs


#%% Helper functions
    
def zip_clusters_and_values(clusters, values):
    """
    Combine cluster indices in <clusters> (as returned from find_clusters_1d_break_dist) with the respective values
    in <values>.
    Return list of tuples, each tuple representing a cluster and containing two NumPy arrays:
    1. cluster indices into <values>, 2. values of this cluster
    """
    clusters_w_vals = []
    for c_ind in clusters:
        c_vals = values[c_ind]
        clusters_w_vals.append((c_ind, c_vals))
    
    return clusters_w_vals


def calc_cluster_centers_1d(clusters_w_vals, method=np.median):
    """
    Calculate the cluster centers (for 1D clusters) using <method>.
    <clusters_w_vals> must be a sequence of tuples t where t[1] contains the values (as returned from
    zip_clusters_and_values).
    """
    return [method(vals) for _, vals in clusters_w_vals]

    
def calc_cluster_centers_range(clusters_w_vals, reduce_clusters_method=np.median, return_centers=False):
    """
    Calculate the cluster centers of <clusters_w_vals> using calc_cluster_centers_1d and return their range, i.e.
    max(centers) - min(centers).
    Optionally return also the centers.
    """
    centers = calc_cluster_centers_1d(clusters_w_vals, method=reduce_clusters_method)
    rng = max(centers) - min(centers)
    if return_centers:
        return rng, centers
    else:
        return rng

        
def array_match_difference_1d(a, b):
    """Return the summed difference between the elements in a and b."""
    if len(a) != len(b):
        raise ValueError('Both arrays must have the same length')
    
    if len(a) == 0:
        raise ValueError('Arrays must be filled')
    
    if type(a) is not np.ndarray:
        a = np.array(a)
    if type(b) is not np.ndarray:
        b = np.array(b)
    
    return np.sum(np.abs(a - b))
    

def find_best_matching_array(base_arr, model_arr):
    """
    Find an array <best_arr> based on <base_arr> that fits best to <model_arr> if their sizes differ.
    <best_arr> will have the same size as <model_arr> and either has surplus elements removed (if <base_arr> is
    bigger than <model_arr>) or missing elements added from <model_arr> (if <base_arr> is smaller than <model_arr>).
    
    Returns the best fitting array and the summed difference of this array and <model_arr>.
    
    It uses a brute force method so this is slow for big arrays.
    
    Example:
        
    values = [
        [0,  10,     30,         40],
        [0,  11,     29,         42],
        [10, 21, 25, 39,         52],
        [0,   9, 15, 29, 32,     41],
        [0,  10,     29, 35, 36, 40],
        [0,   9,                 41],
        [0,          33,           ],
    ]
    
    model = np.array(values[0])  # first row is the "model" -> we know that this is correct
    for row in values[1:]:
        row = np.array(row)
        print(row)
        corrected_row, diffsum = find_best_matching_array(row, model)
        print(corrected_row)
        print(diffsum)
        print()

    Output:
        [ 0 11 29 42]
        [ 0 11 29 42]
        4
        
        [10 21 25 39 52]
        [10 21 39 52]
        4
        
        [ 0  9 15 29 32 41]
        [ 0  9 29 41]
        3
        
        [ 0 10 29 35 36 40]
        [ 0 10 29 40]
        1
        
        [ 0  9 41]
        [ 0  9 30 41]
        2
        
        [ 0 33]
        [ 0 10 33 40]
        3
    """
    if type(base_arr) is not np.ndarray:
        raise TypeError("base_arr must be NumPy array")
    if type(model_arr) is not np.ndarray:
        raise TypeError("model_arr must be NumPy array")
    
    amount_diff = len(base_arr)  - len(model_arr)
    
    if amount_diff > 0:    # too many values in base_arr
        # go through all possible combinations of surplus elements in the base_arr and
        # measure the match difference and save it to "candidates"
        del_indices_combi = itertools.combinations(range(len(base_arr)), amount_diff)
        candidates = []
        for del_ind in del_indices_combi:
            candidate_arr = np.delete(base_arr, del_ind)
            # model_arr is normalized -> add first value as offset
            center_medians_w_offset = model_arr + candidate_arr[0]
            diff = array_match_difference_1d(candidate_arr, center_medians_w_offset)
            candidates.append((candidate_arr, diff))
        
        best_arr, diff = sorted(candidates, key=lambda x: x[1])[0]
    elif amount_diff < 0:  # too few values in base_arr
        # this time, reduce the model_arr so that it fits the number of values in base_arr
        # i.e. we find the best candidate of all adjusted model_arr first
        del_indices_combi = itertools.combinations(range(len(model_arr)), -amount_diff)
        candidates = []
        for del_ind in del_indices_combi:
            candidate_arr = np.delete(model_arr, del_ind)
            # model_arr is normalized -> add first value as offset
            diff = array_match_difference_1d(candidate_arr + base_arr[0], base_arr)
            candidates.append((del_ind, diff))
            
        add_ind, _ = sorted(candidates, key=lambda x: x[1])[0]
        model_arr_w_offset = model_arr + base_arr[0]
        
        # take the missing values from best_model_arr
        best_arr = fill_array_a_with_values_from_b(base_arr, model_arr_w_offset, add_ind)
        diff = array_match_difference_1d(best_arr, model_arr_w_offset)
    else:                  # number of values matches
        diff = array_match_difference_1d(base_arr, model_arr + base_arr[0])
        best_arr = base_arr
    
    return best_arr, diff


