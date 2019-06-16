#!/usr/bin/env python
#RMS2019

import numpy as np
import pandas as pd
import re
from sklearn.base import BaseEstimator, TransformerMixin
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from config import config

class FeatureGenerator(BaseEstimator, TransformerMixin):
    """Categorical data missing value imputer."""

    def __init__(self) -> None:

        #This hard coding is not ideal - come back and fix once the processing is
        #finalized
        self.variables = config.GENERATED_FEATURES

    def fit(self, X: pd.DataFrame, y: pd.Series = None
            ) -> 'FeatureGenerator':
        """Fit statement to accomodate the sklearn pipeline."""

        self.summary = X[self.variables].groupby('credits').mean().reset_index()

        park_names = list(X['credits'].unique())

        self.names_dir = {}
        i = 1
        for name in park_names:
            self.names_dir[name] = i
            i += 1

        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Apply the transforms to the dataframe."""

        X = X.copy()

        def __difference_from_mean_likes_per_follower(row) -> float:

            name = row['credits']
            return (row['nlikes_per_follower'] - \
                self.summary[self.summary['credits']==name]['nlikes_per_follower'].values[0])/self.summary[self.summary['credits']==name]['nlikes_per_follower'].values[0]

        def __difference_from_mean_comments_per_follower(row) -> float:

            name = row['credits']
            return (row['ncomments_per_follower'] - \
                self.summary[self.summary['credits']==name]['ncomments_per_follower'].values[0])/self.summary[self.summary['credits']==name]['ncomments_per_follower'].values[0]

        def __categorize_parks(parkid) -> int:

            return self.names_dir[parkid]

        def __post_rank(row,likes_weight=1,comments_weight=1) -> float:

            return row['mean_nlikes_diff']*likes_weight + row['mean_ncomments_diff']*comments_weight

        X['mean_nlikes_diff'] = X.apply(lambda row: __difference_from_mean_likes_per_follower(row),axis=1)
        X['mean_ncomments_diff'] = X.apply(lambda row: __difference_from_mean_comments_per_follower(row),axis=1)
        X['park_id'] = X['credits'].apply(__categorize_parks)
        X['rank'] = X.apply(lambda row: __post_rank(row),axis=1)

        return X


class CaptionConstructor(BaseEstimator,TransformerMixin):

    def __init__(self) -> None:

        return None

    def fit(self, X: pd.DataFrame, y: pd.Series = None) -> 'CaptionConstructor':

        #List of tags that we don't want to include
        self.hashtagQClist = config.HASHTAG_QC
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:

        X = X.copy()

        def __extract_hashtags(string):

            try:
                hashtags = [re.sub(r"(\W+)$", "", j) for j in set([i for i in string.split() if i.startswith("#")])]
            except:
                return np.nan
            if len(hashtags) == 0:
                return np.nan
            else:
                return hashtags

        def __extract_pcredits(row):
            string = row['caption']

            try:
                pcredits = [re.sub(r"(\W+)$", "", j) for j in set([i for i in string.split() if i.startswith("@")])]
                pcredits.append('@'+row['credits'])
            except:
                return np.nan

            return pcredits

        def __hashtagQC(hashtags):
            
            hashstring = ''.join(hashtags).lower()
            for word in self.hashtagQClist:
                if word in hashstring:
                    return np.nan
            return [e.lower() for e in hashtags if len(e) > 1]

        def __generate_repost_caption(row):
    
            caption = row['caption']
            date = row['postdate']
            credit = row['credits']
            a = re.split("[.!]+", caption)[0]+'!'
            a = re.sub('[@$""'']', '', a)
            if '#' in a:
                return np.nan
            else:
                post_date = f"{date.month:02d}-{date.day:02d}-{date.year}"
                
                comment = f'Here is a segment from the original post, by @{credit} on {post_date}: "{a}"'
                return comment


        X['hashtags'] = X['caption'].apply(__extract_hashtags)
        X['pcredits'] = X.apply(lambda row: __extract_pcredits(row),axis=1)
        X['postdate'] = pd.to_datetime(X['postdate'])

        X.dropna(inplace=True)

        X['hashtags'] = X['hashtags'].apply(__hashtagQC)
        X['repost_comment'] = X.apply(lambda row: __generate_repost_caption(row),axis=1)

        X.dropna(inplace=True)

        X.to_csv('latest_QC_posts.csv')

        return X


class ChoosePost(BaseEstimator, TransformerMixin):

    def __init__(self,captions=config.CAPTIONS,tags=config.TAGS) -> None:

        self.captions_loc = captions
        self.tags_loc = tags

    def fit(self, X: pd.DataFrame, y: pd.Series = None
            ) -> 'ChoosePost':
        """Fit statement to accomodate the sklearn pipeline."""

        ranks = X['rank'].values
        ranks = np.nan_to_num(ranks)
        ranks = ranks - min(ranks)

        #probability of choosing that file to post
        self.p = ranks/sum(ranks)

        self.loaded_comments = pd.read_csv(self.captions_loc,sep='\t',names=['caption'])
        self.loaded_tags = pd.read_csv(self.tags_loc,names=['tag'])

        return self

    def transform(self, X: pd.DataFrame,debug=False) -> dict:

        attempts = 0
        error = 1
        chosen_image = None
        X = self._rank_posts(X)

        while error == 1 and attempts < 10:

            #try:

                pp = np.random.choice(np.arange(len(X)),size=1,replace=False,p=self.p)[0]
                chosen_image = X.iloc[pp]['Flocation']
                chosen_image_caption = X.iloc[pp]['repost_comment']
                chosen_image_hashtags = X.iloc[pp]['hashtags']
                chosen_image_pcredits = X.iloc[pp]['pcredits']

                repost_comment = self._generate_caption_basic(self.loaded_comments,self.loaded_tags,\
                    chosen_image_caption,list(chosen_image_pcredits),list(chosen_image_hashtags))

                #Some QC stage here to determine if the chosen image is OK
                error = 0

            #except:
            #    attempts += 1

        if chosen_image is None:

            print("ERROR!")

        else:

            if debug == True:

                print(repost_comment)

                image = mpimg.imread(chosen_image)
                plt.imshow(image)
                plt.axis('off')
                plt.show()

        return {'Image':chosen_image,'Caption':repost_comment}

    def _rank_posts(self,X,variable='rank') -> pd.DataFrame:

        X.sort_values(by=variable,ascending=False,inplace=True)

        return X

    def _generate_caption_basic(self,loaded_comments,loaded_tags,base_caption,credits,hashtags):
        
        """Run this to generate a caption specific to the image that has been chosen"""
        
        comments_list = list(loaded_comments['caption'])
        tags_list = list(loaded_tags['tag'])
        
        chosen_caption = np.random.choice(comments_list,size=1)[0]
        chosen_tags = list(np.random.choice(tags_list,size=20,replace=False))


        if ' - ' in chosen_caption:
            caption_parts = chosen_caption.split(' - ')
            chosen_caption = '"'+caption_parts[0]+'"'+' - '+caption_parts[1]
        
        for hashtag in hashtags:
            if hashtag not in chosen_tags:
                chosen_tags.append(hashtag)
        
        credits = ' '.join(list(set(credits)))

        tl1 = config.TAG_LINE_1
        tl2 = config.TAG_LINE_2
        tl3 = config.TAG_LINE_3

        repost_caption = f'{chosen_caption}\n\n\n{base_caption}\n📸: {credits}\n\n{tl1}\n\n{tl2}\n\n{tl3}\n\n\n\n\n{chosen_tags}'
        
        return repost_caption
    


