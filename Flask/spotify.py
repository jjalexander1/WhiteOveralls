import os
import requests
import spotipy.util as util


class SpotifyConnector(object):
    def __init__(self, scopes=None):
        self.username = os.environ['SPOTIFY_USERNAME']
        self.client_id = os.environ['SPOTIFY_CLIENT_ID']
        self.client_secret = os.environ['SPOTIFY_CLIENT_SECRET']
        self.redirect_uri = os.environ['SPOTIFY_REDIRECT_URI']

        self.scopes = scopes

    def get_token(self):
        # params = dict(response_type='code',
        #               scope=self.scopes,
        #               client_id=self.client_id,
        #               client_secret=self.client_secret,
        #               redirect_uri=self.redirect_uri)
        # resp = requests.get(url='https://accounts.spotify.com/authorize',
        #                     params=params)
        # resp
        token = util.prompt_for_user_token(username=self.username,
                                           scope=self.scopes,
                                           client_id=self.client_id,
                                           client_secret=self.client_secret,
                                           redirect_uri=self.redirect_uri)
        return token


class SpotifyCleaner(object):
    def __init__(self, to_be_cleaned):
        self.to_be_cleaned = to_be_cleaned.lower()
        self.bad_symbols = ['{', '!', ',', '...', '(']
        self.feat_keywords = [' ft ', ' feat ', ' featuring ', ' ft. ', ' feat. ']  # must have space separation

    def remove_featuring(self, to_clean):
        for word in self.feat_keywords:
            if word in to_clean:
                split_word = to_clean.split(word)
                return split_word[0], split_word[1]
        return to_clean, None

    def remove_unnecessary_symbols(self, to_clean):
        for symbol in self.bad_symbols:
            if symbol in to_clean:
                return to_clean.split(symbol)[0]
        return to_clean

    def rm_apostrophe(self, to_clean):
        return to_clean.replace('\'', '')


    @staticmethod
    def sep_multiples(word, separator):
        if separator in word:
            separated = word.split(separator)
            return separated[0], separated[1]
        else:
            return word, None


class SongCleaner(SpotifyCleaner):
    """
    create a SongCleaner object and then call its clean_song() method.
    """
    def __init__(self, song):
        super(SongCleaner, self).__init__(song)

    def clean_song(self):
        clean1, _ = self.remove_featuring(self.to_be_cleaned)
        clean2, _ = self.sep_multiples(clean1, '/')
        clean3, _ = self.sep_multiples(clean2, '&')
        clean4 = self.rm_apostrophe(clean3)
        return self.remove_unnecessary_symbols(clean4)


class ArtistCleaner(SpotifyCleaner):
    """
    create an ArtistCleaner object and then call its clean_artist() method.
    """
    def __init__(self, artist):
        super(ArtistCleaner, self).__init__(artist)

    def remove_the(self, stri):
        start = 'the'
        if stri.startswith(start+' '):
            return stri[len(start):]
        return stri

    def clean_artist(self):
        main_artist, featured_artist = self.remove_featuring(self.to_be_cleaned)
        cleaned_main_artist = self.remove_unnecessary_symbols(main_artist)
        clean1_main, _ = self.sep_multiples(cleaned_main_artist, '/')
        clean2_main, _ = self.sep_multiples(clean1_main, '&')
        clean3 = self.rm_apostrophe(clean2_main)
        return self.remove_the(clean3)
