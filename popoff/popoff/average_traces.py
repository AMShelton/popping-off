import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import gridspec
import pickle
import pandas as pd
import seaborn as sns

from Session import SessionLite
from loadpaths import loadpaths


class AverageTraces():
    
    def __init__(self, flu_flavour):

        """ Class to load and process Session objects from Session.py 
            and create trial by trial arrays across multiple sessions
            sorted by trial types and brain area.

            Input Arguments
            -----------------
            flu_flavour -- which flu data type to load, valid inputs:
                           [dff, denoised_flu, spks, raw]

            Methods
            -----------------
            load_sessions    -- loads the sessions pkls built by Session.py
                                and defined by flu flavour. Called on __init__
            match_framerates -- patch frames_use attribute to Session objects
                                allowing for simultaneous analysis of 5 Hz and
                                30 Hz data.
            build_trace_dict -- builds a dictionary with keys 's1' and 's2'. Each
                                val contains a tuple of arrays [n_trials x n_frames] containing
                                cell averaged data for every trial recorded across all
                                sessions. Array 0 in tuple == behaviour data; array 2 in tuple ==
                                prereward data.
            tt_raveled       -- get the indexs of trial types matched to arrays in trace_dict.
                                Inputs:
                                trial_type -> [easy, test, nogo, all]
                                trial_outcome -> [hit, miss, fp, cr, ar_miss, ur_hit, all]
                                Returns:
                                boolean list of trials of both trial_type and trial_outcome
            s1s2_plot        -- plot trial averaged traces of trial types across brain areas
                                see average_traces.ipynb

            """


        self.flu_flavour = flu_flavour
        self.user_paths = loadpaths()
        self.load_sessions()
        self.match_framerates()


    def load_sessions(self):

        base_path = self.user_paths['base_path']
        if self.flu_flavour == 'denoised_flu':
            sessions_file = 'sessions_lite_denoised_flu.pkl'
        elif self.flu_flavour == 'dff':
            sessions_file = 'sessions_lite_flu.pkl'
        elif self.flu_flavour == 'spks':
            sessions_file = 'sessions_lite_spks.pkl'
        elif self.flu_flavour == 'raw':
            sessions_file = 'sessions_lite_flu_raw.pkl'
        else:
            raise ValueError('flu_flavour not recognised')
            
        sessions_path = os.path.join(base_path, sessions_file)
                                 
        with open(sessions_path, 'rb') as f:
            self.sessions = pickle.load(f)


    @property
    def tp_dict(self):
        ## Integrate different imaging frequencies:
        freqs = np.unique([ss.frequency for _, ss in self.sessions.items()])
        tp_dict = {}
        for ff in freqs:
            # assume pre_seconds & post_seconds equal for all sessions
            for _, ss in self.sessions.items():   
                if ss.frequency == ff:
                    tp_dict[ff] = ss.filter_ps_time

        if len(freqs) == 2:  # for hard-coded bit next up
            tp_dict['mutual'] = np.intersect1d(ar1=tp_dict[freqs[0]], 
                                               ar2=tp_dict[freqs[1]])
        elif len(freqs) == 1:
            tp_dict['mutual'] = tp_dict[freqs[0]]
        
        return tp_dict


    def match_framerates(self):
    
        # Find the frames to use that match across all sessions
        baseline_start = -2  # Could be a param of class?
        self.times_use = self.tp_dict['mutual']
        self.times_use = self.times_use[self.times_use >= baseline_start]

        for idx, session in self.sessions.items():

            session.frames_use = [session.filter_ps_array
                                 [np.where(session.filter_ps_time == tt)[0][0]] 
                                 for tt in self.times_use]

            session.frames_use = np.array(session.frames_use)
                
            assert len(self.times_use) == len(session.frames_use) 
    

    def build_trace_dict(self):

        self.trace_dict = {

        's1': self.trace_tuple('s1'),
        's2': self.trace_tuple('s2')

        }


    def trace_tuple(self, region):
        
        behaviour = self.session_stacker(region, prereward=False, 
                                         sub_baseline=True)
        prereward = self.session_stacker(region, prereward=True,
                                         sub_baseline=True)
        
        return behaviour, prereward


    def session_stacker(self, cells_include='s1', prereward=False,
                        sub_baseline=True):
       
        for idx, session in self.sessions.items():

            if cells_include == 's1':
                cell_bool = session.s1_bool
            elif cells_include == 's2':
                cell_bool = session.s2_bool
            
            if not prereward:
                behaviour_trials = session.behaviour_trials[cell_bool, :, :]
            else:
                behaviour_trials = session.pre_rew_trials[cell_bool, :, :]
            
            baseline_frames = np.where((session.filter_ps_time>=-2) & 
                                       (session.filter_ps_time<0))[0]
            baseline = np.mean(behaviour_trials[:, :, baseline_frames], 2)
            
            if sub_baseline:
                baseline_subbed = behaviour_trials[:, :, session.frames_use] \
                                  - baseline[:,:,np.newaxis]
            else:
                baseline_subbed = behaviour_trials[:, :, session.frames_use]
            
            if idx == 0:
                stacked_trials = np.mean(baseline_subbed, 0)
            else:
                stacked_trials = np.vstack((stacked_trials, 
                                            np.mean(baseline_subbed, 0)))
            
        return stacked_trials


    def tt_idxs(self, session, trial_type='all', trial_outcome='all'):
    
        assert len(session.photostim) == len(session.decision)

        if trial_type == 'nogo':
            type_use = session.photostim == 0
        elif trial_type == 'test':
            type_use = session.photostim == 1
        elif trial_type == 'easy':
            type_use = session.photostim == 2
        elif trial_type == 'all':
            type_use = np.repeat(True, len(session.photostim))
            
        if trial_outcome == 'hit' or trial_outcome=='fp':
            outcome_use = np.logical_and(session.decision == 1, 
                                         session.unrewarded_hits==False)
        elif trial_outcome == 'miss' or trial_outcome=='cr':
            outcome_use = np.logical_and(session.decision == 0,
                                         session.autorewarded==False)
        elif trial_outcome == 'ar_miss':
            outcome_use = session.autorewarded
        elif trial_outcome == 'ur_hit':
            outcome_use = session.unrewarded_hits
        elif trial_outcome == 'all':
            outcome_use = np.repeat(True, len(session.decision)) 
            
        return np.logical_and(type_use, outcome_use)


    def balanced_hitmiss(self, session, hits, misses):

        balanced_hits = np.full_like(hits, False)
        balanced_misses = np.full_like(misses, False)


        subsets = np.unique(session.trial_subsets)

        for subset in subsets:

            trial_idxs = session.trial_subsets == subset
            subset_hits = np.logical_and(trial_idxs, hits)
            subset_misses = np.logical_and(trial_idxs, misses)

            subset_hits, subset_misses = match_booleans(subset_hits, 
                                                        subset_misses)

            balanced_hits[np.where(subset_hits)[0]] = True
            balanced_misses[np.where(subset_misses)[0]] = True

        assert sum(balanced_hits) == sum(balanced_misses)
        
        return balanced_hits, balanced_misses


        
    def tt_raveled(self, trial_type='all', trial_outcome='all', balance=False):

        trials_use = []
        
        for _, session in self.sessions.items():
            
            if balance and trial_type=='test':
                
                hits = self.tt_idxs(session, trial_type, 'hit')
                misses = self.tt_idxs(session, trial_type, 'miss')
                balanced_hits, balanced_misses = self.balanced_hitmiss(session, 
                                                                       hits,
                                                                       misses)
                if trial_outcome == 'hit':
                    trials_use.append(balanced_hits)
                elif trial_outcome == 'miss':
                    trials_use.append(balanced_misses)
                    
            else:
                trials_use.append(self.tt_idxs(session, 
                                               trial_type,
                                               trial_outcome))
                
        return np.concatenate(trials_use)


    @staticmethod
    def match_booleans(arr1, arr2):
    
        ''' match two boolean arrays to have the same number of Trues 
            without moving position of existing Trues '''
        
        s1 = sum(arr1)
        s2 = sum(arr2)
        
        if s1 == s2:
            pass
        elif s1 > s2:
            arr1[np.random.choice(np.where(arr1)[0], s1-s2, replace=False)] = False
        elif s2 > s1:
            arr2[np.random.choice(np.where(arr2)[0], s2-s1, replace=False)] = False
            
        assert sum(arr1) == sum(arr2), f'{sum(arr1)} {sum(arr2)}; {s1} {s2}'
        
        return arr1, arr2


    def average_trace_plotter(self, df_plot, tt):
        
        color_tt = {'hit': 'green', 'miss': 'grey', 'fp': 'magenta', 
                    'cr': 'brown', 'ur_hit': '#7b85d4', 'ar_miss': '#e9d043',
                    'spont_rew': 'darkorange'}

        sns.lineplot(data=df_plot[df_plot['timepoint'] <= 0], x='timepoint', 
                     y='diff_dff', linewidth=3, color=color_tt[tt], 
                     label=tt, ci=95)

        sns.lineplot(data=df_plot[df_plot['timepoint'] >= 0], x='timepoint', 
                     y='diff_dff', linewidth=3, color=color_tt[tt], 
                     label=None, ci=95)


    def plotting_df(self, stacked_trials, stacked_prereward=None, 
                    stim_type='test', balance=False):
        
        outcomes = ['hit', 'miss', 'ur_hit', 'ar_miss', 'spont_rew', 'cr', 'fp']
        outcomes = ['hit', 'miss', 'spont_rew', 'cr', 'fp']
        
        tt_mapper = {

            'hit': stim_type,
            'miss': stim_type,
            'ur_hit': stim_type,
            'ar_miss': stim_type,
            'spont_rew': None,
            'cr': 'nogo',
            'fp': 'nogo'
        }

        for outcome in outcomes:
            
            if outcome=='spont_rew':
                assert stacked_prereward is not None
                diff_dff = stacked_prereward
            else:
                trials_use = self.tt_raveled(tt_mapper[outcome], outcome, 
                                             balance=balance)
                diff_dff = stacked_trials[trials_use, :]
            
            d = {name: np.array([]) for name in ['diff_dff', 'timepoint']}  
            d['diff_dff'] = diff_dff.ravel() 
            d['timepoint'] = np.tile(self.times_use, diff_dff.shape[0])

            df_plot = pd.DataFrame(d) 
            
            self.average_trace_plotter(df_plot, outcome)


    def s1s2_plot(self, ylims, grid, stim_type='test', balance=False):

        # PREREWRAD S2 DIFFERNET?
        plt.subplots_adjust(wspace=0.4,hspace=0.4)
        
        gs = gridspec.GridSpecFromSubplotSpec(1, 2, grid, width_ratios=[1, 1]) 
        ax0 = plt.subplot(gs[0])
        ax1 = plt.subplot(gs[1])
        
        for idx, region in enumerate(['s1', 's2']):
            plt.subplot(gs[idx])
            d = self.plotting_df(*self.trace_dict[region], stim_type, balance)
            
            plt.ylim(ylims)
            plt.title('Average {} response'.format(region))
            plt.axhline(0)
            plt.xlabel('Time (s)')
            
            plt.ylabel(self.flu_flavour)
            if idx == 0:
                plt.legend(fontsize=14)
            else:
                plt.legend().set_visible(False)
            
