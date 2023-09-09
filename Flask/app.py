from flask import Flask, render_template, request
from wtforms import SelectField, SubmitField, BooleanField, TextField
from flask_wtf import FlaskForm
import spotipy
import dotenv
import psycopg2
import os
import random
import wikipedia
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from spotify import SpotifyConnector, SongCleaner, ArtistCleaner
from scraping.lastfm import LastFMHelper

dotenv.load_dotenv('flaskenv.env', verbose=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'JJASpotifyAppKey'


class SongLimiterForm(FlaskForm):
    intros = BooleanField("Intros")
    display_info_by_default = BooleanField("Display Info By Default")
    start_year = SelectField("Start Year")
    end_year = SelectField("End Year")
    min_position = SelectField("Min Position")
    max_position = SelectField("Max Position")
    fetch_next_song = SubmitField("Fetch Next Song")


class ArtistPickerForm(FlaskForm):
    artist = TextField("Artist")
    country = SelectField("Country")
    search = SubmitField("Search")


class SpotifyHelper():
    def __init__(self):
        self.spotify_conn = SpotifyConnector(scopes='user-library-read streaming user-read-playback-state')
        self.token = self.spotify_conn.get_token()
        self.sp_client = spotipy.Spotify(auth=self.token)

    @staticmethod
    def fetch_song_artist(max_pos, min_pos, year_start, year_end):
        conn = psycopg2.connect(dbname=os.environ['DB_NAME'],
                                user=os.environ['DB_USER'],
                                host=os.environ['DB_HOST'],
                                port=os.environ['DB_PORT'])

        cur = conn.cursor()
        cur.execute("""
        SELECT 
            song, artist, chart_peak, EXTRACT(YEAR FROM week_start_date)::INT, 
            spotify_track_uri, spotify_song, spotify_artist, spotify_track_duration
        FROM songbase.song_peaks_mv
        WHERE chart_peak BETWEEN %s AND %s
          AND EXTRACT(YEAR FROM week_start_date) BETWEEN %s AND %s
          ORDER BY RANDOM() LIMIT 1
          ;""",
                    (max_pos, min_pos, year_start, year_end))
        result = cur.fetchone()
        cur.close()
        conn.close()
        db_info = dict(song=result[0],
                       artist=result[1],
                       chart_peak=result[2],
                       year=result[3])
        spotify_info = dict(track_uri=result[4],
                            song=result[5],
                            artist=result[6],
                            track_duration=result[7])
        return db_info, spotify_info

    @staticmethod
    def get_random_start_point(track_duration, max_start_pos_frac=0.8):
        max_ms = (track_duration * max_start_pos_frac)  # don't start too close to end
        return random.randint(0, int(max_ms))

    def get_random_spotify_song(self,
                                max_pos,
                                min_pos,
                                year_start,
                                year_end,
                                intro=True):
        while True:
            db_info, spotify_info = self.fetch_song_artist(max_pos,
                                                  min_pos,
                                                  year_start,
                                                  year_end)
            cleaned_song = SongCleaner(db_info['song']).clean_song()
            cleaned_artist = ArtistCleaner(db_info['artist']).clean_artist()
            results = self.sp_client.search(q='artist:' + cleaned_artist + ' AND track:' + cleaned_song,
                                            limit=1,
                                            type='track')
            if results['tracks']['items'] and results['tracks']['items'][0]['id']:
                track_duration = results['tracks']['items'][0]['duration_ms']
                start_ms = self.get_random_start_point(track_duration=track_duration) if not intro else 0
                spotify_info = dict(track_uri=results['tracks']['items'][0]['id'],
                                    song=results['tracks']['items'][0]['name'],
                                    artist=', '.join([i['name'] for i in results['tracks']['items'][0]['artists']]),
                                    track_duration=track_duration)
                return db_info, spotify_info, start_ms
            else:
                print('Could not find {0} by {1}'.format(db_info['song'], db_info['artist']))
                self.log_not_on_spotify(song=db_info['song'], artist=db_info['artist'])

    def get_artist_top_songs(self, artist, country='UK', n_songs=5):
        cleaned_artist = ArtistCleaner(artist).clean_artist()
        result = self.sp_client.search(q='artist:' + cleaned_artist,
                                       limit=1,
                                       type='artist')
        if result['artists']['items'] and result['artists']['items'][0]['id']:
            artist_id = result['artists']['items'][0]['id']
            top_tracks = self.sp_client.artist_top_tracks(artist_id, country=country)
            return top_tracks

    @staticmethod
    def cache_spotify_info(db_info, spotify_info):
        conn = psycopg2.connect(dbname=os.environ['DB_NAME'],
                                user=os.environ['DB_USER'],
                                host=os.environ['DB_HOST'],
                                port=os.environ['DB_PORT'])

        cur = conn.cursor()
        cur.execute("""
                UPDATE songbase.weekly_charts
                SET spotify_track_uri = %s,
                    spotify_song = %s,
                    spotify_artist = %s,
                    spotify_track_duration = %s
                WHERE song = %s
                  AND artist = %s
                  AND (spotify_track_uri IS NULL
                    OR spotify_song IS NULL
                    OR spotify_artist IS NULL
                    OR spotify_track_duration IS NULL
                    OR (spotify_track_uri IS NOT NULL AND (spotify_song != %s 
                                                        OR spotify_artist != %s
                                                        OR spotify_track_duration != %s)))""", ())
        conn.commit()
        cur.execute("""REFRESH MATERIALIZED VIEW songbase.song_peaks_mv;""")
        conn.commit()
        cur.close()
        conn.close()

    @staticmethod
    def log_not_on_spotify(song, artist):
        conn = psycopg2.connect(dbname=os.environ['DB_NAME'],
                                user=os.environ['DB_USER'],
                                host=os.environ['DB_HOST'],
                                port=os.environ['DB_PORT'])

        cur = conn.cursor()
        cur.execute("""
                INSERT INTO songbase.songs_not_on_spotify (song, artist) 
                SELECT %s, %s
                WHERE NOT EXISTS (
                    SELECT song, artist
                    FROM songbase.songs_not_on_spotify
                    WHERE song = %s
                      AND artist = %s
                )""", (song, artist, song, artist))
        conn.commit()
        cur.close()
        conn.close()


@app.route('/', methods=["GET", "POST"])
def home():
    form = SongLimiterForm()
    form.start_year.choices = form.end_year.choices = [(i, i) for i in range(1952, 2021)]
    form.max_position.choices = form.min_position.choices = [(i, i) for i in range(1, 101)]

    db_info = spotify_info = {}
    wiki_page = None
    display_info = 'none'

    if request.method == 'POST':
        if form.display_info_by_default.data:
            display_info = 'block'

        spotify_helper = SpotifyHelper()
        db_info, spotify_info, start_ms = spotify_helper.get_random_spotify_song(max_pos=form.max_position.data,
                                                                                            min_pos=form.min_position.data,
                                                                                            year_start=form.start_year.data,
                                                                                            year_end=form.end_year.data,
                                                                                            intro=form.intros.data)
        device_id = None
        for i in spotify_helper.sp_client.devices()['devices']:
            if i['name'] == u'Jack\u2019s MacBook Pro':
                device_id = i['id']
                break
        if device_id:
            spotify_helper.sp_client.start_playback(device_id=device_id,
                                                    position_ms=start_ms,
                                                    uris=['spotify:track:' + str(spotify_info['track_uri'])])
        page_search = "{song} by {artist}".format(song=db_info['song'], artist=db_info['artist'])
        for page in [page_search, db_info]:
            try:
                wiki_page = wikipedia.page(page)
                wiki_page = wiki_page.url
                break
            except:
                print('Could not get page for {page}'.format(page=page))

        #song_picker.cache_spotify_info(song=song,
        #                              artist=artist,
         #                              spotify_track_id=track_uri,
          #                             spotify_song=spotify_song,
           #                            spotify_artist=spotify_artist,
            #                           spotify_track_duration=spotify_track_duration)
    return render_template('question_writing.html',
                           form=form,
                           db_info=db_info,
                           spotify_info=spotify_info,
                           display_info=display_info,
                           wiki_page=wiki_page)


@app.route('/auth_callback')
def auth_callback():
    return render_template('question_writing.html')


@app.route('/submit_question_answer', methods=["GET", "POST"])
def submit_question_answer():
    question = request.form['question']
    answer = request.form['answer']

    # use creds to create a client to interact with the Google Drive API
    # scope = ['https://spreadsheets.google.com/feeds']
    scopes = ['https://www.googleapis.com/auth/spreadsheets',
              'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(os.environ['CLIENT_FILE'], scopes)
    client = gspread.authorize(creds)

    # Find a workbook by name and open the first sheet
    # Make sure you use the right name here.
    sheet = client.open('SpotifyAppMusicQuestions').sheet1
    sheet.append_row([question, answer])
    return ''  # errors if view function doesn't even return a str



@app.route('/spotify_table', methods=["GET", "POST"])
def spotify_table():
    form = ArtistPickerForm()
    form.country.choices = ['GB', 'US']

    top_tracks = []
    unable_to_find = []

    if request.method == 'POST':
        spotify_helper = SpotifyHelper()
        lastfm_helper = LastFMHelper()
        spotify_tracks = spotify_helper.get_artist_top_songs(artist=form.artist.data,
                                                             country=form.country.data)
        for track in spotify_tracks['tracks']:
            last_fm_data = lastfm_helper.get_n_plays(track['name'], form.artist.data)
            if last_fm_data:
                if 'track' in last_fm_data:
                    top_tracks.append(dict(spotify_data=track,
                                           last_fm_data=last_fm_data['track']))
                else:
                    unable_to_find.append(dict(spotify_data=track))
        top_tracks = sorted(top_tracks, key=lambda x: int(x['last_fm_data']['playcount']), reverse=True)
        for track in top_tracks:  # format playcounts with commas
            track['last_fm_data']['playcount'] = f"{int(track['last_fm_data']['playcount']):,}"
        device_id = None
        for i in spotify_helper.sp_client.devices()['devices']:
            if i['name'] == u'Jack\u2019s MacBook Pro':
                device_id = i['id']
                break
        if device_id:
            spotify_helper.sp_client.start_playback(device_id=device_id,
                                                    uris=['spotify:track:' + str(top_tracks[0]['spotify_data']['id'])])

    return render_template('spotify_table.html',
                           form=form,
                           top_tracks=top_tracks,
                           unable_to_find=unable_to_find)
"""
TODO
Cache all the spotify info as a json object
Make the wiki box size with window
ADD ABILITY TO CONFIGURE WHETHER SONGS ARE RANDOMIZED OR WHETHER YOU GO SEQUENTIALLY THROUGH ALL OF THEM
Update Cleaner to remove {year} from the end
allow cleaner to have multiple tries, and in second try convert number to word
"""

