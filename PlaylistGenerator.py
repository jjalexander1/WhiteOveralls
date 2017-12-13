import spotipy
import psycopg2
import os
import spotipy.util as util
from utils import load_env_from_env_file


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
    def __init__(self, playlist_name, query):
        super(PlaylistGenerator, self).__init__()

        self.playlist_name = playlist_name
        self.query = query

        self.token = self.get_token()
        self.sp_client = spotipy.Spotify(auth=self.token)

    @staticmethod
    def find_playlist_id(client, name):
        playlists = client.current_user_playlists()
        for playlist in playlists['items']:
            if playlist['name'] == name:
                return str(playlist['id'])

    def db_query(self):
        conn = psycopg2.connect(dbname=os.environ['DB_NAME'],
                                user=os.environ['DB_USER'],
                                password=os.environ['DB_PASSWORD'],
                                host=os.environ['DB_HOST'])
        cur = conn.cursor()
        cur.execute(self.query)
        result = cur.fetchall()
        conn.commit()
        cur.close()
        conn.close()
        return result

    def generate_playlist(self):
        if self.token:

            self.sp_client.user_playlist_create(self.username, self.playlist_name, public=self.is_public)
            playlist_id = self.find_playlist_id(self.sp_client, self.playlist_name)

            query_result = self.db_query()

            for row in query_result:
                results = self.sp_client.search(q='artist:' + row[2] + ' AND track:' + row[3],
                                                limit=1,
                                                type='track')
                try:
                    ids = results['tracks']['items'][0]['id']
                    self.sp_client.user_playlist_add_tracks(self.username, playlist_id, tracks=[ids])
                except Exception as e:
                    print('Could not find {0} by {1} because: '.format(row[3], row[2]) + str(e))
        else:
            print "Can't get token for", self.username


def write_query(data_year):
    """
    Note: Query should return just two columns, the first being the artists you want, the second being the songs.
    """
    query = "SELECT * FROM songbase.bestselling WHERE date_year = {0}".format(data_year)
    return query

if __name__ == '__main__':
    load_env_from_env_file()
    for year in range(1952, 2017):
        songs_query = write_query(year)
        test = PlaylistGenerator('Bestselling Songs of ' + str(year), songs_query)
        test.generate_playlist()
