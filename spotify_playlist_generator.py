import spotipy
import psycopg2
import os
import spotipy.util as util
import time
import dotenv


def load_env_from_env_file():
    env_file = os.environ.get('ENV_FILE', None)
    dotenv.load_dotenv(env_file, verbose=True)


class SpotifyCleaner(object):
    """
    issues noticed
      - numbers (e.g. 99 ways vs. ninety-nine ways) -- possibly use the inflect library https://stackoverflow.com/questions/8982163/how-do-i-tell-python-to-convert-integers-into-words
      - americanisms (paralyzed vs. paralysed) -- dunno, maybe a python lib?
      - misspellings (jimmie rodgers vs. jimmy rodgers) - dunno..
      - spotify apostrophes (where they have an apostrophe in their name, but we don't, e.g. Mocking Bird Hill vs. Mockin' Bird Hill) - dunno..
    """
    def __init__(self, to_be_cleaned):
        self.to_be_cleaned = to_be_cleaned.lower()
        self.symbols_to_cut_off_after = ['!', ',', '...', '?', '(', '{', '[']
        self.feat_keywords = [' ft ', ' feat ', ' featuring ', ' ft. ', ' feat. ']  # must have space separation

    def remove_featuring(self, to_clean):
        for word in self.feat_keywords:
            if word in to_clean:
                split_word = to_clean.split(word)
                return split_word[0], split_word[1]
        return to_clean, None

    def remove_unnecessary_symbols(self, to_clean):
        for symbol in self.symbols_to_cut_off_after:
            if symbol in to_clean:
                return to_clean.split(symbol)[0]
        return to_clean

    def remove_brackets(self, to_clean):
        brackets = ['{}', '[]', '()']
        for bracket in brackets:
            if bracket[0] in to_clean and bracket[1] in to_clean:
                to_clean = to_clean[:to_clean.index(bracket[0])] + to_clean[to_clean.index(bracket[1]) + 1:]
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
        clean0 = self.remove_brackets(self.to_be_cleaned)  # do this first
        clean1, _ = self.remove_featuring(clean0)
        clean2, _ = self.sep_multiples(clean1, '/')
        clean3, _ = self.sep_multiples(clean2, '&')
        clean4 = self.rm_apostrophe(clean3)
        return self.remove_unnecessary_symbols(clean4).strip()


class ArtistCleaner(SpotifyCleaner):
    """
    create an ArtistCleaner object and then call its clean_artist() method.
    """
    def __init__(self, artist):
        super(ArtistCleaner, self).__init__(artist)

    def remove_the(self, stri):
        start = 'the'
        if stri.strip().startswith(start+' '):
            return stri[len(start):].strip()
        return stri

    def remove_extra_credits(self, stri):
        conjunctions = [' with ', ' and ', ' starring ', ' - ']  # spaces important, e.g. Andy Williams
        for con in conjunctions:
            stri = stri.split(con)[0].strip()
        return stri

    def clean_artist(self):
        clean0 = self.remove_brackets(self.to_be_cleaned)  # do this first
        main_artist, featured_artist = self.remove_featuring(clean0)
        definite_main_artist = self.remove_extra_credits(main_artist)
        cleaned_main_artist = self.remove_unnecessary_symbols(definite_main_artist)
        clean1_main, _ = self.sep_multiples(cleaned_main_artist, '/')
        clean2_main, _ = self.sep_multiples(clean1_main, '&')
        clean3 = self.rm_apostrophe(clean2_main)
        return self.remove_the(clean3).strip()


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
    def __init__(self, playlist_name, query_results, year=None):
        super(PlaylistGenerator, self).__init__()

        self.playlist_name = playlist_name
        self.query_results = query_results
        self.year = year

        self.token = self.get_token()
        self.sp_client = spotipy.Spotify(auth=self.token)

    @staticmethod
    def find_playlist_id(client, name):
        playlists = client.current_user_playlists()
        for playlist in playlists['items']:
            if playlist['name'] == name:
                return str(playlist['id'])
            else:
                return None

    def generate_playlist(self):
        if self.token:
            if not self.find_playlist_id(self.sp_client, self.playlist_name):
                self.sp_client.user_playlist_create(self.username, self.playlist_name, public=self.is_public)
            playlist_id = self.find_playlist_id(self.sp_client, self.playlist_name)

            for row in self.query_results:
                try:
                    clean_song = SongCleaner(row[1].lower()).clean_song()
                    clean_artist = ArtistCleaner(row[0].lower()).clean_artist()
                except:
                    raise Exception('Could not clean song or artist: {} by {}'.format(row[1], row[0]))
                try:
                    results = self.sp_client.search(q='artist:' + clean_artist + ' AND track:' + clean_song,
                                                    limit=1,
                                                    type='track')
                    ids = results['tracks']['items'][0]['id']
                    self.sp_client.user_playlist_add_tracks(self.username, playlist_id, tracks=[ids])
                except Exception as e:
                    print('{0}: Could not find {1} by {2} because: '.format(self.year, clean_song, clean_artist) + str(e))
                finally:
                    time.sleep(.300)
        else:
            print("Can't get token for user {}", self.username)


def fetch_songs(chart_min, chart_max, year):
    q = """SELECT artist, song
               FROM songbase.song_peaks_mv 
               WHERE chart_peak BETWEEN {0} AND {1} AND EXTRACT(YEAR FROM week_start_date) = '{2}'
               ;""".format(chart_min, chart_max, year)

    conn = psycopg2.connect(dbname=os.environ['DB_NAME'],
                            user=os.environ['DB_USER'],
                            host=os.environ['DB_HOST'],
                            port=os.environ['DB_PORT'])
    cur = conn.cursor()
    cur.execute(q)
    result = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()
    return result


def main():
    load_env_from_env_file()
    chart_min = 16
    chart_max = 20
    year_start = 1952
    year_end = 2021
    for year in range(year_start, year_end + 1):
        song_list = fetch_songs(chart_min, chart_max, year)
        test = PlaylistGenerator('{0}: Songs that peaked between {1} and {2}'.format(year, chart_min, chart_max), song_list, year)
        test.generate_playlist()


if __name__ == '__main__':
    main()