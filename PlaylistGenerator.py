import os

import psycopg2
import spotipy
import spotipy.util as util
from scraping.utils import load_env_from_env_file


class SpotifyConnector(object):
    def __init__(self, scope='playlist-modify-public', is_public=True):
        self.username = os.environ['SPOTIFY_USERNAME']
        self.client_id = os.environ['SPOTIFY_CLIENT_ID']
        self.client_secret = os.environ['SPOTIFY_CLIENT_SECRET']
        self.redirect_uri = os.environ['SPOTIFY_REDIRECT_URI']

        self.is_public = is_public
        if is_public:
            self.scope = scope
        else:
            self.scope = 'playlist-modify-private'

    def get_token(self):
        token = util.prompt_for_user_token(self.username,
                                           self.scope,
                                           client_id=self.client_id,
                                           client_secret=self.client_secret,
                                           redirect_uri=self.redirect_uri)
        return token


class PlaylistGenerator(SpotifyConnector):
    def __init__(self, playlist_name, query_results):
        super(PlaylistGenerator, self).__init__()

        self.playlist_name = playlist_name
        self.query_results = query_results

        self.token = self.get_token()
        self.sp_client = spotipy.Spotify(auth=self.token)
        self.missed_list = []

    def find_playlist_id(self, name):
        playlists = self.sp_client.current_user_playlists()
        for playlist in playlists['items']:
            if playlist['name'] == name:
                return str(playlist['id'])

    def generate_playlist(self):
        if self.token:

            self.sp_client.user_playlist_create(self.username, self.playlist_name, public=self.is_public)
            playlist_id = self.find_playlist_id(self.playlist_name)

            query_result = self.query_results

            for row in query_result:
                song, artist = self.clean_song_artist(uncleaned_song=row[1],
                                                      uncleaned_artist=row[0])
                try:
                    ids = self.find_spotify_uri(song=song, artist=artist)
                    self.sp_client.user_playlist_add_tracks(self.username, playlist_id, tracks=[ids])
                except:
                    self.missed_list.append({'song': song, 'artist': artist})
        else:
            print("Can't get token for {}".format(self.username))

    def find_spotify_uri(self, song, artist):
        results = self.sp_client.search(q='artist:' + artist + ' AND track:' + song,
                                        limit=1,
                                        type='track')
        return results['tracks']['items'][0]['id']

    @staticmethod
    def clean_song_artist(uncleaned_song, uncleaned_artist):
        song_cleaner = SongCleaner(uncleaned_song)
        cleaned_song = song_cleaner.clean_song()
        artist_cleaner = ArtistCleaner(uncleaned_artist)
        cleaned_artist = artist_cleaner.clean_artist()
        return cleaned_song, cleaned_artist


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


def write_query(data_year, high_peak, low_peak):
    """
    Note: Query should return just two columns, the first being the artists you want, the second being the songs.
    """
    query = """
    SELECT artist, song 
FROM songbase.song_peaks_mv 
WHERE chart_peak BETWEEN %s AND %s AND 
EXTRACT(YEAR FROM week_start_date) = %s
"""
    conn = psycopg2.connect(dbname=os.environ['DB_NAME'],
                            user=os.environ['DB_USER'],
                            host=os.environ['DB_HOST'],
                            port=os.environ['DB_PORT'])
    cur = conn.cursor()
    cur.execute(query, (high_peak, low_peak, data_year))
    result = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()
    return result


if __name__ == '__main__':
    load_env_from_env_file()
    start_year = 2020
    end_year = 2020
    high_peak = 1
    low_peak = 40

    for year in range(start_year, end_year + 1):  # range is open interval so upper year not included
        songs_query = write_query(year, high_peak, low_peak)
        gen = PlaylistGenerator('{0} to {1} hits from {2}'.format(high_peak, low_peak, year), songs_query)
        gen.generate_playlist()
        if gen.missed_list:
            print('=============== Missed songs from {0} ==============='.format(year))
            for i in gen.missed_list:
                print(i['song'] + ' by ' + i['artist'])

