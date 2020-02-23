# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import scipy.signal

from ..signal import (signal_zerocrossings,
                      signal_resample,
                      signal_detrend,
                      signal_smooth,
                      signal_filter,
                      signal_findpeaks,
                      signal_formatpeaks)
from .ecg_peaks import ecg_peaks
from ..epochs import epochs_create
from ..events import events_plot


def ecg_delineator(ecg_cleaned, rpeaks, sampling_rate=1000, method="derivative"):
    """Delineate QRS complex.
    Function to delineate the QRS complex.

    - **Cardiac Cycle**: A typical ECG heartbeat consists of a P wave, a QRS complex and a T wave.The P wave represents the wave of depolarization that spreads from the SA-node throughout the atria. The QRS complex reflects the rapid depolarization of the right and left ventricles. Since the ventricles are the largest part of the heart, in terms of mass, the QRS complex usually has a much larger amplitude than the P-wave. The T wave represents the ventricular repolarization of the ventricles. On rare occasions, a U wave can be seen following the T wave. The U wave is believed to be related to the last remnants of ventricular repolarization.

    Parameters
    ----------
    ecg : list, array or Series
        The raw ECG signal.
    rpeaks : list, array or Series
        The samples at which R-peaks occur. Accessible with the key "ECG_R_Peaks" in the info dictionary returned by `ecg_findpeaks()`.
    sampling_rate : int
        The sampling frequency of `ecg_signal` (in Hz, i.e., samples/second).
        Defaults to 500.

    Returns
    -------
    info : dict
        A dictionary containing additional information, in this case the
        samples at which P-peaks and T-peaks occur, accessible with the key "ECG_P_Peaks" and "ECG_R_Peaks" respectively.

    See Also
    --------
    ecg_clean, ecg_fixpeaks, ecg_peaks, ecg_rate, ecg_process, ecg_plot

    Examples
    --------
    >>> import neurokit2 as nk
    >>>
    >>> ecg = nk.ecg_simulate(duration=10, sampling_rate=500)
    >>> cleaned = nk.ecg_clean(ecg, sampling_rate=1000)
    >>> rpeaks = nk.ecg_findpeaks(cleaned)
    >>> info = nk.ecg_delineator(cleaned, rpeaks, sampling_rate=500)
    >>> nk.events_plot(info["ECG_P_Peaks"], cleaned)
    >>> nk.events_plot(info2["ECG_T_Peaks"], cleaned)

    References
    --------------
    - Martínez, J. P., Almeida, R., Olmos, S., Rocha, A. P., & Laguna, P. (2004). A wavelet-based ECG delineator: evaluation on standard databases. IEEE Transactions on biomedical engineering, 51(4), 570-581.

    """
    # Sanitize inputs
    if rpeaks is None:
        rpeaks = ecg_peaks(ecg_cleaned, sampling_rate=sampling_rate)["ECG_R_Peaks"]

    # Try retrieving right column
    if isinstance(rpeaks, dict):
        rpeaks = rpeaks["ECG_R_Peaks"]

    method = method.lower()  # remove capitalised letters
    if method in ["derivative", "gradient"]:
        waves = _ecg_delineator_derivative(ecg_cleaned,
                                           rpeaks=rpeaks,
                                           sampling_rate=sampling_rate)
    if method in ["cwt", "continuous wavelet transform"]:
        waves = _ecg_delinator_cwt(ecg_cleaned,
                                   rpeaks=rpeaks,
                                   sampling_rate=sampling_rate)
    if method in ["dwt", "discrete wavelet transform"]:
        waves = _ecg_delinator_dwt(ecg_cleaned,
                                   rpeaks,
                                   sampling_rate=sampling_rate)
    return waves


###############################################################################
#                             WAVELET METHOD (DWT)                             #
###############################################################################
def _resample_points(peaks, sampling_rate, desired_sampling_rate):
    return (np.array(peaks) * desired_sampling_rate / sampling_rate).astype(int)


def _ecg_delinator_dwt(ecg, rpeaks, sampling_rate):
    ecg = signal_resample(ecg, sampling_rate=sampling_rate, desired_sampling_rate=250)
    dwtmatr = compute_dwt_multiscales(ecg, 5)

    # for idx in [0, 1, 2, 3]:
    #     plt.plot(dwtmatr[idx], label=f'W[{idx}]')
    # plt.plot(ecg, '--')
    # plt.legend()
    # plt.grid(True)
    # plt.show()

    rpeaks_resampled = _resample_points(rpeaks, sampling_rate, 250)
    # rpeaks_resampled = (rpeaks * 250 / sampling_rate).astype(int)
    tpeaks, ppeaks = _dwt_delinate_tp_peaks(ecg, rpeaks_resampled, dwtmatr, sampling_rate=250, debug=False)

    # P-Peaks and T-Peaks
    # tpeaks, ppeaks = _peaks_delineator(ecg, rpeaks, sampling_rate=sampling_rate)
    return dict(
        ECG_T_Peaks=_resample_points(tpeaks, 250, desired_sampling_rate=sampling_rate),
        ECG_P_Peaks=_resample_points(ppeaks, 250, desired_sampling_rate=sampling_rate)
    )

    # return {"ECG_P_Peaks": ppeaks,
    #         "ECG_T_Peaks": tpeaks,
    #         "ECG_R_Onsets": qrs_onsets,
    #         "ECG_R_Offsets": qrs_offsets,
    #         "ECG_P_Onsets": p_onsets,
    #         "ECG_P_Offsets": p_offsets,
    #         "ECG_T_Onsets": t_onsets,
    #         "ECG_T_Offsets": t_offsets}


def _dwt_delinate_tp_peaks(ecg, rpeaks, dwtmatr, sampling_rate=250, debug=False, dwt_delay=0.0):
    qrs_duration = 0.05
    p_qrs_duration = 0.5
    srch_bndry = int(0.9 * qrs_duration * sampling_rate / 2)
    tpeaks = []
    ppeaks = []
    for i in range(len(rpeaks)-1):
        for find in ['tpeak', 'ppeak']:

            if find == 'tpeak':
                # search for T peaks from R peaks
                srch_idx_start = rpeaks[i] + srch_bndry
                srch_idx_end = rpeaks[i + 1] - srch_bndry * 6
                dwt_local = dwtmatr[3, srch_idx_start:srch_idx_end]
            elif find == 'ppeak':
                # search for P peaks from Rpeaks
                srch_idx_start = rpeaks[i] - int(p_qrs_duration * sampling_rate)
                srch_idx_end = rpeaks[i] - srch_bndry
                dwt_local = dwtmatr[2, srch_idx_start:srch_idx_end]

            height = 0.25*np.sqrt(np.mean(np.square(dwt_local)))
            peaks_tp, heights_tp = scipy.signal.find_peaks(np.abs(dwt_local), height=height)
            peaks_tp = [peaks_tp[j] for j in range(len(peaks_tp)) if heights_tp['peak_heights'][j]]

            peaks_tp = list(filter(lambda p: np.abs(dwt_local[p]) > 0.125 * max(dwt_local), peaks_tp))
            if dwt_local[0] > 0:  # just append
                peaks_tp = [0] + peaks_tp

            candidate_peaks = []
            for idx_peak, idx_peak_nxt in zip(peaks_tp[:-1], peaks_tp[1:]):
                correct_sign = dwt_local[idx_peak] > 0 and dwt_local[idx_peak_nxt] < 0
                if correct_sign:
                    idx_zero = signal_zerocrossings(dwt_local[idx_peak: idx_peak_nxt])[0] + idx_peak
                    # account for delay
                    candidate_peaks.append(idx_zero + int(dwt_delay * sampling_rate))

            # filtering? use a simple rule now
            if find == 'tpeak':
                if len(candidate_peaks) > 0:
                    tpeaks.append(candidate_peaks[0] + srch_idx_start)
                else:
                    tpeaks.append(np.nan)
            elif find == 'ppeak':
                if len(candidate_peaks) > 0:
                    ppeaks.append(candidate_peaks[0] + srch_idx_start)
                else:
                    ppeaks.append(np.nan)

            if debug:
                events_plot(candidate_peaks, dwt_local)
                plt.plot(ecg[srch_idx_start: srch_idx_end])
                plt.show()

    return tpeaks, ppeaks


def compute_dwt_multiscales(ecg: np.ndarray, max_degree):
    """Return multiscales wavelet transforms.

    Args:
        ecg (FIXME): FIXME
        max_degree (FIXME): FIXME

    Returns:
        out (FIXME): FIXME
    """
    def _apply_H_filter(signal_i, power=0):
        zeros = np.zeros(2 ** power - 1)
        timedelay = 2 ** power
        banks = np.r_[
            1.0 / 8, zeros, 3.0 / 8, zeros, 3.0 / 8, zeros, 1.0 / 8,
        ]
        signal_f = scipy.signal.convolve(signal_i, banks, mode='full')
        signal_f[:-timedelay] = signal_f[timedelay:]  # timeshift: 2 steps
        return signal_f

    def _apply_G_filter(signal_i, power=0):
        zeros = np.zeros(2 ** power - 1)
        timedelay = 2 ** power
        banks = np.r_[2, zeros, -2]
        signal_f = scipy.signal.convolve(signal_i, banks, mode='full')
        signal_f[:-timedelay] = signal_f[timedelay:]  # timeshift: 1 step
        return signal_f

    dwtmatr = []
    intermediate_ret = np.array(ecg)
    for deg in range(max_degree):
        S_deg = _apply_G_filter(intermediate_ret, power=deg)
        T_deg = _apply_H_filter(intermediate_ret, power=deg)
        dwtmatr.append(S_deg)
        intermediate_ret = np.array(T_deg)
    dwtmatr = [arr[:len(ecg)] for arr in dwtmatr]  # rescale transforms to the same length
    return np.array(dwtmatr)


# =============================================================================
# WAVELET METHOD
# =============================================================================
def _ecg_delinator_cwt(ecg, rpeaks=None, sampling_rate=1000):

    # P-Peaks and T-Peaks
    tpeaks, ppeaks = _peaks_delineator(ecg, rpeaks,
                                       sampling_rate=sampling_rate)

    # qrs onsets and offsets
    qrs_onsets, qrs_offsets = _onset_offset_delineator(ecg, rpeaks,
                                                       peak_type="rpeaks",
                                                       sampling_rate=sampling_rate)

    # ppeaks onsets and offsets
    p_onsets, p_offsets = _onset_offset_delineator(ecg, ppeaks,
                                                   peak_type="ppeaks",
                                                   sampling_rate=sampling_rate)

    # tpeaks onsets and offsets
    t_onsets, t_offsets = _onset_offset_delineator(ecg, tpeaks,
                                                   peak_type="tpeaks",
                                                   sampling_rate=sampling_rate)

    info = {"ECG_P_Peaks": ppeaks,
            "ECG_T_Peaks": tpeaks,
            "ECG_R_Onsets": qrs_onsets,
            "ECG_R_Offsets": qrs_offsets,
            "ECG_P_Onsets": p_onsets,
            "ECG_P_Offsets": p_offsets,
            "ECG_T_Onsets": t_onsets,
            "ECG_T_Offsets": t_offsets}
    return info

# Internals
# ---------------------

def _onset_offset_delineator(ecg, peaks, peak_type="rpeaks", sampling_rate=1000):
    # Try loading pywt
    try:
        import pywt
    except ImportError:
        raise ImportError("NeuroKit error: ecg_delineator(): the 'PyWavelets' "
                          "module is required for this method to run. ",
                          "Please install it first (`pip install PyWavelets`).")
    # first derivative of the Gaissian signal
    scales = np.array([1, 2, 4, 8, 16])
    cwtmatr, freqs = pywt.cwt(ecg, scales, 'gaus1', sampling_period=1.0/sampling_rate)

    half_wave_width = int(0.1*sampling_rate)  # NEED TO CHECK
    onsets = []
    offsets = []
    for index_peak in peaks:
        # find onset
        if peak_type == "rpeaks":
            search_window = cwtmatr[2, index_peak - half_wave_width: index_peak]
            prominence = 0.20*max(search_window)
            height = 0.0
            wt_peaks, wt_peaks_data = scipy.signal.find_peaks(search_window, height=height,
                                       prominence=prominence)

        elif peak_type == "tpeaks" or peak_type == "ppeaks":
            search_window = - cwtmatr[4, index_peak - half_wave_width: index_peak]

            prominence = 0.10*max(search_window)
            height = 0.0
            wt_peaks, wt_peaks_data = scipy.signal.find_peaks(search_window, height=height,
                                           prominence=prominence)

        if len(wt_peaks) == 0:
            print("Fail to find onset at index: %d", index_peak)
            continue
        # The last peak is nfirst in (Martinez, 2004)
        nfirst = wt_peaks[-1] + index_peak - half_wave_width
        if peak_type == "rpeaks":
            if wt_peaks_data['peak_heights'][-1] > 0:
                epsilon_onset = 0.05 * wt_peaks_data['peak_heights'][-1]
            elif wt_peaks_data['peak_heights'][-1] > 0:
                epsilon_onset = 0.07 * wt_peaks_data['peak_heights'][-1]
        elif peak_type == "ppeaks":
            epsilon_onset = 0.50 * wt_peaks_data['peak_heights'][-1]
        elif peak_type == "tpeaks":
            epsilon_onset = 0.25 * wt_peaks_data['peak_heights'][-1]
        leftbase = wt_peaks_data['left_bases'][-1] + index_peak - half_wave_width
        if peak_type == "rpeaks":
            candidate_onsets = np.where(cwtmatr[2, nfirst-100: nfirst] <
                                        epsilon_onset)[0] + nfirst - 100
        elif peak_type == "tpeaks" or peak_type == "ppeaks":
            candidate_onsets = np.where(-cwtmatr[4, nfirst-100: nfirst] <
                                        epsilon_onset)[0] + nfirst - 100

        candidate_onsets = candidate_onsets.tolist() + [leftbase]
        onsets.append(max(candidate_onsets))

        # find offset
        if peak_type == "rpeaks":
            search_window = - cwtmatr[2, index_peak: index_peak + half_wave_width]
            prominence = 0.50*max(search_window)
            wt_peaks, wt_peaks_data = scipy.signal.find_peaks(search_window, height=height,
                                                 prominence=prominence)

        elif peak_type == "tpeaks" or peak_type == "ppeaks":
            search_window = cwtmatr[4, index_peak: index_peak + half_wave_width]
            prominence = 0.10*max(search_window)
            wt_peaks, wt_peaks_data = scipy.signal.find_peaks(search_window, height=height,
                                           prominence=prominence)

        if len(wt_peaks) == 0:
            print("Fail to find offset at index: %d", index_peak)
            continue
        nlast = wt_peaks[0] + index_peak
        if peak_type == "rpeaks":
            if wt_peaks_data['peak_heights'][0] > 0:
                epsilon_offset = 0.125 * wt_peaks_data['peak_heights'][0]
            elif wt_peaks_data['peak_heights'][0] > 0:
                epsilon_offset = 0.71 * wt_peaks_data['peak_heights'][0]
        elif peak_type == "ppeaks":
            epsilon_offset = 0.9 * wt_peaks_data['peak_heights'][0]
        elif peak_type == "tpeaks":
            epsilon_offset = 0.4 * wt_peaks_data['peak_heights'][0]
        rightbase = wt_peaks_data['right_bases'][0] + index_peak
        if peak_type == "rpeaks":
            candidate_offsets = np.where((-cwtmatr[2, nlast: nlast + 100]) <
                                         epsilon_offset)[0] + nlast
        elif peak_type == "tpeaks" or peak_type == "ppeaks":
            candidate_offsets = np.where((cwtmatr[4, nlast: nlast + 100]) <
                                         epsilon_offset)[0] + nlast

        candidate_offsets = candidate_offsets.tolist() + [rightbase]
        offsets.append(min(candidate_offsets))

    return onsets, offsets



def _peaks_delineator(ecg, rpeaks, cleaning=False, sampling_rate=1000):
    # Try loading pywt
    try:
        import pywt
    except ImportError:
        raise ImportError("NeuroKit error: ecg_delineator(): the 'PyWavelets' "
                          "module is required for this method to run. ",
                          "Please install it first (`pip install PyWavelets`).")
    # first derivative of the Gaissian signal
    scales = np.array([1, 2, 4, 8, 16])
    cwtmatr, freqs = pywt.cwt(ecg, scales, 'gaus1', sampling_period=1.0/sampling_rate)

    qrs_duration = 0.1

    search_boundary = int(0.9 * qrs_duration * sampling_rate / 2)
    significant_peaks_groups = []
    tppeaks_pairs = []
    tppeaks = []
    for i in range(len(rpeaks)-1):
        # search for T peaks and P peaks from R peaks
        start = rpeaks[i] + search_boundary
        end = rpeaks[i + 1] - search_boundary
        search_window = cwtmatr[4, start:end]
        height = 0.25*np.sqrt(np.mean(np.square(search_window)))
        peaks_tp, heights_tp = scipy.signal.find_peaks(np.abs(search_window), height=height)
        peaks_tp = peaks_tp + rpeaks[i] + search_boundary
        # set threshold for heights of peaks to find significant peaks in wavelet
        threshold = 0.125*max(search_window)
        significant_index = []
        significant_index = [j for j in range(len(peaks_tp)) if
                             heights_tp["peak_heights"][j] > threshold]

        significant_peaks_tp = []
        for index in significant_index:
            significant_peaks_tp.append(peaks_tp[index])
        significant_peaks_groups.append(_find_tppeaks(ecg, significant_peaks_tp, sampling_rate=sampling_rate))

    tpeaks, ppeaks = zip(*[(g[0], g[-1]) for g in significant_peaks_groups])
    return tpeaks, ppeaks


def _find_tppeaks(ecg, keep_tp, sampling_rate=1000):
    # Try loading pywt
    try:
        import pywt
    except ImportError:
        raise ImportError("NeuroKit error: ecg_delineator(): the 'PyWavelets' "
                          "module is required for this method to run. ",
                          "Please install it first (`pip install PyWavelets`).")
    # first derivative of the Gaissian signal
    scales = np.array([1, 2, 4, 8, 16])
    cwtmatr, freqs = pywt.cwt(ecg, scales, 'gaus1', sampling_period=1.0/sampling_rate)
    max_search_duration = 0.05
    tppeaks = []
    for index_cur, index_next in zip(keep_tp[:-1], keep_tp[1:]):
        # limit 1
        correct_sign = cwtmatr[4, :][index_cur] < 0 and cwtmatr[4, :][index_next] > 0
    #    near = (index_next - index_cur) < max_wv_peak_dist #limit 2
    #    if near and correct_sign:
        if correct_sign:
            index_zero_cr = signal_zerocrossings(
                cwtmatr[4, :][index_cur:index_next])[0] + index_cur
            nb_idx = int(max_search_duration * sampling_rate)
            index_max = np.argmax(ecg[index_zero_cr - nb_idx: index_zero_cr + nb_idx]) + (index_zero_cr - nb_idx)
            tppeaks.append(index_max)
    return tppeaks

# =============================================================================
# Derivative Method
# =============================================================================
def _ecg_delineator_derivative(ecg, rpeaks=None, sampling_rate=1000):

    # Initialize
    heartbeats = epochs_create(ecg, rpeaks, sampling_rate=sampling_rate, epochs_start=-0.35, epochs_end=0.5)

    Q_list = []
    P_list = []
    S_list = []
    T_list = []

    P_onsets = []
    T_offsets = []

    for i, rpeak in enumerate(rpeaks):
        heartbeat = heartbeats[str(i+1)]

        # Get index of heartbeat
        R = heartbeat.index.get_loc(np.min(heartbeat.index.values[heartbeat.index.values > 0]))

        # Peaks ------
        # Q wave
        Q_index, Q = _ecg_delineator_derivative_Q(rpeak, heartbeat, R)
        Q_list.append(Q_index)

        # P wave
        P_index, P = _ecg_delineator_derivative_P(rpeak, heartbeat, R, Q)
        P_list.append(P_index)

        # S wave
        S_index, S = _ecg_delineator_derivative_S(rpeak, heartbeat, R)
        S_list.append(S_index)

        # T wave
        T_index, T = _ecg_delineator_derivative_T(rpeak, heartbeat, R, S)
        T_list.append(T_index)

        # Onsets/Offsets ------
        P_onsets.append(_ecg_delineator_derivative_P_onset(rpeak, heartbeat, R, P))
        T_offsets.append(_ecg_delineator_derivative_T_offset(rpeak, heartbeat, R, T))


    out = {"ECG_P_Peaks": P_list,
           "ECG_Q_Peaks": Q_list,
           "ECG_S_Peaks": S_list,
           "ECG_T_Peaks": T_list,
           "ECG_P_Onsets": P_onsets,
           "ECG_T_Offsets": T_offsets}

    return out


# Internal
# --------------------------

def _ecg_delineator_derivative_Q(rpeak, heartbeat, R):
    segment = heartbeat[:0]  # Select left hand side

    Q = signal_findpeaks(-1*segment["Signal"],
                            height_min=0.05 * (segment["Signal"].max() - segment["Signal"].min()))
    if len(Q["Peaks"]) == 0:
        return np.nan, None
    Q = Q["Peaks"][-1]  # Select most right-hand side
    from_R = R - Q  # Relative to R
    return rpeak - from_R, Q



def _ecg_delineator_derivative_P(rpeak, heartbeat, R, Q):
    if Q is None:
        return np.nan, None

    segment = heartbeat.iloc[:Q]  # Select left of Q wave
    P = signal_findpeaks(segment["Signal"],
                         height_min=0.05 * (segment["Signal"].max() -
                                            segment["Signal"].min()))

    if len(P["Peaks"]) == 0:
        return np.nan, None
    P = P["Peaks"][-1]  # Select most right-hand side
    from_R = R - P  # Relative to R
    return rpeak - from_R, P




def _ecg_delineator_derivative_S(rpeak, heartbeat, R):
    segment = heartbeat[0:]  # Select right hand side
    S = signal_findpeaks(-segment["Signal"],
                         height_min=0.05 * (segment["Signal"].max() -
                                            segment["Signal"].min()))

    if len(S["Peaks"]) == 0:
        return np.nan, None

    S = S["Peaks"][0]  # Select most left-hand side
    return rpeak + S, S



def _ecg_delineator_derivative_T(rpeak, heartbeat, R, S):
    if S is None:
        return np.nan, None

    segment = heartbeat.iloc[R + S:]  # Select right of S wave
    T = signal_findpeaks(segment["Signal"],
                         height_min=0.05 * (segment["Signal"].max() -
                                            segment["Signal"].min()))

    if len(T["Peaks"]) == 0:
        return np.nan, None

    T = S + T["Peaks"][0]  # Select most left-hand side
    return rpeak + T, T


def _ecg_delineator_derivative_P_onset(rpeak, heartbeat, R, P):
    if P is None:
        return np.nan, None

    segment = heartbeat.iloc[:P]  # Select left of P wave
    signal = signal_smooth(segment["Signal"].values, size=R/10)
    signal = np.gradient(np.gradient(signal))
    P_onset = np.argmax(signal)

    from_R = R - P_onset  # Relative to R
    return rpeak - from_R



def _ecg_delineator_derivative_T_offset(rpeak, heartbeat, R, T):
    if T is None:
        return np.nan, None

    segment = heartbeat.iloc[R + T:]  # Select left of P wave
    signal = signal_smooth(segment["Signal"].values, size=R/10)
    signal = np.gradient(np.gradient(signal))
    T_offset = np.argmax(signal)

    return rpeak + T + T_offset
